import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import * as Plot from "@observablehq/plot";
import { api } from "@/api/client";
import type { Envelope, OfficialSeries } from "@/api/types";
import { DataTable, PlotFigure } from "@/components/charts";
import { PageHeader } from "@/components/Layout";
import {
  ProvenanceBadge,
  ReconciliationBadge,
  SuppressedCell,
  WarningCallout,
} from "@/components/Provenance";
import { ChartSkeleton, EmptyState, ErrorState, Loading } from "@/components/States";
import { courtFromSlug, courtNames, courtSlug, useCourts } from "@/lib/courts";
import { fmtPct, fmtSigned, fmtValue } from "@/lib/format";
import { byId, FY_MAX, FY_MIN } from "@/lib/measures";
import { Select } from "./Editions";

const TRENDS = [
  "weighted_total_filings_per_judgeship",
  "civil_cases_filed",
  "civil_cases_pending",
  "civil_median_months_to_disposition",
];

export function CourtPage({ slug, fy }: { slug: string; fy?: number }) {
  const court = courtFromSlug(slug);
  const courts = useCourts();
  const names = courtNames(courts.data?.courts);
  const navigate = useNavigate();
  const known = courts.data ? courts.data.courts.some((c) => c.code === court) : true;
  const year = fy ?? FY_MAX;
  const name = court === "US" ? "All district courts" : (names.get(court) ?? court);
  const full = courts.data?.courts.find((c) => c.code === court);

  const profile = useQuery({
    queryKey: ["profile", court, year],
    queryFn: () => api.profile(court, year),
    enabled: known,
  });
  const trends = useQueries({
    queries: TRENDS.map((m) => ({
      queryKey: ["series", m, court],
      queryFn: () => api.series(m, court, FY_MIN, FY_MAX),
      enabled: known,
      retry: false,
    })),
  });
  const mix = useQuery({
    queryKey: ["mix", court, year],
    queryFn: () => api.caseMix(court, year),
    enabled: known,
    retry: false,
  });
  const recon = useQuery({
    queryKey: ["recon", court, year],
    queryFn: () => api.reconcile(court, year),
    enabled: known,
    retry: false,
  });
  const revisions = useQuery({
    queryKey: ["revisions", "court", court],
    queryFn: () => api.revisions({ court }),
    enabled: known,
  });

  if (!known)
    return (
      <EmptyState title={`No court "${slug}"`}>
        <Link to="/explore" className="text-accent underline">
          Pick a district on the map
        </Link>
        .
      </EmptyState>
    );

  const ctx = profile.data?.data;
  return (
    <div>
      <PageHeader
        title={name}
        lede={
          full?.level === "district"
            ? `${full.name} · ${full.circuit?.replace("CIR-", "Circuit ") ?? ""}`
            : "Every district court combined"
        }
      >
        <Select
          label="Fiscal year"
          value={String(year)}
          onChange={(v) =>
            navigate({ to: "/courts/$court", params: { court: slug }, search: { fy: Number(v) } })
          }
        >
          {Array.from({ length: FY_MAX - FY_MIN + 1 }, (_, i) => FY_MAX - i).map((y) => (
            <option key={y} value={y}>
              FY{y}
            </option>
          ))}
        </Select>
      </PageHeader>

      <section aria-labelledby="ctx-h" className="mb-8 rounded-lg border border-rule bg-card p-5">
        <h2 id="ctx-h" className="text-sm font-semibold uppercase tracking-wide text-muted">
          Judgeship context, FY{year}
        </h2>
        {profile.isPending ? (
          <Loading lines={3} />
        ) : profile.error ? (
          <ErrorState error={profile.error} retry={() => void profile.refetch()} />
        ) : ctx ? (
          <div className="mt-3 grid gap-6 md:grid-cols-3">
            <Stat
              label="Weighted filings per judgeship"
              value={fmtValue(ctx.weighted_total.value)}
              badge={
                profile.data?.provenance?.[0] && <ProvenanceBadge p={profile.data.provenance[0]} />
              }
              note={`National: ${fmtValue(ctx.national_weighted_total?.value)}`}
            />
            <Stat
              label="Authorized judgeships"
              value={fmtValue(ctx.authorized_judgeships?.value)}
              note={
                ctx.recommendation
                  ? `Judicial Conference ${ctx.recommendation.date.slice(0, 4)}: ${fmtValue(ctx.recommendation.recommended_additional)} more recommended`
                  : "No Conference recommendation for this court"
              }
            />
            <div className="space-y-2">
              {ctx.thresholds.map((t) => (
                <p key={t.id} className="text-sm">
                  <span className={`num font-semibold ${t.above ? "text-ink" : "text-muted"}`}>
                    {t.above ? "Above" : "Below"} {fmtValue(t.value)}
                  </span>{" "}
                  <span className="text-ink-2">by {fmtValue(Math.abs(t.margin ?? 0))}</span>
                  <br />
                  <span className="text-muted">{t.label}</span>
                </p>
              ))}
            </div>
            <p className="text-ink-2 md:col-span-3">{ctx.statement}</p>
            {profile.data?.warnings?.map((w) => (
              <div key={w.message} className="md:col-span-3">
                <WarningCallout w={w} />
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section aria-labelledby="trend-h" className="mb-8">
        <h2 id="trend-h" className="mb-3 font-serif text-2xl font-semibold">
          Trends, FY{FY_MIN}–FY{FY_MAX}
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {TRENDS.map((m, i) => (
            <Trend key={m} measure={m} q={trends[i]!} />
          ))}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="mix-h">
          <h2 id="mix-h" className="mb-3 font-serif text-2xl font-semibold">
            Civil case mix, FY{year}
          </h2>
          {mix.isPending ? (
            <Loading lines={4} />
          ) : mix.error ? (
            <ErrorState error={mix.error} />
          ) : (
            <CaseMix env={mix.data} />
          )}
        </section>
        <section aria-labelledby="rec-h">
          <h2 id="rec-h" className="mb-3 font-serif text-2xl font-semibold">
            Official count vs IDB records
          </h2>
          {recon.isPending ? (
            <Loading lines={2} />
          ) : recon.error ? (
            <ErrorState error={recon.error} />
          ) : recon.data?.data ? (
            <div className="rounded-lg border border-rule bg-card p-4 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">Civil cases filed, FY{year}</span>
                <ReconciliationBadge b={recon.data.data.badge} />
              </p>
              <p className="num mt-2 text-ink-2">
                Official {fmtValue(recon.data.data.official.value)} (
                {recon.data.data.official.edition}) · rebuilt from IDB records{" "}
                {fmtValue(recon.data.data.idb_value)} · difference{" "}
                {fmtSigned(recon.data.data.variance)}
              </p>
              {recon.data.data.explanations?.map((e) => (
                <p key={e.detail} className="mt-1 text-muted">
                  {e.detail}
                </p>
              ))}
              <p className="mt-2 text-xs text-muted">{recon.data.data.rule}</p>
            </div>
          ) : null}
          <h2 className="mb-3 mt-8 font-serif text-2xl font-semibold">Revised figures</h2>
          {revisions.data?.revisions.length ? (
            <DataTable
              columns={["Measure", "FY", "First", "Latest"]}
              rows={revisions.data.revisions.slice(0, 12).map((r) => {
                const m = byId(r.measure);
                return [
                  m ? (
                    <Link
                      key="m"
                      to="/editions/$measure/$court/$fy"
                      params={{
                        measure: m.slug,
                        court: courtSlug(court),
                        fy: String(r.fiscal_year),
                      }}
                      className="text-accent underline underline-offset-2"
                    >
                      {m.short}
                    </Link>
                  ) : (
                    r.measure.replace(/_/g, " ")
                  ),
                  r.fiscal_year,
                  `${fmtValue(r.first_value)} (${r.first_edition})`,
                  `${fmtValue(r.latest_value)} (${r.latest_edition})`,
                ];
              })}
            />
          ) : (
            <EmptyState title="No revised figures for this court" />
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  note,
  badge,
}: {
  label: string;
  value: string;
  note?: string;
  badge?: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-sm text-muted">{label}</p>
      <p className="num font-serif text-4xl font-semibold text-ink">{value}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-2">
        {badge}
        {note && <span>{note}</span>}
      </div>
    </div>
  );
}

function Trend({
  measure,
  q,
}: {
  measure: string;
  q: { data?: Envelope<OfficialSeries>; isPending: boolean; error: unknown };
}) {
  const m = byId(measure);
  const s = q.data?.data;
  const build = useMemo(
    () =>
      (_w: number, t: Record<string, string>): Plot.PlotOptions => ({
        x: { label: null, tickFormat: (d: number) => `FY${String(d).slice(2)}` },
        y: {
          label: s?.unit ?? null,
          grid: true,
          nice: true,
          zero: measure !== "civil_median_months_to_disposition",
        },
        marks: [
          Plot.gridY({ stroke: t["chart-grid"], strokeOpacity: 1 }),
          Plot.lineY(s?.points ?? [], {
            x: "fiscal_year",
            y: "value",
            stroke: t["seq-3"],
            strokeWidth: 2,
          }),
          Plot.dot(s?.points ?? [], {
            x: "fiscal_year",
            y: "value",
            r: 3.5,
            fill: (p: { revision_status: string }) =>
              p.revision_status === "revised" ? t.revision : t["seq-3"],
            stroke: t.card,
          }),
          Plot.tip(
            s?.points ?? [],
            Plot.pointerX({
              x: "fiscal_year",
              y: "value",
              title: (p: {
                fiscal_year: number;
                value: number;
                edition: string;
                revision_status: string;
              }) =>
                `FY${p.fiscal_year}: ${fmtValue(p.value)} (${p.edition})${p.revision_status === "revised" ? "\nrevised in a later edition" : ""}`,
            }),
          ),
        ],
      }),
    [s, measure],
  );
  if (q.isPending) return <ChartSkeleton height={220} />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!s) return null;
  return (
    <PlotFigure
      height={220}
      title={m?.label ?? s.measure_label}
      label={`${s.measure_label} for ${s.court_name}, FY${FY_MIN}–FY${FY_MAX}`}
      caption={
        <>
          {s.vintage}. <span className="text-revision">Amber points were revised later.</span>
        </>
      }
      build={build as never}
      table={
        <DataTable
          columns={["FY", "Value", "Edition"]}
          rows={s.points.map((p) => [`FY${p.fiscal_year}`, fmtValue(p.value), p.edition])}
        />
      }
    />
  );
}

function CaseMix({ env }: { env?: Envelope<import("@/api/types.gen").CohortAnalysis> }) {
  const res = env?.data?.results?.[0];
  const all = [...(res?.breakdown ?? [])].sort((a, b) => (b.n ?? -1) - (a.n ?? -1));
  const rows = all.filter((r) => !r.suppressed && r.n !== null);
  const withheld = all.filter((r) => r.suppressed || r.n === null);
  if (!res || !all.length) return <EmptyState title="No IDB records for this court and year" />;
  return (
    <div className="rounded-lg border border-rule bg-card p-4">
      <table className="num w-full text-sm">
        <caption className="sr-only">Civil cases filed by case-type group</caption>
        <thead>
          <tr className="border-b border-rule text-left text-muted">
            <th scope="col" className="py-1 font-medium">
              Case type
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              Cases
            </th>
            <th scope="col" className="w-1/3 py-1 pl-3 font-medium">
              Share
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-rule/60">
              <td className="py-1 pr-2">{r.key}</td>
              <td className="py-1 text-right">
                <SuppressedCell n={r.n} suppressed={r.suppressed} />
              </td>
              <td className="py-1 pl-3">
                {r.share !== null && r.share !== undefined && !r.suppressed ? (
                  <span className="flex items-center gap-2">
                    <span
                      className="h-2 rounded-sm bg-[var(--seq-3)]"
                      style={{ width: `${Math.max(2, r.share * 100)}%` }}
                    />
                    <span className="text-ink-2">{fmtPct(r.share)}</span>
                  </span>
                ) : (
                  <span className="text-muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {withheld.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-ink-2">
            {withheld.length} more case type{withheld.length === 1 ? "" : "s"} with{" "}
            <SuppressedCell n={null} suppressed /> cases each
          </summary>
          <p className="mt-1 text-muted">{withheld.map((r) => r.key).join(" · ")}</p>
        </details>
      )}
      {env?.provenance?.[0] && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
          <ProvenanceBadge p={env.provenance[0]} /> n = {fmtValue(res.n)} cases.
        </p>
      )}
      {env?.warnings?.map((w) => (
        <div key={w.message} className="mt-2">
          <WarningCallout w={w} />
        </div>
      ))}
    </div>
  );
}
