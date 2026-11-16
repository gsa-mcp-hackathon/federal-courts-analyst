// The provenance-first pieces: every number carries where it came from.
import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Popover, Tooltip } from "radix-ui";
import type { Decline, Provenance, ReconciliationBadge as Badge, Warning } from "@/api/types";
import { editionLabel, fmtCount, fmtSigned, fmtValue } from "@/lib/format";
import { Icon, type IconName } from "./Icon";

export function citationText(p: Provenance): string {
  const parts = [
    p.series ?? p.source,
    p.edition ? editionLabel(p.edition) : null,
    p.table_code ? `Table ${p.table_code}` : null,
    p.period ? `FY${p.period.fiscal_year} (12 months ending ${p.period.period_end})` : null,
    p.cell_ref ? `cell ${p.cell_ref}` : null,
  ].filter(Boolean);
  return parts.join(", ") + (p.url ? `. ${p.url}` : ".");
}

const SOURCE_LABEL: Record<string, string> = {
  official_table: "Official table",
  idb_derived: "Computed from FJC IDB records",
  derived: "Derived from official figures",
};

/** Pill beside a number ("JFF 2023 · Table 6.2"); focus or click opens the full card. */
export function ProvenanceBadge({ p }: { p: Provenance }) {
  const [copied, setCopied] = useState(false);
  const label =
    p.source === "official_table" && p.edition
      ? `${editionLabel(p.edition)}${p.table_code ? ` · Table ${p.table_code}` : ""}`
      : p.source === "idb_derived"
        ? "FJC IDB"
        : (SOURCE_LABEL[p.source] ?? p.source);
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="num inline-flex items-center gap-1 rounded-full border border-rule bg-card px-2 py-0.5 align-middle font-mono text-[0.72rem] leading-5 text-ink-2 hover:border-accent hover:text-accent"
          aria-label={`Source: ${label}. Show details`}
        >
          {label}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={6}
          className="z-50 w-80 rounded-lg border border-rule bg-card p-4 text-sm text-ink shadow-lg"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">
            {SOURCE_LABEL[p.source] ?? p.source}
          </p>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {p.series && <Row k="Series">{p.series}</Row>}
            {p.edition && <Row k="Edition">{p.edition}</Row>}
            {p.table_code && <Row k="Table">{p.table_code}</Row>}
            {p.period && (
              <Row k="Period">
                FY{p.period.fiscal_year}, ending {p.period.period_end}
                {p.period.period_type === "statistical_year" ? " (statistical year)" : ""}
              </Row>
            )}
            {p.cell_ref && (
              <Row k="Cell">
                <span className="font-mono text-xs">{p.cell_ref}</span>
              </Row>
            )}
            {p.dataset_release && <Row k="Release">{p.dataset_release}</Row>}
          </dl>
          <p className="mt-2 text-ink-2">{p.definition}</p>
          {p.note && <p className="mt-1 text-muted">{p.note}</p>}
          <div className="mt-3 flex items-center gap-3">
            {p.url && (
              <a
                href={p.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-accent underline underline-offset-2"
              >
                Source file <Icon name="external" className="size-3.5" />
              </a>
            )}
            <button
              type="button"
              className="inline-flex items-center gap-1 text-ink-2 hover:text-accent"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(citationText(p));
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                } catch {
                  setCopied(false);
                }
              }}
            >
              <Icon name="copy" className="size-3.5" />
              {copied ? "Copied" : "Copy citation"}
            </button>
          </div>
          <Popover.Arrow className="fill-card" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{k}</dt>
      <dd className="num">{children}</dd>
    </>
  );
}

/** Amber chip for a revised figure; links to its Edition Tracker page. */
export function RevisionChip({
  status,
  firstValue,
  firstEdition,
  to,
}: {
  status: string | null | undefined;
  firstValue: number | null | undefined;
  firstEdition: string | null | undefined;
  to?: { measure: string; court: string; fy: number };
}) {
  if (status !== "revised" || firstValue === null || firstValue === undefined || !firstEdition)
    return null;
  const text = `Revised · first published as ${fmtValue(firstValue)} (${editionLabel(firstEdition)})`;
  const cls =
    "num inline-flex items-center gap-1 rounded-full border border-revision-rule bg-revision-bg px-2 py-0.5 text-[0.75rem] font-medium text-revision";
  if (!to)
    return (
      <span className={cls}>
        <Icon name="revised" className="size-3.5" />
        {text}
      </span>
    );
  return (
    <Link
      to="/editions/$measure/$court/$fy"
      params={{ measure: to.measure, court: to.court, fy: String(to.fy) }}
      className={`${cls} hover:underline`}
    >
      <Icon name="revised" className="size-3.5" />
      {text}
    </Link>
  );
}

/** For `status: "declined"`: the reason, the policy and the alternative. */
export function DeclineCard({ d, onAsk }: { d: Decline; onAsk?: (q: string) => void }) {
  return (
    <section
      aria-label="Declined"
      className="rounded-lg border border-rule border-l-4 border-l-ink-2 bg-card p-4"
    >
      <p className="flex items-center gap-2 font-semibold text-ink">
        <Icon name="block" />
        Not something this service answers
      </p>
      <p className="mt-2 text-ink-2">{d.message}</p>
      <p className="mt-2 text-sm text-muted">
        <span className="font-medium">Policy:</span> {d.policy}
      </p>
      {d.alternative && (
        <div className="mt-3">
          {onAsk ? (
            <button
              type="button"
              onClick={() => onAsk(d.alternative!)}
              className="rounded-full border border-accent px-3 py-1 text-sm text-accent hover:bg-accent hover:text-accent-ink"
            >
              Ask instead: {d.alternative}
            </button>
          ) : (
            <p className="text-sm">
              <span className="font-medium">Instead:</span> {d.alternative}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** A count the server withheld (n < 10). Never rendered as 0. */
export function SuppressedCell({
  n,
  suppressed,
}: {
  n: number | null | undefined;
  suppressed?: boolean;
}) {
  if (!suppressed && n !== null && n !== undefined)
    return <span className="num">{fmtCount(n)}</span>;
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span
            tabIndex={0}
            className="cursor-help italic text-muted underline decoration-dotted underline-offset-2"
          >
            fewer than 10
          </span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            sideOffset={4}
            className="z-50 max-w-64 rounded bg-ink px-3 py-2 text-xs text-paper shadow"
          >
            Counts of 1–9 are withheld, and so is the next smallest where needed, so small groups of
            cases can't be identified or recovered by subtraction.
            <Tooltip.Arrow className="fill-ink" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

const BADGE: Record<string, { icon: IconName; label: string; cls: string }> = {
  matched: { icon: "check", label: "Matched", cls: "text-good border-good/50" },
  explained_variance: {
    icon: "info",
    label: "Explained variance",
    cls: "text-warning border-warning/50",
  },
  unexplained: { icon: "caution", label: "Unexplained", cls: "text-critical border-critical/50" },
};

export function ReconciliationBadge({ b }: { b: Badge }) {
  const s = BADGE[b.status] ?? {
    icon: "info" as const,
    label: b.status,
    cls: "text-muted border-rule",
  };
  return (
    <span
      title={b.explanation ?? undefined}
      className={`num inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${s.cls}`}
    >
      <Icon name={s.icon} className="size-3.5" />
      {s.label}
      {b.variance !== null && b.variance !== undefined && (
        <span className="text-ink-2">
          {" "}
          ({fmtSigned(b.variance)}
          {b.variance_pct !== null && b.variance_pct !== undefined
            ? `, ${fmtSigned(b.variance_pct)}%`
            : ""}
          )
        </span>
      )}
    </span>
  );
}

const CALLOUT: Record<string, { icon: IconName; cls: string; title: string }> = {
  info: { icon: "info", cls: "border-l-info", title: "Note" },
  caution: { icon: "caution", cls: "border-l-warning", title: "Caution" },
  block: { icon: "block", cls: "border-l-critical", title: "Withheld" },
};

const CODE_TITLE: Record<string, string> = {
  small_cell: "Few cases",
  suppressed: "Small groups withheld",
  data_break: "Data break",
  revised_figure: "Revised figure",
  period_mismatch: "Different period",
  inferred_not_official: "Our inference, not official",
  inexact_match: "Match may be inexact",
  out_of_scope: "Outside what the data covers",
  mixed_editions: "Editions not mixed",
  partial_year: "Partial year",
  truncated: "Truncated",
  no_recommendation: "No recommendation",
  sandbox: "Request desk sandbox",
  office_response: "Statistics office response (simulated)",
  advocacy: "Neutral facts only",
  judge_level: "No judge-level data",
  pii: "No party names",
};

/** Guardrail warnings in one calm, consistent style. */
export function WarningCallout({
  w,
}: {
  w: { code: Warning["code"] | (string & {}); message: string; severity?: Warning["severity"] };
}) {
  const sev = CALLOUT[w.severity ?? "caution"] ?? CALLOUT.caution!;
  return (
    <div
      className={`rounded-md border border-rule border-l-4 bg-card px-3 py-2 text-sm ${sev.cls}`}
    >
      <p className="flex items-center gap-1.5 font-medium text-ink">
        <Icon name={sev.icon} className="size-4 shrink-0" />
        {CODE_TITLE[w.code] ?? sev.title}
      </p>
      <p className="mt-0.5 text-ink-2">{w.message}</p>
    </div>
  );
}
