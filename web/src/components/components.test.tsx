import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MOCK } from "@/test/mocks";
import { ClarifyChips, DocketCard, ToolTrace, unescapeHtml } from "./agent";
import { Markdown } from "./Markdown";
import {
  citationText,
  DeclineCard,
  ProvenanceBadge,
  ReconciliationBadge,
  RevisionChip,
  SuppressedCell,
  WarningCallout,
} from "./Provenance";

describe("ProvenanceBadge", () => {
  it("shows edition and table, and opens its card from the keyboard", async () => {
    const user = userEvent.setup();
    render(<ProvenanceBadge p={MOCK.provenance} />);
    const pill = screen.getByRole("button", { name: /JFF 2025 · Table 6\.2/ });
    await user.tab();
    expect(pill).toHaveFocus();
    await user.keyboard("{Enter}");
    const card = await screen.findByRole("dialog");
    expect(within(card).getByText("Judicial Facts and Figures")).toBeInTheDocument();
    expect(within(card).getByText("Table 6.2!D5")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Source file/ })).toHaveAttribute(
      "href",
      MOCK.provenance.url,
    );
    expect(within(card).getByRole("button", { name: /Copy citation/ })).toBeInTheDocument();
  });

  it("builds a citation line", () => {
    expect(citationText(MOCK.provenance)).toBe(
      "Judicial Facts and Figures, JFF 2025, Table 6.2, FY2020 (12 months ending 2020-09-30), cell Table 6.2!D5. " +
        MOCK.provenance.url,
    );
  });
});

describe("RevisionChip", () => {
  it("renders only for revised figures", () => {
    const { rerender, container } = render(
      <RevisionChip status="original" firstValue={554} firstEdition="JB-2020" />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<RevisionChip status="revised" firstValue={554} firstEdition="JB-2020" />);
    expect(screen.getByText("Revised · first published as 554 (JB 2020)")).toBeInTheDocument();
    rerender(<RevisionChip status="revised" firstValue={null} firstEdition={null} />);
    expect(screen.queryByText(/Revised/)).toBeNull();
  });
});

describe("WarningCallout", () => {
  it.each([
    ["info", "data_break", "Data break"],
    ["caution", "inferred_not_official", "Our inference, not official"],
    ["block", "suppressed", "Small groups withheld"],
  ] as const)("%s variant", (severity, code, title) => {
    render(<WarningCallout w={{ code, severity, message: "Because." }} />);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByText("Because.")).toBeInTheDocument();
  });
});

describe("SuppressedCell and ReconciliationBadge", () => {
  it("never shows a suppressed count as a number", () => {
    render(<SuppressedCell n={null} suppressed />);
    expect(screen.getByText("fewer than 10")).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("labels status with words, not only color", () => {
    render(
      <ReconciliationBadge
        b={{
          status: "matched",
          official_value: 1,
          idb_value: 1,
          variance: -900,
          variance_pct: -0.31,
          explanation: null,
        }}
      />,
    );
    expect(screen.getByText("Matched")).toBeInTheDocument();
    expect(screen.getByText(/−900, −0\.3%/)).toBeInTheDocument();
  });
});

describe("DeclineCard", () => {
  it("offers the alternative as a follow-up", async () => {
    const onAsk = vi.fn();
    render(<DeclineCard d={MOCK.decline} onAsk={onAsk} />);
    expect(screen.getByText(/on judge-identifying statistics/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Ask instead/ }));
    expect(onAsk).toHaveBeenCalledWith(MOCK.decline.alternative);
  });
});

describe("agent components", () => {
  it("DocketCard shows untrusted text as text", () => {
    const { container } = render(<DocketCard card={MOCK.docket} />);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/<script>alert\(1\)<\/script> 28:1332 Diversity/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open on CourtListener/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer nofollow",
    );
  });

  it("DocketCard never links outside CourtListener", () => {
    render(<DocketCard card={{ ...MOCK.docket, url: "https://evil.example/x" }} />);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("unescapes entities once, without creating markup", () => {
    expect(unescapeHtml("&lt;b&gt; &amp;amp; &#x27;x&#x27;")).toBe("<b> &amp; 'x'");
  });

  it("ClarifyChips sends the chosen value, or null to skip", async () => {
    const onChoose = vi.fn();
    render(<ClarifyChips ev={MOCK.clarify} onChoose={onChoose} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Civil filings per judgeship (unweighted)" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(onChoose.mock.calls).toEqual([["civil_filings_per_judgeship"], [null]]);
  });

  it("ToolTrace lists calls, statuses and arguments when opened", async () => {
    render(<ToolTrace steps={MOCK.steps} />);
    await userEvent.click(screen.getByRole("button", { name: /Show your work: 2 tool calls/ }));
    expect(screen.getByText("explain_change")).toBeInTheDocument();
    expect(screen.getByText(/ok · 652 ms/)).toBeInTheDocument();
    expect(screen.getByText("running…")).toBeInTheDocument();
    expect(screen.getByText(/courts=FL-N/)).toBeInTheDocument();
  });
});

describe("Markdown", () => {
  it("renders structure without letting markup through", () => {
    const { container } = render(
      <Markdown
        text={
          "## Heading\n\nSome **bold** and `code`.\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n<img src=x onerror=alert(1)> [bad](javascript:alert(1)) [ok](https://www.uscourts.gov/)"
        }
      />,
    );
    expect(screen.getByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("table td")?.textContent).toBe("1");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    const links = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links).toEqual(["https://www.uscourts.gov/"]);
  });
});
