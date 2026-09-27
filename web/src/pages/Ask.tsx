import { lazy, Suspense, useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { AnimatePresence, motion } from "motion/react";
import { answerClarification, ask, StreamError } from "@/api/sse";
import { foldTurn, initialTurn, reduceTurn, type TurnState } from "@/api/turn";
import type { AgentEvent, ClarifyEvent } from "@/api/types.gen";
import { ClarifyChips, DocketCard, ToolTrace } from "@/components/agent";
import { Icon } from "@/components/Icon";
import { Markdown } from "@/components/Markdown";
import { RevisionChip, WarningCallout } from "@/components/Provenance";
import { editionLabel, fmtMs, fmtUsd, fmtValue } from "@/lib/format";
import { courtSlug } from "@/lib/courts";
import { byId } from "@/lib/measures";

// The chart library loads with the first chart, not with the page.
const SpecChart = lazy(() => import("@/components/charts").then((m) => ({ default: m.SpecChart })));

export const EXAMPLES = [
  "Why did weighted civil filings per judgeship change so much in FY2020?",
  "Which districts are over 600 weighted filings per judgeship, according to which edition?",
  "What was the national median time to disposition for civil cases in FY2024?",
  "Show me a few example MDL dockets from N.D. Fla. in FY2020.",
  "How busy were federal district courts per judgeship in FY2020?",
];

const STORE = "fca-turn:";

export function saveTurn(t: TurnState) {
  if (!t.turnId) return;
  try {
    localStorage.setItem(STORE + t.turnId, JSON.stringify({ q: t.question, events: t.events }));
  } catch {
    // Storage full or blocked: the answer just isn't replayable later.
  }
}

export function loadTurn(id: string): TurnState | null {
  try {
    const raw = localStorage.getItem(STORE + id);
    if (!raw) return null;
    const { q, events } = JSON.parse(raw) as { q: string; events: AgentEvent[] };
    return foldTurn(q, events);
  } catch {
    return null;
  }
}

export function AskPage({ replayId }: { replayId?: string }) {
  const [turns, setTurns] = useState<TurnState[]>(() => {
    const t = replayId ? loadTurn(replayId) : null;
    return t ? [t] : [];
  });
  const [current, dispatch] = useReducer(
    (s: TurnState, a: { reset: string } | AgentEvent) =>
      "reset" in a ? initialTurn(a.reset) : reduceTurn(s, a),
    initialTurn(),
  );
  const [streamError, setStreamError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busyClarify, setBusyClarify] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const navigate = useNavigate();
  const streaming = current.status === "streaming" || current.status === "waiting";

  const submit = useCallback(
    async (question: string) => {
      const q = question.trim();
      if (!q || streaming) return;
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      setStreamError(null);
      setDraft("");
      dispatch({ reset: q });
      let last: TurnState = initialTurn(q);
      try {
        await ask(
          q,
          (e) => {
            last = reduceTurn(last, e);
            dispatch(e);
          },
          ctrl.signal,
        );
      } catch (err) {
        setStreamError(err instanceof StreamError ? err.message : String(err));
      }
      if (last.turnId) {
        saveTurn(last);
        setTurns((ts) => [...ts, last]);
        dispatch({ reset: "" });
        void navigate({ to: "/ask/$turnId", params: { turnId: last.turnId }, replace: true });
      }
    },
    [streaming, navigate],
  );

  useEffect(() => () => abort.current?.abort(), []);

  const onClarify = async (ev: ClarifyEvent, choice: string | null) => {
    setBusyClarify(true);
    try {
      await answerClarification(ev, choice);
    } finally {
      setBusyClarify(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl">
      {!turns.length && !current.question && (
        <div className="mb-8 max-w-3xl">
          <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink sm:text-5xl">
            Ask about federal court workload
          </h1>
          <p className="mt-3 text-lg text-ink-2">
            Answers come from the official uscourts.gov tables and the FJC Integrated Database.
            Every figure names the edition it comes from, and revised figures say so.
          </p>
        </div>
      )}
      <div className="space-y-10">
        {turns.map((t) => (
          <AnswerView key={t.turnId ?? t.question} turn={t} onAsk={submit} />
        ))}
        {current.question && (
          <AnswerView
            turn={current}
            onAsk={submit}
            onClarify={onClarify}
            busyClarify={busyClarify}
            live
          />
        )}
        {streamError && (
          <div role="alert" className="rounded-lg border border-critical/40 bg-card p-4 text-sm">
            <p className="font-medium text-critical">The answer didn't finish</p>
            <p className="mt-1 text-ink-2">{streamError}</p>
            <button
              type="button"
              onClick={() => {
                const q = current.question || turns.at(-1)?.question;
                if (q) void submit(q);
              }}
              className="mt-2 rounded border border-rule px-3 py-1 hover:bg-paper-2"
            >
              Ask again
            </button>
          </div>
        )}
      </div>
      <form
        className="sticky bottom-4 mt-10"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(draft);
        }}
      >
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <div className="flex items-end gap-2 rounded-xl border border-rule bg-card p-2 shadow-sm focus-within:border-accent">
          <textarea
            id="question"
            rows={2}
            maxLength={2000}
            value={draft}
            placeholder="Ask about filings, pending cases, time to disposition or judgeships…"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit(draft);
              }
            }}
            className="min-h-12 flex-1 resize-none bg-transparent px-2 py-1.5 text-ink outline-none placeholder:text-muted"
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => abort.current?.abort()}
              className="rounded-lg border border-rule px-3 py-2 text-sm text-ink hover:bg-paper-2"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-ink disabled:opacity-40"
            >
              <Icon name="send" />
              Ask
            </button>
          )}
        </div>
        {!turns.length && !current.question && (
          <div className="mt-3 flex flex-wrap gap-2" aria-label="Example questions">
            {EXAMPLES.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => void submit(q)}
                className="rounded-full border border-rule bg-card px-3 py-1 text-left text-sm text-ink-2 hover:border-accent hover:text-ink"
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </form>
    </div>
  );
}

export function AnswerView({
  turn,
  onAsk,
  onClarify,
  busyClarify,
  live,
}: {
  turn: TurnState;
  onAsk?: (q: string) => void;
  onClarify?: (ev: ClarifyEvent, choice: string | null) => void;
  busyClarify?: boolean;
  live?: boolean;
}) {
  const guard = turn.warnings.filter((w) => w.source === "guardrail");
  const other = turn.warnings.filter((w) => w.source !== "guardrail");
  const hasEvidence = turn.charts.length > 0 || turn.dockets.length > 0;
  return (
    <article aria-busy={live && turn.status === "streaming"} className="space-y-4">
      <h2 className="font-serif text-2xl font-semibold text-ink">{turn.question}</h2>
      <div className={hasEvidence ? "grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]" : ""}>
        <div className="min-w-0 space-y-4">
          {guard.map((w) => (
            <WarningCallout key={w.message} w={w} />
          ))}
          {turn.thinking && !turn.text && (
            <p className="flex items-center gap-2 text-sm text-muted" role="status">
              <span className="size-2 animate-pulse rounded-full bg-accent" /> {turn.thinking}
            </p>
          )}
          {live &&
            turn.status === "streaming" &&
            !turn.text &&
            !turn.thinking &&
            turn.steps.length > 0 && (
              <p className="text-sm text-muted" role="status">
                Checking {turn.steps.at(-1)!.call.tool.replace(/_/g, " ")}…
              </p>
            )}
          <div aria-live={live ? "polite" : undefined}>
            <Markdown text={turn.text} className="prose-answer text-ink" />
          </div>
          <AnimatePresence>
            {turn.clarify && onClarify && (
              <motion.div
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <ClarifyChips
                  ev={turn.clarify}
                  busy={busyClarify}
                  onChoose={(c) => onClarify(turn.clarify!, c)}
                />
              </motion.div>
            )}
          </AnimatePresence>
          {turn.citations.length > 0 && <Citations turn={turn} />}
          {other.length > 0 && (
            <div className="space-y-2">
              {other.map((w) => (
                <WarningCallout key={w.message} w={w} />
              ))}
            </div>
          )}
          {turn.error && (
            <div role="alert" className="rounded-lg border border-critical/40 bg-card p-3 text-sm">
              <p className="font-medium text-critical">
                {turn.error.code === "model_not_configured"
                  ? "The agent isn't configured on this server"
                  : "The agent stopped with an error"}
              </p>
              <p className="text-ink-2">{turn.error.message}</p>
              {turn.error.code === "model_not_configured" && (
                <p className="mt-1 text-muted">
                  The Explore and Edition Tracker pages work without it. Presentation mode can
                  replay a recorded answer.
                </p>
              )}
            </div>
          )}
          <ToolTrace steps={turn.steps} />
          {turn.end && (
            <p className="num text-xs text-muted">
              {turn.model} · {fmtMs(turn.end.latency_ms)} · {turn.end.usage.tool_calls} tool calls
              {(turn.end.usage.cost_usd ?? 0) > 0 && ` · ${fmtUsd(turn.end.usage.cost_usd ?? 0)}`}
              {turn.end.stop_reason !== "end_turn" &&
                ` · stopped: ${turn.end.stop_reason.replace(/_/g, " ")}`}
            </p>
          )}
          {onAsk && turn.end?.stop_reason === "declined" && (
            <p className="text-sm text-muted">Try one of the district-level questions below.</p>
          )}
        </div>
        {hasEvidence && (
          <aside aria-label="Evidence" className="min-w-0 space-y-4">
            <Suspense
              fallback={<div className="h-72 animate-pulse rounded-lg bg-paper-2" aria-hidden />}
            >
              {turn.charts.map((c) => (
                <SpecChart key={c.call_id + c.title} spec={c} />
              ))}
            </Suspense>
            {turn.dockets.length > 0 && (
              <section aria-label="Example dockets" className="space-y-2">
                <h3 className="text-sm font-semibold text-ink">Example dockets</h3>
                {turn.dockets.map((d, i) => (
                  <DocketCard key={`${d.callId}-${i}`} card={d.card} />
                ))}
              </section>
            )}
          </aside>
        )}
      </div>
    </article>
  );
}

function Citations({ turn }: { turn: TurnState }) {
  return (
    <section
      aria-label="Figures in this answer"
      className="rounded-lg border border-rule bg-card p-3"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
        Figures in this answer
      </h3>
      <ul className="mt-2 space-y-2">
        {turn.citations.map((c) => {
          const m = byId(c.ref.measure);
          return (
            <li key={c.ref.citation} className="text-sm">
              <span className="num font-semibold text-ink">{fmtValue(c.ref.value)}</span>{" "}
              <span className="text-ink-2">
                {m?.label ?? c.ref.measure.replace(/_/g, " ")},{" "}
                {c.ref.court === "US" ? "national" : c.ref.court}, FY
                {c.ref.fiscal_year}
              </span>{" "}
              {c.ref.url ? (
                <a
                  href={c.ref.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="num rounded-full border border-rule px-2 py-0.5 font-mono text-[0.72rem] text-ink-2 hover:border-accent"
                >
                  {editionLabel(c.ref.edition)} · Table {c.ref.table_code}
                </a>
              ) : (
                <span className="num font-mono text-[0.72rem] text-ink-2">
                  {editionLabel(c.ref.edition)} · Table {c.ref.table_code}
                </span>
              )}{" "}
              <RevisionChip
                status={c.ref.revised ? "revised" : "only_edition"}
                firstValue={c.ref.first_published_value}
                firstEdition={c.ref.first_published_edition}
                to={
                  m
                    ? { measure: m.slug, court: courtSlug(c.ref.court), fy: c.ref.fiscal_year }
                    : undefined
                }
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
