import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockAgent, mockApi, unmocked, usage } from "./mock";

async function axe(page: Page) {
  const r = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map(
      (v) =>
        `${v.id}: ${v.nodes
          .map((n) => n.target.join(" "))
          .slice(0, 3)
          .join(" | ")}`,
    ),
  ).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});
test.afterEach(() => {
  expect(unmocked, "requests without a fixture").toEqual([]);
});

const CLARIFY_Q = "Filings per judgeship in FY2020?";

test("Ask → clarify → answer with citations", async ({ page }) => {
  await mockAgent(page, {
    [CLARIFY_Q]: [
      {
        type: "turn_start",
        turn_id: "turn1",
        model: "claude-sonnet-5",
        provider: "anthropic",
        prompt_version: "v",
      },
      {
        type: "tool_call",
        call_id: "c1",
        server: "courts-analyst",
        tool: "get_official_figure",
        arguments: { measure: "filings_per_judgeship", fiscal_year: 2020 },
      },
      {
        type: "clarify",
        turn_id: "turn1",
        clarify_id: "0123456789ab",
        clarification: {
          parameter: "measure",
          question: "Which filings per judgeship: weighted or unweighted, total or civil only?",
          choices: [
            {
              value: "weighted_total_filings_per_judgeship",
              label: "Weighted total filings per judgeship",
              description: null,
            },
            {
              value: "civil_filings_per_judgeship",
              label: "Civil filings per judgeship (unweighted)",
              description: null,
            },
          ],
          default: "weighted_total_filings_per_judgeship",
        },
      },
      { waitForClarify: true },
      { choice: true },
      {
        type: "citation",
        ref: {
          citation: "675 (JFF-2025, Table 6.2)",
          value: 675,
          measure: "civil_filings_per_judgeship",
          court: "US",
          fiscal_year: 2020,
          edition: "JFF-2025",
          table_code: "6.2",
          url: "https://www.uscourts.gov/x.xlsx",
          revised: false,
          first_published_value: null,
          first_published_edition: null,
        },
        span: [45, 48],
        call_id: "c1",
      },
      { type: "turn_end", usage, latency_ms: 2100, stop_reason: "end_turn" },
    ],
  });
  await page.goto("/");
  await page.getByLabel("Your question").fill(CLARIFY_Q);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const chips = page.getByRole("group", { name: "Choices" });
  await expect(chips).toBeVisible();
  await expect(page.getByText("Which filings per judgeship")).toBeVisible();
  // Scan only once the panel has finished fading in: mid-fade, its text is
  // partly transparent and fails colour contrast.
  await expect(page.getByLabel("The server needs a choice").locator("..")).toHaveCSS(
    "opacity",
    "1",
  );
  await axe(page);
  await chips.getByRole("button", { name: "Civil filings per judgeship (unweighted)" }).click();
  await expect(
    page.getByText("Civil filings per judgeship (unweighted): 675 (JFF-2025)."),
  ).toBeVisible();
  await expect(chips).toBeHidden();
  const figures = page.getByRole("region", { name: "Figures in this answer" });
  await expect(figures.getByText("675")).toBeVisible();
  await expect(figures.getByRole("link", { name: "JFF 2025 · Table 6.2" })).toHaveAttribute(
    "href",
    "https://www.uscourts.gov/x.xlsx",
  );
  expect(
    await page.evaluate(() => (window as unknown as { __posted: unknown[] }).__posted),
  ).toEqual([{ turn: "turn1", clarify_id: "0123456789ab", choice: "civil_filings_per_judgeship" }]);
  await expect(page).toHaveURL(/\/ask\/turn1$/);
  // The answer survives a reload (replayed from this browser's storage).
  await page.reload();
  await expect(
    page.getByText("Civil filings per judgeship (unweighted): 675 (JFF-2025)."),
  ).toBeVisible();
});

test("A judge request is declined with the policy", async ({ page }) => {
  await mockAgent(page, {
    "*": [
      {
        type: "turn_start",
        turn_id: "turn2",
        model: "no model call",
        provider: "none",
        prompt_version: "v",
      },
      {
        type: "warning",
        code: "judge_level",
        message: "This server can't rank, compare, name or profile individual judges.",
        severity: "block",
        source: "guardrail",
      },
      {
        type: "text_delta",
        text: "This server can't rank judges. Ask about the district instead.",
      },
      {
        type: "turn_end",
        usage: { ...usage, model_requests: 0, tool_calls: 0, cost_usd: 0 },
        latency_ms: 3,
        stop_reason: "declined",
      },
    ],
  });
  await page.goto("/");
  await page.getByLabel("Your question").fill("Rank the judges in S.D.N.Y.");
  await page.keyboard.press("Enter");
  await expect(page.getByText("No judge-level data")).toBeVisible();
  await expect(page.getByText(/stopped: declined/)).toBeVisible();
});

test("Explore → click a district → court profile", async ({ page }) => {
  await page.goto("/explore?measure=weighted-filings-per-judgeship&fy=2025");
  await expect(page.getByText(/all from/)).toContainText("JB 2025");
  await expect(
    page.locator("svg[aria-label^='Map of federal judicial districts'] path").first(),
  ).toBeVisible();
  await axe(page);
  await page.getByRole("radio", { name: "Over 600" }).click();
  await expect(page).toHaveURL(/over=600/);
  const table = page.getByRole("table");
  const rows = table.locator("tbody tr");
  const n = await rows.count();
  expect(n).toBeGreaterThan(5);
  await expect(page.getByText(new RegExp(`${n} of \\d+ districts over 600`))).toBeVisible();
  await table.getByRole("link", { name: "N.D. Fla." }).click();
  await expect(page).toHaveURL(/\/courts\/fl-n$/);
  await expect(page.getByRole("heading", { level: 1, name: "N.D. Fla." })).toBeVisible();
  await expect(page.getByText("Judgeship context, FY2025")).toBeVisible();
  await expect(page.getByText(/Matched|Explained variance|Unexplained/).first()).toBeVisible();
  await axe(page);
});

test("Edition Tracker deep link shows the 554 → 322 revision", async ({ page }) => {
  await page.goto("/editions/weighted-civil-filings-per-judgeship/national/2020");
  await expect(page.getByText("322", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Revised · first published as 554 (JB 2020)")).toBeVisible();
  await expect(page.getByRole("img", { name: /every edition/ })).toBeVisible();
  const history = page.getByRole("table").first();
  await expect(history).toContainText("JFF 2023");
  await axe(page);
  await page.getByText("Show the data as a table").first().click();
  await expect(page.getByRole("cell", { name: "554 (JB-2020)" }).first()).toBeVisible();
});

test("Evaluation page loads", async ({ page }) => {
  await page.goto("/eval");
  await expect(page.getByText("Adversarial, through the agent")).toBeVisible();
  await expect(page.getByText("43 of 47 correct")).toBeVisible();
  await expect(page.getByRole("table")).toContainText("adv-one-number-please");
  await axe(page);
});

test("Methodology and the glossary", async ({ page }) => {
  await page.goto("/methodology");
  await expect(page.getByRole("heading", { name: "Weighted filings per judgeship" })).toBeVisible();
  const terms = page.locator("#glossary dl > div");
  const all = await terms.count();
  await page.getByLabel("Filter terms").fill("judgeship");
  await expect(terms.first()).toContainText(/judgeship/i);
  expect(await terms.count()).toBeLessThan(all);
  await axe(page);
});

test("Presentation mode replays the recording", async ({ page }) => {
  await page.goto("/demo");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Step 2 of 4")).toBeVisible();
  await expect(page.getByRole("region", { name: "Example dockets" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("button", { name: /Show your work: 3 tool calls/ })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Step 3 of 4")).toBeVisible();
});

test("Gallery and dark mode have no serious accessibility issues", async ({ page }) => {
  await page.goto("/dev/gallery");
  await expect(page.getByRole("heading", { name: "Component gallery" })).toBeVisible();
  await axe(page);
  await page.getByRole("button", { name: /Switch to (dark|light) mode/ }).click();
  await axe(page);
});
