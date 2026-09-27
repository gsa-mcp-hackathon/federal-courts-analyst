import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseRecorded, replay, SseParser } from "./sse";
import { foldTurn, initialTurn, reduceTurn } from "./turn";
import type { AgentEvent } from "./types.gen";

const recorded = (name: string) =>
  readFileSync(join(__dirname, "..", "..", "public", "demo", name), "utf8");

describe("SseParser", () => {
  it("reassembles events split across chunks and drops keep-alives", () => {
    const p = new SseParser();
    const text =
      ': keep-alive\n\nid: 0\nevent: turn_start\ndata: {"seq":0,"type":"turn_start","turn_id":"t","model":"m","provider":"p","prompt_version":"v"}\n\n' +
      'id: 1\nevent: text_delta\ndata: {"seq":1,"type":"text_delta","text":"Hel';
    const first = p.push(text.slice(0, 40));
    const second = p.push(text.slice(40));
    const third = p.push('lo"}\n\n');
    expect(first).toEqual([]);
    expect(second.map((e) => e.type)).toEqual(["turn_start"]);
    expect(third).toEqual([{ seq: 1, type: "text_delta", text: "Hello" }]);
  });

  it("skips malformed and unknown events", () => {
    const events = new SseParser().push(
      'data: {not json}\n\ndata: {"type":"nope"}\n\ndata: {"seq":0,"type":"thinking","text":"…"}\n\n',
    );
    expect(events.map((e) => e.type)).toEqual(["thinking"]);
  });
});

describe("the recorded FY2020 storyline", () => {
  const events = parseRecorded(recorded("fy2020-storyline.sse"));
  const state = foldTurn("Why did FY2020 change?", events);

  it("parses every event in order", () => {
    expect(events[0]!.type).toBe("turn_start");
    expect(events.at(-1)!.type).toBe("turn_end");
    expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i));
  });

  it("folds into the UI state the page renders", () => {
    expect(state.status).toBe("done");
    expect(state.steps.map((s) => s.call.tool)).toEqual([
      "explain_change",
      "find_cases",
      "sample_dockets",
    ]);
    expect(state.steps.every((s) => s.result?.status === "ok")).toBe(true);
    expect(state.charts).toHaveLength(1);
    expect(state.dockets).toHaveLength(3);
    expect(state.citations.map((c) => c.ref.value)).toEqual([381, 554]);
    expect(state.text).toContain("554");
    // Each warning once, however often it streamed.
    expect(new Set(state.warnings.map((w) => w.message)).size).toBe(state.warnings.length);
  });

  it("replays with the same result", async () => {
    let s = initialTurn("q");
    await replay(events, (e) => (s = reduceTurn(s, e)), { speed: 1e6 });
    expect(s.text).toBe(state.text);
    expect(s.status).toBe("done");
  });
});

describe("turn reducer", () => {
  const start: AgentEvent = {
    seq: 0,
    type: "turn_start",
    turn_id: "t1",
    model: "m",
    provider: "p",
    prompt_version: "v",
  };

  it("waits on a clarification and resumes on the tool result", () => {
    let s = reduceTurn(initialTurn("q"), start);
    s = reduceTurn(s, {
      seq: 1,
      type: "tool_call",
      call_id: "c",
      server: "courts-analyst",
      tool: "get_official_figure",
      arguments: {},
    });
    s = reduceTurn(s, {
      seq: 2,
      type: "clarify",
      turn_id: "t1",
      clarify_id: "0123456789ab",
      clarification: { parameter: "measure", question: "Which?", choices: [], default: null },
    });
    expect(s.status).toBe("waiting");
    expect(s.clarify?.clarify_id).toBe("0123456789ab");
    s = reduceTurn(s, {
      seq: 3,
      type: "tool_result",
      call_id: "c",
      server: "courts-analyst",
      tool: "get_official_figure",
      status: "ok",
      result: null,
      error: null,
      latency_ms: 5,
    });
    expect(s.status).toBe("streaming");
    expect(s.clarify).toBeNull();
    expect(s.steps[0]!.result?.status).toBe("ok");
  });

  it("an error event ends the turn in the error state", () => {
    let s = reduceTurn(initialTurn("q"), start);
    s = reduceTurn(s, { seq: 1, type: "error", code: "model_not_configured", message: "no key" });
    s = reduceTurn(s, {
      seq: 2,
      type: "turn_end",
      usage: { input_tokens: 0, output_tokens: 0, cost_usd: 0, model_requests: 0, tool_calls: 0 },
      latency_ms: 3,
      stop_reason: "error",
    });
    expect(s.status).toBe("error");
    expect(s.error?.code).toBe("model_not_configured");
  });

  it("a recorded decline has a guardrail warning and no model call", () => {
    const s = foldTurn("rank judges", parseRecorded(recorded("judge-decline.sse")));
    expect(s.end?.stop_reason).toBe("declined");
    expect(s.end?.usage.model_requests).toBe(0);
    expect(s.warnings[0]).toMatchObject({
      source: "guardrail",
      severity: "block",
      code: "judge_level",
    });
  });
});
