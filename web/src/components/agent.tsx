// The Ask experience's pieces: "show your work", clarification chips and
// docket cards. Everything the agent streams is rendered as text; nothing is
// ever injected as HTML.
import { useState } from "react";
import { Collapsible } from "radix-ui";
import type { ClarifyEvent, DocketCard as Card } from "@/api/types.gen";
import type { ToolStep } from "@/api/turn";
import { fmtMs } from "@/lib/format";
import { Icon } from "./Icon";

/** Docket fields arrive HTML-escaped from the server; decode for display
 * (React escapes again when rendering, so this can't create markup). */
export function unescapeHtml(s: string | null | undefined): string {
  if (!s) return "";
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  return /^https:\/\/(www\.)?courtlistener\.com\//.test(url) ? url : null;
}

const ORIGIN_LABEL: Record<Card["origin"], string> = {
  idb_sample: "From the IDB · search on CourtListener",
  courtlistener: "CourtListener (external)",
  courtlistener_fixture: "Example data (not a real case)",
};

export function DocketCard({ card }: { card: Card }) {
  const href = safeHref(card.url);
  return (
    <article className="rounded-lg border border-rule bg-card p-3 text-sm">
      <p className="text-[0.7rem] font-semibold uppercase tracking-wide text-muted">
        {ORIGIN_LABEL[card.origin]}
      </p>
      <p className="mt-1 font-mono text-ink">
        {unescapeHtml(card.docket_number) || "No docket number"}
      </p>
      <p className="text-ink-2">
        {unescapeHtml(card.court)}
        {card.filing_date && <> · filed {card.filing_date}</>}
      </p>
      {card.nature_of_suit && <p className="text-ink-2">{unescapeHtml(card.nature_of_suit)}</p>}
      {card.cause && <p className="text-muted">{unescapeHtml(card.cause)}</p>}
      <p className="mt-1 text-xs text-muted">{unescapeHtml(card.note)}</p>
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="mt-1 inline-flex items-center gap-1 text-accent underline underline-offset-2"
        >
          Open on CourtListener <Icon name="external" className="size-3.5" />
        </a>
      )}
    </article>
  );
}

export function ClarifyChips({
  ev,
  onChoose,
  busy,
}: {
  ev: ClarifyEvent;
  onChoose: (choice: string | null) => void;
  busy?: boolean;
}) {
  const c = ev.clarification;
  return (
    <section
      aria-label="The server needs a choice"
      className="rounded-lg border border-accent/50 bg-card p-4"
    >
      <p className="font-medium text-ink">{c.question}</p>
      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Choices">
        {c.choices.map((ch) => (
          <button
            key={ch.value}
            type="button"
            disabled={busy}
            title={ch.description ?? undefined}
            onClick={() => onChoose(ch.value)}
            className={`rounded-full border px-3 py-1 text-sm disabled:opacity-50 ${
              ch.value === c.default
                ? "border-accent bg-accent text-accent-ink"
                : "border-rule text-ink hover:border-accent"
            }`}
          >
            {ch.label}
          </button>
        ))}
        <button
          type="button"
          disabled={busy}
          onClick={() => onChoose(null)}
          className="rounded-full px-3 py-1 text-sm text-muted underline underline-offset-2"
        >
          Skip
        </button>
      </div>
    </section>
  );
}

function summarize(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : String(v)}`)
    .join(" · ");
}

export function ToolTrace({ steps }: { steps: ToolStep[] }) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;
  return (
    <Collapsible.Root
      open={open}
      onOpenChange={setOpen}
      className="rounded-lg border border-rule bg-card"
    >
      <Collapsible.Trigger className="flex w-full items-center justify-between px-4 py-2 text-left text-sm font-medium text-ink">
        <span className="inline-flex items-center gap-2">
          <Icon name="tool" />
          Show your work: {steps.length} tool call{steps.length === 1 ? "" : "s"}
        </span>
        <Icon name="chevron" className={`size-4 transition-transform ${open ? "rotate-90" : ""}`} />
      </Collapsible.Trigger>
      <Collapsible.Content>
        <ol className="space-y-2 border-t border-rule px-4 py-3">
          {steps.map((s, i) => (
            <li key={s.call.call_id} className="text-sm">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="num text-muted">{i + 1}.</span>
                <span className="font-mono text-ink">{s.call.tool}</span>
                {s.call.server !== "courts-analyst" && (
                  <span className="rounded bg-paper-2 px-1.5 text-xs text-muted">
                    {s.call.server}
                  </span>
                )}
                {s.result ? (
                  <span
                    className={`text-xs ${
                      s.result.status === "ok"
                        ? "text-good"
                        : s.result.status === "error"
                          ? "text-critical"
                          : "text-warning"
                    }`}
                  >
                    {s.result.status} · {fmtMs(s.result.latency_ms)}
                  </span>
                ) : (
                  <span className="text-xs text-muted">running…</span>
                )}
              </p>
              <p className="ml-6 break-words font-mono text-xs text-ink-2">
                {summarize(s.call.arguments)}
              </p>
              {s.result?.error && <p className="ml-6 text-xs text-critical">{s.result.error}</p>}
              {s.result?.result && (
                <details className="ml-6">
                  <summary className="cursor-pointer text-xs text-accent">Result</summary>
                  <pre className="mt-1 max-h-64 overflow-auto rounded bg-paper-2 p-2 text-[0.7rem] leading-snug text-ink-2">
                    {JSON.stringify(s.result.result, null, 2)}
                  </pre>
                </details>
              )}
            </li>
          ))}
        </ol>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

/** The active cohort from a find_cases result, with its filters. */
export function CohortPill({ handle, filters }: { handle: string; filters: string[] }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-rule bg-card px-3 py-1 text-xs">
      <span className="font-mono text-ink">{handle}</span>
      <span className="text-muted">{filters.join(" · ")}</span>
    </span>
  );
}
