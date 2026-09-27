// The stream client against a mocked server (MSW): a recorded stream sent in
// small chunks, rate limiting, and a connection that drops mid-turn.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { answerClarification, ask, StreamError } from "./sse";
import { foldTurn } from "./turn";
import type { AgentEvent, ClarifyEvent } from "./types.gen";

const recording = readFileSync(
  join(__dirname, "..", "..", "public", "demo", "fy2020-storyline.sse"),
  "utf8",
);

function chunked(text: string, size = 97, cut = text.length): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text.slice(0, cut));
  let i = 0;
  return new ReadableStream({
    pull(ctrl) {
      if (i >= bytes.length) return ctrl.close();
      ctrl.enqueue(bytes.slice(i, i + size));
      i += size;
    },
  });
}

const posted: unknown[] = [];
const server = setupServer(
  http.post("http://localhost/api/ask", async ({ request }) => {
    const { question } = (await request.json()) as { question: string };
    if (question === "flood") return HttpResponse.json({ error: "rate_limited" }, { status: 429 });
    const cut = question === "drop" ? Math.floor(recording.length / 2) : recording.length;
    return new HttpResponse(chunked(recording, 97, cut), {
      headers: { "content-type": "text/event-stream" },
    });
  }),
  http.post("http://localhost/api/ask/:turn/clarify", async ({ request, params }) => {
    posted.push({ turn: params.turn, body: await request.json() });
    return HttpResponse.json({ status: "accepted" }, { status: 202 });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
beforeEach(() => {
  // Relative URLs resolve against the page, as in the browser.
  const real = globalThis.fetch;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
    real(
      typeof input === "string" && input.startsWith("/") ? `http://localhost${input}` : input,
      init,
    ),
  );
});
afterEach(() => vi.unstubAllGlobals());

it("reassembles a chunked stream into the same turn as the recording", async () => {
  const events: AgentEvent[] = [];
  await ask("why?", (e) => events.push(e));
  const s = foldTurn("why?", events);
  expect(events).toHaveLength(249);
  expect(s.status).toBe("done");
  expect(s.dockets).toHaveLength(3);
});

it("reports rate limiting in plain words", async () => {
  await expect(ask("flood", () => undefined)).rejects.toMatchObject({
    status: 429,
    message: expect.stringMatching(/Too many questions/),
  });
});

it("says when the answer stopped before it finished", async () => {
  const events: AgentEvent[] = [];
  const err = await ask("drop", (e) => events.push(e)).catch((e: unknown) => e);
  expect(err).toBeInstanceOf(StreamError);
  expect((err as Error).message).toMatch(/stopped before it finished/);
  expect(events.length).toBeGreaterThan(0);
  expect(events.some((e) => e.type === "turn_end")).toBe(false);
});

it("posts a clarification answer to the turn", async () => {
  const ev = {
    type: "clarify",
    seq: 3,
    turn_id: "turn42",
    clarify_id: "0123456789ab",
    clarification: { parameter: "measure", question: "?", choices: [], default: null },
  } satisfies ClarifyEvent;
  expect(await answerClarification(ev, "civil_filings_per_judgeship")).toBe(true);
  expect(posted).toEqual([
    { turn: "turn42", body: { clarify_id: "0123456789ab", choice: "civil_filings_per_judgeship" } },
  ]);
});
