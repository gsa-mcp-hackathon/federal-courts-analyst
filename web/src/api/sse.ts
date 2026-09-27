// The agent's server-sent events: an incremental parser, the POST stream
// client (EventSource can't POST), and replay of a recorded stream.
import type { AgentEvent, ClarifyEvent } from "./types.gen";

export const EVENT_TYPES = new Set([
  "turn_start",
  "thinking",
  "tool_call",
  "tool_result",
  "clarify",
  "text_delta",
  "citation",
  "chart",
  "docket",
  "warning",
  "turn_end",
  "error",
]);

/** Splits an SSE byte stream into events; comments (keep-alives) are dropped. */
export class SseParser {
  private buf = "";

  push(chunk: string): AgentEvent[] {
    this.buf += chunk.replace(/\r\n/g, "\n");
    const out: AgentEvent[] = [];
    let idx: number;
    while ((idx = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, idx);
      this.buf = this.buf.slice(idx + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .filter((l): l is string => typeof l === "string")
        .join("\n");
      if (!data) continue;
      try {
        const ev = JSON.parse(data) as AgentEvent;
        if (ev && typeof ev === "object" && EVENT_TYPES.has(ev.type)) out.push(ev);
      } catch {
        // A malformed event is skipped, not fatal.
      }
    }
    return out;
  }

  /** The stream ended: parse a final event that had no blank-line terminator. */
  flush(): AgentEvent[] {
    if (!this.buf.trim()) return [];
    const rest = this.buf;
    this.buf = "";
    return this.push(rest + "\n\n");
  }
}

export function parseRecorded(text: string): AgentEvent[] {
  const p = new SseParser();
  return [...p.push(text), ...p.flush()];
}

export class StreamError extends Error {
  readonly status: number | null;
  constructor(message: string, status: number | null = null) {
    super(message);
    this.status = status;
  }
}

/** POST a question and call `onEvent` for each event until the turn ends. */
export async function ask(
  question: string,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) return;
    throw new StreamError(`Couldn't reach the server (${(err as Error).message}).`);
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}) as Record<string, unknown>);
    const msg =
      res.status === 429
        ? "Too many questions in a minute. Try again shortly."
        : ((body as { message?: string }).message ?? `The server answered ${res.status}.`);
    throw new StreamError(msg, res.status);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  let ended = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        for (const ev of parser.flush()) {
          if (ev.type === "turn_end") ended = true;
          onEvent(ev);
        }
        break;
      }
      for (const ev of parser.push(value)) {
        if (ev.type === "turn_end") ended = true;
        onEvent(ev);
      }
    }
  } catch (err) {
    if (signal?.aborted) return;
    throw new StreamError(`The connection dropped (${(err as Error).message}).`);
  }
  if (!ended && !signal?.aborted) throw new StreamError("The answer stopped before it finished.");
}

export async function answerClarification(
  ev: ClarifyEvent,
  choice: string | null,
): Promise<boolean> {
  const res = await fetch(`/api/ask/${encodeURIComponent(ev.turn_id)}/clarify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ clarify_id: ev.clarify_id, choice }),
  });
  return res.status === 202;
}

/** Play recorded events back with human pacing (demo insurance). Paced
 * against a clock, so a late timer (a throttled background tab) catches up
 * by playing several events at once instead of falling further behind. */
export async function replay(
  events: AgentEvent[],
  onEvent: (e: AgentEvent) => void,
  opts: { signal?: AbortSignal; speed?: number } = {},
): Promise<void> {
  const speed = opts.speed ?? 1;
  const wait = (ms: number) =>
    new Promise<void>((resolve) => {
      const t = setTimeout(resolve, ms);
      opts.signal?.addEventListener("abort", () => {
        clearTimeout(t);
        resolve();
      });
    });
  const start = performance.now();
  let due = 0;
  for (const ev of events) {
    if (opts.signal?.aborted) return;
    const ahead = due - (performance.now() - start);
    if (ahead > 4) await wait(ahead);
    if (opts.signal?.aborted) return;
    onEvent(ev);
    due +=
      (ev.type === "text_delta"
        ? 12
        : ev.type === "tool_call"
          ? 450
          : ev.type === "tool_result"
            ? 250
            : 40) / speed;
  }
}
