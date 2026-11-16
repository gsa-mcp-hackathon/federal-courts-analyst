// Mocked backend for e2e journeys: REST from captured fixtures, and a fake
// agent stream inside the page (so a clarify can wait for the user's click).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { keyOf } from "./fixture-urls.mjs";

const FIXTURES = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures", "api.json"), "utf8"),
) as Record<string, { status: number; body: unknown }>;

// Request desk (ADR 0013) responses captured from the real backend; the Ask
// page looks up the library and eligibility on every answer.
const DESK = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures", "desk.json"), "utf8"),
) as Record<string, unknown>;
const DESK_DEFAULTS: Record<string, string> = {
  "/api/desk/library": "library_empty",
  "/api/desk/eligibility": "eligibility",
  "/api/desk/accounts": "accounts",
};

export const unmocked: string[] = [];

export async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith("/api/ask")) return route.fallback();
    const desk = DESK_DEFAULTS[url.pathname];
    if (desk) return route.fulfill({ status: 200, json: DESK[desk] });
    const hit = FIXTURES[keyOf(url.pathname + url.search)];
    if (!hit) {
      unmocked.push(url.pathname + url.search);
      return route.fulfill({
        status: 404,
        json: { error: "not_mocked", message: `No fixture for ${url.pathname}${url.search}` },
      });
    }
    return route.fulfill({
      status: hit.status,
      json: hit.body,
      headers: { "cache-control": "no-cache" },
    });
  });
}

/** Scripted agent turns, served from inside the page: each script is a list
 * of events; `{ waitForClarify: true }` pauses until the page POSTs an answer,
 * and `{ choice: true }` inserts a tool result echoing the chosen measure. */
export type ScriptItem = Record<string, unknown> | { waitForClarify: true } | { choice: true };

export async function mockAgent(page: Page, scripts: Record<string, ScriptItem[]>) {
  await page.addInitScript((scripts: Record<string, ScriptItem[]>) => {
    const w = window as unknown as {
      __clarify: { resolve?: (c: string | null) => void };
      __posted: unknown[];
    };
    w.__clarify = {};
    w.__posted = [];
    const real = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/ask") && init?.method === "POST") {
        const { question } = JSON.parse(String(init.body)) as { question: string };
        const script = scripts[question] ?? scripts["*"];
        if (!script) return new Response(JSON.stringify({ error: "no script" }), { status: 500 });
        const enc = new TextEncoder();
        let seq = 0;
        let choice: string | null = null;
        const stream = new ReadableStream<Uint8Array>({
          async start(ctrl) {
            const send = (ev: Record<string, unknown>) =>
              ctrl.enqueue(
                enc.encode(
                  `id: ${seq}\nevent: ${ev.type}\ndata: ${JSON.stringify({ ...ev, seq: seq++ })}\n\n`,
                ),
              );
            for (const item of script) {
              await new Promise((r) => setTimeout(r, 15));
              if ("waitForClarify" in item) {
                choice = await new Promise<string | null>(
                  (resolve) => (w.__clarify.resolve = resolve),
                );
              } else if ("choice" in item) {
                send({
                  type: "tool_result",
                  call_id: "c1",
                  server: "courts-analyst",
                  tool: "get_official_figure",
                  status: choice ? "ok" : "needs_clarification",
                  result: {
                    status: choice ? "ok" : "needs_clarification",
                    data: choice ? { measure: choice, value: 675 } : null,
                  },
                  error: null,
                  latency_ms: 12,
                });
                send({
                  type: "text_delta",
                  text: choice
                    ? `Civil filings per judgeship (unweighted): 675 (JFF-2025).`
                    : "Which measure did you mean?",
                });
              } else send(item);
            }
            ctrl.close();
          },
        });
        return new Response(stream, { headers: { "content-type": "text/event-stream" } });
      }
      const m = url.match(/\/api\/ask\/([^/]+)\/clarify$/);
      if (m && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { choice: string | null };
        w.__posted.push({ turn: m[1], ...body });
        w.__clarify.resolve?.(body.choice);
        return new Response(JSON.stringify({ status: "accepted" }), { status: 202 });
      }
      return real(input, init);
    };
  }, scripts);
}

export const usage = {
  input_tokens: 1000,
  output_tokens: 50,
  cost_usd: 0.01,
  model_requests: 2,
  tool_calls: 1,
};
