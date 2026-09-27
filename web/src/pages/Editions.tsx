import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api, ApiError } from "@/api/client";
import { DataTable, VintageChart } from "@/components/charts";
import { PageHeader } from "@/components/Layout";
import { ProvenanceBadge, RevisionChip, WarningCallout } from "@/components/Provenance";
import { ChartSkeleton, EmptyState, ErrorState, Loading } from "@/components/States";
import { courtFromSlug, courtNames, courtSlug, useCourts } from "@/lib/courts";
import { editionLabel, fmtSigned, fmtValue } from "@/lib/format";
import { bySlug, MEASURES } from "@/lib/measures";
import { editionHistory, vintageLines } from "@/lib/vintage";

const FYS = Array.from({ length: 10 }, (_, i) => 2016 + i);

export function EditionsPage({
  measureSlug,
  courtSlugParam,
  fy,
}: {
  measureSlug: string;
  courtSlugParam: string;
  fy: number;
}) {
  const navigate = useNavigate();
  const measure = bySlug(measureSlug);
  const court = courtFromSlug(courtSlugParam);
  const courts = useCourts();
  const names = courtNames(courts.data?.courts);
  const courtName = court === "US" ? "All district courts" : (names.get(court) ?? court);

  const go = (p: { measure?: string; court?: string; fy?: number }) =>
    navigate({
      to: "/editions/$measure/$court/$fy",
      params: {
        measure: p.measure ?? measureSlug,
        court: p.court ?? courtSlugParam,
        fy: String(p.fy ?? fy),
      },
    });

  const figure = useQuery({
    queryKey: ["figure", measure?.id, court, fy],
    queryFn: () => api.figure({ measure: measure!.id, court, fiscal_year: fy }),
    enabled: !!measure,
  });
  const vintages = useQuery({
    queryKey: ["vintages", measure?.id, court],
    queryFn: () => api.vintages(measure!.id, court),
    enabled: !!measure,
  });
  const first = useQuery({
    queryKey: ["series-first", measure?.id, court],
    queryFn: () => api.series(measure!.id, court, 2016, 2025, false, "first_published"),
    enabled: !!measure,
    retry: false,
  });
  const revisions = useQuery({
    queryKey: ["revisions", measure?.id, court],
    queryFn: () => api.revisions({ measure: measure!.id, court }),
    enabled: !!measure,
  });

  // One line per edition that printed the selected year (the editions the
  // figure's own history lists), so the chart answers "what did each
  // edition say?" without ten overlapping lines.
  const printed = useMemo(
    () => new Set((figure.data?.data?.editions ?? []).map((e) => e.edition)),
    [figure.data],
  );
  const lines = useMemo(
    () =>
      vintageLines(
        first.data?.data,
        (vintages.data?.data?.editions ?? []).filter(
          (e) => !printed.size || printed.has(e.edition),
        ),
        2015,
      ),
    [first.data, vintages.data, printed],
  );

  if (!measure)
    return (
      <EmptyState title="Unknown measure">
        Pick one of: {MEASURES.map((m) => m.label).join(", ")}.
      </EmptyState>
    );

  const f = figure.data?.data;
  const refused = first.error instanceof ApiError ? first.error : null;
  return (
    <div>
      <PageHeader
        title="Edition Tracker"
        lede="The same statistic can differ between editions of the same table. See every edition side by side, never spliced."
      />
      <form
        className="mb-6 flex flex-wrap items-end gap-3"
        aria-label="Choose a figure"
        onSubmit={(e) => e.preventDefault()}
      >
        <Select label="Measure" value={measureSlug} onChange={(v) => go({ measure: v })}>
          {MEASURES.map((m) => (
            <option key={m.slug} value={m.slug}>
              {m.label}
            </option>
          ))}
        </Select>
        <Select
          label="Court"
          value={courtSlugParam.toLowerCase()}
          onChange={(v) => go({ court: v })}
        >
          <option value="national">All district courts (national)</option>
          {(courts.data?.courts ?? [])
            .filter((c) => c.level === "district")
            .map((c) => (
              <option key={c.code} value={courtSlug(c.code)}>
                {c.citation ?? c.name}
              </option>
            ))}
        </Select>
        <Select label="Fiscal year" value={String(fy)} onChange={(v) => go({ fy: Number(v) })}>
          {FYS.map((y) => (
            <option key={y} value={y}>
              FY{y}
            </option>
          ))}
        </Select>
      </form>

      <section aria-labelledby="fig-h" className="mb-8 rounded-lg border border-rule bg-card p-5">
        <h2 id="fig-h" className="text-sm font-semibold uppercase tracking-wide text-muted">
          {measure.label} · {courtName} · FY{fy}
        </h2>
        {figure.isPending ? (
          <div
            className="mt-2 h-60 animate-pulse rounded bg-paper-2"
            role="status"
            aria-label="Loading figure"
          />
        ) : figure.error ? (
          <ErrorState error={figure.error} retry={() => void figure.refetch()} />
        ) : f ? (
          <div className="mt-2">
            <p className="flex flex-wrap items-baseline gap-3">
              <span className="num font-serif text-5xl font-semibold text-ink">
                {fmtValue(f.value)}
              </span>
              <span className="text-ink-2">{f.unit}</span>
              {figure.data?.provenance?.[0] && <ProvenanceBadge p={figure.data.provenance[0]} />}
              <RevisionChip
                status={f.revision_status}
                firstValue={f.first_published.value}
                firstEdition={f.first_published.edition}
              />
            </p>
            <p className="mt-2 break-words font-mono text-sm text-ink-2 sm:whitespace-nowrap">
              {f.citation}
            </p>
            {(f.revision_notes ?? []).length > 0 && (
              <div className="mt-4 space-y-2">
                {(f.revision_notes ?? []).map((n) => (
                  <WarningCallout
                    key={n.text}
                    w={{
                      code: n.basis === "inferred" ? "inferred_not_official" : "revised_figure",
                      message: n.text,
                      severity: n.basis === "inferred" ? "caution" : "info",
                    }}
                  />
                ))}
              </div>
            )}
          </div>
        ) : null}
      </section>

      <section aria-label="Every edition" className="mb-8">
        {vintages.isPending || figure.isPending ? (
          <ChartSkeleton />
        ) : vintages.error ? (
          <ErrorState error={vintages.error} />
        ) : lines.length ? (
          <>
            {refused && (
              <div className="mb-3">
                <WarningCallout
                  w={{
                    code: "mixed_editions",
                    severity: "info",
                    message: `No "as first published" line: ${refused.body.message ?? "the server won't join these editions."}`,
                  }}
                />
              </div>
            )}
            <VintageChart
              lines={lines}
              unit={measure.unit}
              title={`${measure.label}, ${courtName}: every edition`}
              source="Each line is one edition's own table, as printed."
            />
          </>
        ) : (
          <EmptyState title="Only one edition prints this figure">
            There is nothing to compare: see the value above.
          </EmptyState>
        )}
      </section>

      {f && (
        <section aria-labelledby="hist-h" className="mb-8">
          <h2 id="hist-h" className="mb-2 font-serif text-xl font-semibold">
            FY{fy} in each edition that printed it
          </h2>
          <DataTable
            columns={["Edition", "Table", "Value", "Change"]}
            rows={editionHistory(f.editions).map((e, i, all) => [
              editionLabel(e.edition),
              e.table,
              <span key="v" className={e.changed ? "font-semibold text-revision" : undefined}>
                {fmtValue(e.value)}
              </span>,
              e.changed ? fmtSigned(e.value - all[i - 1]!.value) : "",
            ])}
          />
        </section>
      )}

      <section aria-labelledby="rev-h">
        <h2 id="rev-h" className="mb-2 font-serif text-xl font-semibold">
          Every revised year for this measure and court
        </h2>
        {revisions.isPending ? (
          <Loading lines={2} />
        ) : revisions.data?.revisions.length ? (
          <DataTable
            columns={["Fiscal year", "First published", "Latest", "Change", ""]}
            rows={revisions.data.revisions.map((r) => [
              `FY${r.fiscal_year}`,
              `${fmtValue(r.first_value)} (${r.first_edition})`,
              `${fmtValue(r.latest_value)} (${r.latest_edition})`,
              fmtSigned(r.latest_value - r.first_value),
              r.fiscal_year >= 2016 ? (
                <Link
                  key="l"
                  to="/editions/$measure/$court/$fy"
                  params={{
                    measure: measureSlug,
                    court: courtSlugParam,
                    fy: String(r.fiscal_year),
                  }}
                  className="text-accent underline underline-offset-2"
                >
                  Open
                </Link>
              ) : (
                ""
              ),
            ])}
          />
        ) : (
          <EmptyState title="No revisions">Every edition printed the same values.</EmptyState>
        )}
      </section>
    </div>
  );
}

export function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-ink-2">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-rule bg-card px-2 py-1.5 text-ink"
      >
        {children}
      </select>
    </label>
  );
}
