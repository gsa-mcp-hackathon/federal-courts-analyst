// A turn's UI state, folded from its events (pure; unit-tested).
import type {
  AgentEvent,
  ChartSpec,
  CitationEvent,
  ClarifyEvent,
  DocketCard,
  ToolCallEvent,
  ToolResultEvent,
  TurnEnd,
  WarningEvent,
} from "./types.gen";

export interface ToolStep {
  call: ToolCallEvent;
  result?: ToolResultEvent;
}

export interface TurnState {
  question: string;
  turnId: string | null;
  model: string | null;
  status: "idle" | "streaming" | "waiting" | "done" | "error";
  thinking: string | null;
  text: string;
  steps: ToolStep[];
  warnings: WarningEvent[];
  charts: ChartSpec[];
  dockets: { card: DocketCard; callId: string }[];
  citations: CitationEvent[];
  clarify: ClarifyEvent | null;
  end: TurnEnd | null;
  error: { code: string; message: string } | null;
  events: AgentEvent[];
}

export function initialTurn(question = ""): TurnState {
  return {
    question,
    turnId: null,
    model: null,
    status: question ? "streaming" : "idle",
    thinking: null,
    text: "",
    steps: [],
    warnings: [],
    charts: [],
    dockets: [],
    citations: [],
    clarify: null,
    end: null,
    error: null,
    events: [],
  };
}

export function reduceTurn(s: TurnState, e: AgentEvent): TurnState {
  const next: TurnState = { ...s, events: [...s.events, e] };
  switch (e.type) {
    case "turn_start":
      return { ...next, turnId: e.turn_id, model: e.model, status: "streaming" };
    case "thinking":
      return { ...next, thinking: e.text };
    case "tool_call":
      return { ...next, thinking: null, steps: [...s.steps, { call: e }] };
    case "tool_result":
      return {
        ...next,
        status: s.status === "waiting" ? "streaming" : s.status,
        clarify: s.clarify && s.clarify.turn_id === s.turnId ? null : s.clarify,
        steps: s.steps.map((st) => (st.call.call_id === e.call_id ? { ...st, result: e } : st)),
      };
    case "clarify":
      return { ...next, status: "waiting", clarify: e };
    case "text_delta":
      return { ...next, thinking: null, text: s.text + e.text };
    case "citation":
      return { ...next, citations: [...s.citations, e] };
    case "chart":
      return { ...next, charts: [...s.charts, e.spec] };
    case "docket":
      return { ...next, dockets: [...s.dockets, { card: e.card, callId: e.call_id }] };
    case "warning":
      return s.warnings.some((w) => w.message === e.message)
        ? next
        : { ...next, warnings: [...s.warnings, e] };
    case "error":
      return { ...next, error: { code: e.code, message: e.message } };
    case "turn_end":
      return {
        ...next,
        end: e,
        thinking: null,
        clarify: null,
        status: s.error || e.stop_reason === "error" ? "error" : "done",
      };
    default:
      return next;
  }
}

export function foldTurn(question: string, events: AgentEvent[]): TurnState {
  return events.reduce(reduceTurn, initialTurn(question));
}
