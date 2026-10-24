// Request desk UI (ADR 0013): the three options under an answer, the
// verification gate's verdict, the library match, and the pieces of the
// My requests inbox. A question writes nothing; only these buttons do.
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { citationsFrom, desk, deskAccount, OPTION_LABELS, type DeskOption } from "@/api/desk";
import type { TurnState } from "@/api/turn";
import type {
  DeskOutcome,
  GateReport,
  InquiryView,
  LibraryEntryView,
  RequestView,
  UpdateView,
} from "@/api/types.gen";
import { editionLabel, fmtValue } from "@/lib/format";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";

export const SANDBOX_NOTE =
  "Sandbox: requests are kept here, nothing is sent to the AO or the FJC, and the statistics office is played by a teammate.";

const STATUS_LABELS: Record<string, string> = {
  received: "Received",
  verified: "Verified answer saved",
  watching: "Watching for changes",
  waiting_for_office: "Waiting for statistics office",
  office_responded: "Statistics office responded",
  published: "Published to the library",
};

export function statusLabel(s: string): string {
  return STATUS_LABELS[s] ?? s.replace(/_/g, " ");
}

// ── account ──────────────────────────────────────────────────────────────────

export function AccountPicker({ onChange }: { onChange?: (id: string | null) => void }) {
  const accounts = useQuery({ queryKey: ["desk", "accounts"], queryFn: desk.accounts });
  const [current, setCurrent] = useState(deskAccount.get());
  return (
    <label className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
      <span>Signed in as (demo account)</span>
      <select
        id="desk-account"
        value={current ?? ""}
        onChange={(e) => {
          const id = e.target.value || null;
          deskAccount.set(id);
          setCurrent(id);
          onChange?.(id);
        }}
        className="rounded-md border border-rule bg-card px-2 py-1 text-ink"
      >
        <option value="">Choose…</option>
        {accounts.data?.accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} ({a.role_label})
          </option>
        ))}
      </select>
    </label>
  );
}

// ── the three options under an answer ────────────────────────────────────────

const MAX_ELIGIBILITY_CHECKS = 5;

/** The figures an answer cites, once each. The server decides which were
 * revised without explanation: a citation's own `revised` flag can miss one
 * (figures cited from explain_change, issue #37). */
function citedFigures(turn: TurnState) {
  const seen = new Map<string, { measure: string; court: string; fiscal_year: number }>();
  for (const { ref } of turn.citations) {
    const key = `${ref.measure}|${ref.court}|${ref.fiscal_year}`;
    if (!seen.has(key)) {
      seen.set(key, { measure: ref.measure, court: ref.court, fiscal_year: ref.fiscal_year });
    }
  }
  return [...seen.values()].slice(0, MAX_ELIGIBILITY_CHECKS);
}

export function DeskOptions({ turn }: { turn: TurnState }) {
  const ended = turn.end?.stop_reason === "end_turn";
  const checks = useQueries({
    queries: citedFigures(turn).map((f) => ({
      queryKey: ["desk", "eligibility", f],
      queryFn: () => desk.eligibility(f),
      enabled: ended,
      staleTime: Infinity,
    })),
  });
  // Of the eligible figures, the one whose revision is largest.
  const eligible = checks
    .map((c) => c.data?.data)
    .filter((e) => e?.eligible)
    .sort(
      (a, b) =>
        Math.abs((b!.to_value ?? 0) - (b!.from_value ?? 0)) -
        Math.abs((a!.to_value ?? 0) - (a!.from_value ?? 0)),
    )[0];
  const target = eligible
    ? { measure: eligible.measure, court: eligible.court, fiscal_year: eligible.fiscal_year }
    : null;
  const [open, setOpen] = useState<DeskOption | null>(null);
  const canAsk = eligible !== undefined;
  if (!ended || !turn.text || turn.citations.length === 0) {
    return null;
  }
  const options: DeskOption[] = [
    ...(canAsk ? (["ask_office"] as const) : []),
    "verified_copy",
    "notify",
  ];
  return (
    <section aria-label="Keep this answer" className="rounded-lg border border-rule bg-card p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Keep this answer</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            aria-pressed={open === o}
            onClick={() => setOpen(open === o ? null : o)}
            className={
              o === "ask_office"
                ? "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink"
                : "rounded-md border border-accent px-3 py-1.5 text-sm font-medium text-accent hover:bg-paper-2"
            }
          >
            {OPTION_LABELS[o]}
          </button>
        ))}
      </div>
      {eligible && !open && (
        <p className="mt-2 text-sm text-ink-2">
          FY{eligible.fiscal_year} changed from{" "}
          <span className="num">{fmtValue(eligible.from_value)}</span> (
          {editionLabel(eligible.from_edition ?? "")}) to{" "}
          <span className="num">{fmtValue(eligible.to_value)}</span> (
          {editionLabel(eligible.to_edition ?? "")}). {eligible.reason}
        </p>
      )}
      {open && (
        <SavePanel
          key={open}
          option={open}
          turn={turn}
          target={open === "ask_office" ? target : null}
          onClose={() => setOpen(null)}
        />
      )}
    </section>
  );
}

function SavePanel({
  option,
  turn,
  target,
  onClose,
}: {
  option: DeskOption;
  turn: TurnState;
  target: { measure: string; court: string; fiscal_year: number } | null;
  onClose: () => void;
}) {
  const [text, setText] = useState(turn.text);
  const [account, setAccount] = useState(deskAccount.get());
  const [key] = useState(() => `${turn.turnId ?? "turn"}-${option}-${Date.now()}`);
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () =>
      desk.submit({
        option,
        question: turn.question,
        answer_text: text,
        citations: citationsFrom(turn.citations.map((c) => c.ref)),
        inquiry: target,
        // The server re-runs these read tools itself; only names and
        // arguments are sent, never values.
        tool_calls: turn.steps
          .filter((st) => st.call.server === "courts-analyst")
          .slice(0, 8)
          .map((st) => ({ tool: st.call.tool, arguments: st.call.arguments })),
        idempotency_key: key,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["desk"] }),
  });
  const out = save.data?.data;
  return (
    <div className="mt-3 space-y-3 border-t border-rule pt-3">
      <p className="text-sm font-medium text-ink">{OPTION_LABELS[option]}</p>
      {!out?.written && (
        <>
          <AccountPicker onChange={setAccount} />
          <label htmlFor="desk-answer" className="block text-sm text-ink-2">
            The answer to save. Every number is checked against the official tables before it's
            saved; you can edit it.
          </label>
          <textarea
            id="desk-answer"
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border border-rule bg-paper p-2 font-mono text-sm text-ink"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!account || !text.trim() || save.isPending}
              onClick={() => save.mutate()}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink disabled:opacity-40"
            >
              {save.isPending ? "Checking…" : "Check and save"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-rule px-3 py-1.5 text-sm text-ink hover:bg-paper-2"
            >
              Cancel
            </button>
            {!account && <span className="text-sm text-muted">Choose a demo account first.</span>}
          </div>
          <p className="text-xs text-muted">{SANDBOX_NOTE}</p>
        </>
      )}
      {save.error && <DeskError error={save.error} />}
      {out && <OutcomeView outcome={out} />}
    </div>
  );
}

export function DeskError({ error }: { error: unknown }) {
  const msg =
    error instanceof ApiError
      ? (error.body.message ?? error.body.error)
      : error instanceof Error
        ? error.message
        : "Something went wrong.";
  return (
    <p role="alert" className="rounded-md border border-critical/40 bg-card p-2 text-sm text-ink-2">
      <span className="font-medium text-critical">Not saved. </span>
      {msg}
    </p>
  );
}

export function OutcomeView({ outcome }: { outcome: DeskOutcome }) {
  if (!outcome.written && outcome.gate && !outcome.gate.passed) {
    return <GateProblems gate={outcome.gate} />;
  }
  return (
    <div role="status" className="rounded-md border border-good/40 bg-card p-3 text-sm">
      <p className="flex items-center gap-1.5 font-medium text-good">
        <Icon name="check" /> {outcome.message}
      </p>
      {outcome.request?.answer && (
        <p className="mt-1 font-mono text-xs text-ink-2">{outcome.request.answer.stamp}</p>
      )}
      {outcome.gate && outcome.gate.computed.length > 0 && (
        <p className="mt-1 text-xs text-muted">
          {outcome.gate.computed.length} computed figure
          {outcome.gate.computed.length === 1 ? "" : "s"} (
          {outcome.gate.computed
            .slice(0, 6)
            .map((c) => c.number)
            .join(", ")}
          ) matched by re-running{" "}
          {[...new Set(outcome.gate.computed.map((c) => c.source))].join(", ")} on the server.
        </p>
      )}
      {outcome.inquiry && <InquiryLine inquiry={outcome.inquiry} />}
      <Link to="/requests" className="mt-2 inline-block text-accent underline">
        Follow it in My requests
      </Link>
    </div>
  );
}

export function GateProblems({ gate }: { gate: GateReport }) {
  return (
    <div role="alert" className="rounded-md border border-critical/40 bg-card p-3 text-sm">
      <p className="flex items-center gap-1.5 font-medium text-critical">
        <Icon name="block" /> Not saved: the answer didn't pass verification
      </p>
      <ul className="mt-2 space-y-2">
        {gate.problems.map((p, i) => (
          <li key={i}>
            {p.number && !p.message.startsWith(p.number) && (
              <span className="num mr-1 rounded bg-paper-2 px-1.5 font-mono font-semibold">
                {p.number}
              </span>
            )}
            <span className="text-ink">{p.message}</span>
            {p.fix && <span className="block text-ink-2">Fix: {p.fix}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function InquiryLine({ inquiry }: { inquiry: InquiryView }) {
  return (
    <p className="mt-1 text-ink-2">
      Inquiry #{inquiry.id}: FY{inquiry.fiscal_year} {inquiry.measure_label.toLowerCase()},{" "}
      {inquiry.court_name}, <span className="num">{fmtValue(inquiry.from_value)}</span> (
      {editionLabel(inquiry.from_edition)}) →{" "}
      <span className="num">{fmtValue(inquiry.to_value)}</span> ({editionLabel(inquiry.to_edition)}
      ). Would go to {inquiry.route_label}. {inquiry.delivery}
      {inquiry.waiting_requests > 1 && ` ${inquiry.waiting_requests} requests are waiting on it.`}
    </p>
  );
}

// ── the library ──────────────────────────────────────────────────────────────

export function LibraryMatch({ question }: { question: string }) {
  const lib = useQuery({
    queryKey: ["desk", "library", question],
    queryFn: () => desk.library({ q: question }),
    enabled: question.length > 0,
    staleTime: 60_000,
  });
  const entry = lib.data?.data?.entries[0];
  if (!entry) return null;
  return <LibraryCard entry={entry} heading="An approved answer to a similar question" />;
}

export function LibraryCard({ entry, heading }: { entry: LibraryEntryView; heading?: string }) {
  return (
    <section
      aria-label="Approved answer"
      className="rounded-lg border border-good/40 bg-card p-3 text-sm"
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-good">
        <Icon name="check" /> {heading ?? "Approved answer"} · request #{entry.request_id}
      </p>
      <p className="mt-1 font-medium text-ink">{entry.question}</p>
      {entry.needs_reverification && (
        <p className="mt-1 rounded border-l-4 border-l-warning bg-paper-2 px-2 py-1 text-ink-2">
          A newer edition revised a figure this answer cites. Check the current figure before
          relying on it.
        </p>
      )}
      <Markdown text={entry.answer.text} className="prose-answer mt-2 text-ink" />
      {entry.inquiry?.response && (
        <p className="mt-2 rounded bg-paper-2 px-2 py-1 text-ink-2">
          <span className="font-medium text-ink">{entry.inquiry.response.label}:</span>{" "}
          {entry.inquiry.response.text}
        </p>
      )}
      <p className="mt-2 font-mono text-xs text-muted">{entry.answer.stamp}</p>
    </section>
  );
}

// ── inbox pieces ─────────────────────────────────────────────────────────────

const STEPS: Record<string, string[]> = {
  ask_office: ["received", "verified", "waiting_for_office", "office_responded", "published"],
  verified_copy: ["received", "verified", "published"],
  notify: ["received", "watching", "published"],
};

export function StatusTimeline({ request }: { request: RequestView }) {
  const steps = STEPS[request.option] ?? ["received", request.status];
  const at = steps.indexOf(request.status);
  return (
    <ol className="grid gap-2 sm:grid-flow-col sm:auto-cols-fr" aria-label="Progress">
      {steps.map((s, i) => {
        const done = i < at || (i === at && request.status === "published");
        const now = i === at && !done;
        return (
          <li
            key={s}
            aria-current={now ? "step" : undefined}
            className={`border-t-[3px] pt-1.5 text-xs ${
              done
                ? "border-good text-ink"
                : now
                  ? "border-warning text-warning"
                  : "border-rule text-muted"
            }`}
          >
            <span className="font-semibold">{statusLabel(s)}</span>
          </li>
        );
      })}
    </ol>
  );
}

const KIND_DOT: Record<string, string> = {
  office_responded: "bg-good",
  published: "bg-good",
  verified: "bg-good",
  figure_revised: "bg-critical",
  inquiry_filed: "bg-warning",
  inquiry_joined: "bg-warning",
};

export function UpdatesList({ updates }: { updates: UpdateView[] }) {
  return (
    <ul className="space-y-2 text-sm" aria-label="Updates">
      {updates.map((u) => (
        <li key={u.id} className="grid grid-cols-[0.75rem_minmax(0,1fr)] gap-2">
          <span
            aria-hidden
            className={`mt-1.5 size-2.5 rounded-full ${KIND_DOT[u.kind] ?? "bg-rule"}`}
          />
          <div className={u.read ? "text-ink-2" : "text-ink"}>
            {!u.read && <span className="mr-1 text-xs font-semibold text-accent">New</span>}
            {u.text}
            <span className="ml-1 text-xs text-muted">
              {new Date(u.created_at).toLocaleString()}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function RequestHeader({ request }: { request: RequestView }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <span className="font-mono text-sm text-muted">#{request.id}</span>{" "}
        <span className="font-medium text-ink">{request.question}</span>
        <p className="text-xs text-muted">
          {request.option_label} · {request.asker_name}
        </p>
      </div>
      <span className="rounded-full border border-rule bg-paper-2 px-2 py-0.5 text-xs font-medium text-ink-2">
        {statusLabel(request.status)}
      </span>
    </div>
  );
}

export function RequestAnswer({ request }: { request: RequestView }) {
  if (!request.answer) return null;
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-ink-2">Verified answer</summary>
      <Markdown text={request.answer.text} className="prose-answer mt-2 text-ink" />
      <p className="mt-1 font-mono text-xs text-muted">{request.answer.stamp}</p>
      {request.inquiry?.response && (
        <p className="mt-2 rounded bg-paper-2 px-2 py-1 text-ink-2">
          <span className="font-medium text-ink">{request.inquiry.response.label}:</span>{" "}
          {request.inquiry.response.text}
        </p>
      )}
    </details>
  );
}
