import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Slider, ToggleGroup } from "radix-ui";
import { api } from "@/api/client";
import { DistrictMap } from "@/components/DistrictMap";
import { PageHeader } from "@/components/Layout";
import { ProvenanceBadge, WarningCallout } from "@/components/Provenance";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { courtNames, courtSlug, useCourts } from "@/lib/courts";
import { editionLabel, fmtValue } from "@/lib/format";
import { bySlug, FY_MAX, FY_MIN, MEASURES } from "@/lib/measures";
import { Select } from "./Editions";

export interface ExploreSearch {
  measure?: string;
  fy?: number;
  edition?: "latest" | "first_published";
  over?: number;
}

export function ExplorePage({ search }: { search: ExploreSearch }) {
  const navigate = useNavigate({ from: "/explore" });
  const measure = bySlug(search.measure ?? "") ?? MEASURES[0]!;
  const fy = search.fy ?? FY_MAX;
  const edition = search.edition ?? "latest";
  const over = search.over;
  const [sort, setSort] = useState<{ key: "value" | "name"; dir: "asc" | "desc" }>({
    key: "value",
    dir: "desc",
  });
  const courts = useCourts();
  const names = courtNames(courts.data?.courts);
  const set = (p: Partial<ExploreSearch>) =>
    navigate({ search: (s: ExploreSearch) => ({ ...s, ...p }), replace: true });

  const q = useQuery({
    queryKey: ["compare", measure.id, fy, edition],
    queryFn: () => api.compare({ measure: measure.id, fiscal_year: fy, edition }),
  });
  const data = q.data?.data;
  const values = useMemo(() => new Map((data?.rows ?? []).map((r) => [r.court, r.value])), [data]);
  const rows = useMemo(() => {
    const rs = [...(data?.rows ?? [])].filter((r) => over === undefined || r.value > over);
    rs.sort((a, b) => {
      const c =
        sort.key === "value"
          ? a.value - b.value
          : (a.citation ?? a.court_name).localeCompare(b.citation ?? b.court_name);
      return sort.dir === "asc" ? c : -c;
    });
    return rs;
  }, [data, over, sort]);

  const toggleSort = (key: "value" | "name") =>
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "value" ? "desc" : "asc" },
    );

  return (
    <div>
      <PageHeader
        title="Explore the districts"
        lede="Every district on one measure, from one edition of one table. Pick a year, the current or the first-published edition, and click a district for its profile."
      />
      <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-3">
        <Select
          label="Measure"
          value={measure.slug}
          onChange={(v) => set({ measure: v, over: undefined })}
        >
          {MEASURES.filter((m) => m.id !== "civil_median_months_to_disposition").map((m) => (
            <option key={m.slug} value={m.slug}>
              {m.label}
            </option>
          ))}
        </Select>
        <div className="flex min-w-56 flex-col gap-1 text-sm">
          <span id="fy-label" className="font-medium text-ink-2">
            Fiscal year: <span className="num text-ink">FY{fy}</span>
          </span>
          <Slider.Root
            className="relative flex h-5 w-56 touch-none select-none items-center"
            min={FY_MIN}
            max={FY_MAX}
            step={1}
            value={[fy]}
            onValueChange={([v]) => set({ fy: v })}
            aria-labelledby="fy-label"
          >
            <Slider.Track className="relative h-1 grow rounded-full bg-rule">
              <Slider.Range className="absolute h-full rounded-full bg-accent" />
            </Slider.Track>
            <Slider.Thumb
              aria-label="Fiscal year"
              className="block size-4 rounded-full border-2 border-accent bg-card shadow"
            />
          </Slider.Root>
        </div>
        <div className="flex flex-col gap-1 text-sm">
          <span id="ed-label" className="font-medium text-ink-2">
            Edition
          </span>
          <ToggleGroup.Root
            type="single"
            value={edition}
            onValueChange={(v) => v && set({ edition: v as ExploreSearch["edition"] })}
            aria-labelledby="ed-label"
            className="inline-flex rounded-md border border-rule bg-card p-0.5"
          >
            {[
              ["latest", "Current"],
              ["first_published", "As first published"],
            ].map(([v, l]) => (
              <ToggleGroup.Item
                key={v}
                value={v!}
                className="rounded px-3 py-1 text-ink-2 data-[state=on]:bg-accent data-[state=on]:text-accent-ink"
              >
                {l}
              </ToggleGroup.Item>
            ))}
          </ToggleGroup.Root>
        </div>
        {measure.thresholds && (
          <div className="flex flex-col gap-1 text-sm">
            <span id="over-label" className="font-medium text-ink-2">
              Show
            </span>
            <ToggleGroup.Root
              type="single"
              value={over === undefined ? "all" : String(over)}
              onValueChange={(v) => v && set({ over: v === "all" ? undefined : Number(v) })}
              aria-labelledby="over-label"
              className="inline-flex rounded-md border border-rule bg-card p-0.5"
            >
              {[
                ["all", "All"],
                ["430", "Over 430"],
                ["600", "Over 600"],
              ].map(([v, l]) => (
                <ToggleGroup.Item
                  key={v}
                  value={v!}
                  className="rounded px-3 py-1 text-ink-2 data-[state=on]:bg-accent data-[state=on]:text-accent-ink"
                >
                  {l}
                </ToggleGroup.Item>
              ))}
            </ToggleGroup.Root>
          </div>
        )}
      </div>

      {q.isPending ? (
        <Loading label="Loading districts…" lines={6} />
      ) : q.error ? (
        <ErrorState error={q.error} retry={() => void q.refetch()} />
      ) : !data ? (
        <EmptyState title="No figures for this selection" />
      ) : (
        <>
          <p className="mb-3 flex flex-wrap items-center gap-2 text-ink-2" aria-live="polite">
            <span>
              <strong className="num text-ink">{rows.length}</strong>
              {over !== undefined ? ` of ${data.rows.length} districts over ${over}` : " districts"}
              , all from <strong className="text-ink">{editionLabel(data.edition)}</strong>, Table{" "}
              {data.table_code}.
            </span>
            {q.data?.provenance?.[0] && <ProvenanceBadge p={q.data.provenance[0]} />}
            {data.national && (
              <span className="text-sm text-muted">
                National: <span className="num">{fmtValue(data.national.value)}</span> in the same
                edition.
              </span>
            )}
          </p>
          {q.data?.warnings?.map((w) => (
            <div key={w.message} className="mb-3">
              <WarningCallout w={w} />
            </div>
          ))}
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="rounded-lg border border-rule bg-card p-3">
              <DistrictMap
                values={values}
                names={names}
                thresholds={measure.thresholds}
                unitLabel={measure.unit}
                onSelect={(c) =>
                  navigate({ to: "/courts/$court", params: { court: courtSlug(c) } })
                }
              />
            </div>
            <div className="max-h-[42rem] overflow-auto rounded-lg border border-rule bg-card">
              <table className="num w-full text-sm">
                <caption className="sr-only">
                  {measure.label}, FY{fy}, {editionLabel(data.edition)}
                </caption>
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-rule text-left text-muted">
                    <th scope="col" className="px-3 py-2 font-medium">
                      #
                    </th>
                    <th
                      scope="col"
                      className="px-3 py-2 font-medium"
                      aria-sort={
                        sort.key === "name"
                          ? sort.dir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort("name")}
                        className="hover:text-ink"
                      >
                        District
                      </button>
                    </th>
                    <th
                      scope="col"
                      className="px-3 py-2 text-right font-medium"
                      aria-sort={
                        sort.key === "value"
                          ? sort.dir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort("value")}
                        className="hover:text-ink"
                      >
                        {measure.short}{" "}
                        {sort.key === "value" ? (sort.dir === "desc" ? "↓" : "↑") : ""}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.court} className="border-b border-rule/60 hover:bg-paper-2">
                      <td className="px-3 py-1.5 text-muted">{r.rank}</td>
                      <td className="px-3 py-1.5">
                        <Link
                          to="/courts/$court"
                          params={{ court: courtSlug(r.court) }}
                          className="text-ink hover:text-accent hover:underline"
                        >
                          {r.citation ?? r.court_name}
                        </Link>
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        {fmtValue(r.value)}
                        {measure.thresholds && r.value > 600 && (
                          <span className="ml-2 rounded bg-paper-2 px-1.5 text-xs text-ink-2">
                            &gt;600
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(data.not_published ?? []).length > 0 && (
                <p className="px-3 py-2 text-xs text-muted">
                  Not published in this edition:{" "}
                  {(data.not_published ?? []).map((c) => names.get(c) ?? c).join(", ")}.
                </p>
              )}
            </div>
          </div>
          <p className="mt-3 text-xs text-muted">
            District boundaries are drawn from county lines using an assignment derived from IDB
            filings by county; a few border counties may be placed in a neighbouring district. The
            table is exact.{" "}
            <Link to="/methodology" className="underline">
              Methodology
            </Link>
            .
          </p>
        </>
      )}
    </div>
  );
}
