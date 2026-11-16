// The request desk in the browser (ADR 0013), against responses captured
// from the real backend (e2e/fixtures/desk.json): the options under an
// answer, the gate's refusal, My requests, the library and the staff screen.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockAgent, mockApi, usage } from "./mock";

const DESK = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures", "desk.json"), "utf8"),
) as Record<string, unknown>;

const QUESTION = "How busy were federal courts per judgeship in FY2020?";
const ANSWER =
  "National weighted civil filings per judgeship were 322 in FY2020 (JFF-2025); the figure was first published as 554 (JB-2020).";

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => v.id)).toEqual([]);
}

async function mockDesk(page: Page, opts: { published?: boolean } = {}) {
  const posted: unknown[] = [];
  await page.route("**/api/desk/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const path = url.pathname.replace("/api/desk", "");
    const json = (key: string, status = 200) =>
      route.fulfill({ status, json: DESK[key], headers: { "cache-control": "no-store" } });
    if (path === "/accounts") return json("accounts");
    if (path === "/eligibility") return json("eligibility");
    if (path === "/library") return json(opts.published ? "library" : "library_empty");
    if (path === "/requests" && method === "POST") {
      const body = route.request().postDataJSON() as { answer_text: string };
      posted.push(body);
      return json(body.answer_text.includes("318") ? "submit_mixed" : "submit_ok");
    }
    if (path === "/requests") return json(opts.published ? "mine_after" : "mine");
    if (path.endsWith("/read")) return json("submit_ok");
    if (path === "/staff/inquiries") return json("staff_inquiries");
    if (path === "/staff/requests") return json("staff_requests");
    if (path === "/staff/audit") return json("staff_audit");
    return route.fulfill({ status: 404, json: { error: "not_mocked" } });
  });
  return posted;
}

function answerScript() {
  return [
    {
      type: "turn_start",
      turn_id: "desk1",
      model: "claude-sonnet-5",
      provider: "anthropic",
      prompt_version: "v",
    },
    { type: "text_delta", text: ANSWER },
    {
      type: "citation",
      ref: {
        citation: "322 (JFF-2025, Table 6.2); revised: first published as 554 (JB-2020)",
        value: 322,
        measure: "weighted_civil_filings_per_judgeship",
        court: "US",
        fiscal_year: 2020,
        edition: "JFF-2025",
        table_code: "6.2",
        url: null,
        revised: true,
        first_published_value: 554,
        first_published_edition: "JB-2020",
      },
      span: null,
      call_id: "c1",
    },
    { type: "turn_end", usage, latency_ms: 1800, stop_reason: "end_turn" },
  ];
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("Ask → ask the statistics office → saved and filed", async ({ page }) => {
  const posted = await mockDesk(page);
  await mockAgent(page, { [QUESTION]: answerScript() });
  await page.goto("/");
  await page.getByLabel("Your question").fill(QUESTION);
  await page.keyboard.press("Enter");
  const keep = page.getByRole("region", { name: "Keep this answer" });
  await expect(keep.getByText(/changed from 554/)).toBeVisible();
  await keep.getByRole("button", { name: "Ask the statistics office why this changed" }).click();
  await keep.getByLabel("Signed in as (demo account)").selectOption("priya");
  await expect(keep.getByLabel(/The answer to save/)).toHaveValue(ANSWER);
  await axe(page);
  await keep.getByRole("button", { name: "Check and save" }).click();
  await expect(keep.getByText(/Request #1001: verified answer saved/)).toBeVisible();
  await expect(keep.getByText(/Would go to AO Statistics Division/)).toBeVisible();
  await expect(keep.getByRole("link", { name: "Follow it in My requests" })).toBeVisible();
  const body = posted[0] as {
    option: string;
    citations: { edition: string; value: number }[];
    inquiry: { fiscal_year: number };
  };
  expect(body.option).toBe("ask_office");
  expect(body.inquiry.fiscal_year).toBe(2020);
  // The revised figure's first printing is offered as a citation too.
  expect(body.citations.map((c) => `${c.value} ${c.edition}`).sort()).toEqual([
    "322 JFF-2025",
    "554 JB-2020",
  ]);
});

test("The gate refuses a mixed-edition answer and says why", async ({ page }) => {
  await mockDesk(page);
  await mockAgent(page, { [QUESTION]: answerScript() });
  await page.goto("/");
  await page.getByLabel("Your question").fill(QUESTION);
  await page.keyboard.press("Enter");
  const keep = page.getByRole("region", { name: "Keep this answer" });
  await keep.getByRole("button", { name: "Save a verified copy" }).click();
  await keep.getByLabel("Signed in as (demo account)").selectOption("priya");
  await keep.getByLabel(/The answer to save/).fill("It was 554 in FY2020 and 318 in FY2021.");
  await keep.getByRole("button", { name: "Check and save" }).click();
  const alert = keep.getByRole("alert");
  await expect(alert).toContainText("Not saved: the answer didn't pass verification");
  await expect(alert).toContainText("554 comes from JB-2020");
  await expect(alert).toContainText("Fix: Use 322 (JFF-2024)");
});

test("My requests shows progress and updates", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/requests");
  await page.getByLabel("Signed in as (demo account)").selectOption("priya");
  const req = page.getByRole("article", { name: "Request 1001" });
  await expect(req.getByText("Waiting for statistics office").first()).toBeVisible();
  await expect(req.getByText(/Sent to the statistics office/)).toBeVisible();
  await expect(page.getByText(/new updates?/)).toBeVisible();
  await axe(page);
});

test("A repeat question finds the approved answer in the library", async ({ page }) => {
  await mockDesk(page, { published: true });
  await mockAgent(page, { [QUESTION]: answerScript() });
  await page.goto("/");
  await page.getByLabel("Your question").fill(QUESTION);
  await page.keyboard.press("Enter");
  const card = page.getByRole("region", { name: "Approved answer" });
  await expect(card).toContainText("An approved answer to a similar question");
  await expect(card).toContainText("re-weighted directly filed MDL cases");
  await page.goto("/library");
  await expect(page.getByText(/Verified: every number checked/).first()).toBeVisible();
  await axe(page);
});

test("The staff screen shows the queue behind its token", async ({ page }) => {
  await mockDesk(page);
  await page.goto("/staff");
  await page.getByPlaceholder("Staff token (DESK_STAFF_TOKEN)").fill("office-token");
  await page.getByRole("button", { name: "Open" }).click();
  const queue = page.getByRole("region", { name: "Inquiry queue" });
  await expect(queue.getByText("1 request waiting")).toBeVisible();
  await expect(queue.getByText(/change from 554/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Audit log" })).toContainText("open_request");
  await axe(page);
});
