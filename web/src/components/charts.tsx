// Charts: Observable Plot inside a responsive figure, each with a caption
// that names its source and a data-table view (identity never by color
// alone). Colors are resolved design tokens (validated ramps; amber only for
// revisions).
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as Plot from "@observablehq/plot";
import type { ChartSpec, Contribution } from "@/api/types";
import { editionLabel, fmtSigned, fmtValue } from "@/lib/format";
import { useTokens, type Tokens } from "@/lib/tokens";
import { rampStep, revisionGaps, type VintageLine } from "@/lib/vintage";
import { waterfall, type WaterfallStep } from "@/lib/waterfall";

type Build = (width: number, t: Tokens) => Plot.PlotOptions;

export function PlotFigure({
  build,
  title,
  caption,
  table,
  height = 320,
  label,
}: {
  build: Build;
  title: string;
  caption?: ReactNode;
  table?: ReactNode;
  height?: number;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const tokens = useTokens();
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry!.contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const opts = build(width, tokens);
    const svg = Plot.plot({
      width,
      height,
      marginLeft: 56,
      style: {
        background: "transparent",
        color: tokens["ink-2"],
        fontFamily: "Public Sans Variable, system-ui, sans-serif",
        fontSize: "12px",
        overflow: "visible",
      },
      ...opts,
    });
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
    // Plot labels its mark groups; inside role="img" those labels are
    // prohibited (the figure's label and its data table carry the meaning).
    svg.querySelectorAll("[aria-label]").forEach((el) => {
      if (el !== svg) el.removeAttribute("aria-label");
    });
    el.replaceChildren(svg);
    return () => svg.remove();
  }, [build, width, height, tokens, label]);
  return (
    <figure className="rounded-lg border border-rule bg-card p-4">
      <figcaption className="mb-2">
        <span className="block font-semibold text-ink">{title}</span>
        {caption && <span className="mt-0.5 block text-sm text-muted">{caption}</span>}
      </figcaption>
      {/* Reserve the plot's height so rendering it doesn't shift the page. */}
      <div ref={ref} className="w-full" style={{ minHeight: height }} />
      {table && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-accent">Show the data as a table</summary>
          <div className="mt-2 overflow-x-auto">{table}</div>
        </details>
      )}
    </figure>
  );
}

export function DataTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: (string | number | ReactNode)[][];
}) {
  return (
    <table className="num w-full text-left text-sm">
      <thead>
        <tr className="border-b border-rule text-muted">
          {columns.map((c) => (
            <th key={c} scope="col" className="py-1 pr-4 font-medium">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-b border-rule/60">
            {r.map((c, j) => (
              <td key={j} className="py-1 pr-4">
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── VintageChart ─────────────────────────────────────────────────────────────

/** The hero visual: one line per edition, "as first published" dashed, and
 * the gap between first publication and the newest edition shaded amber. */
export function VintageChart({
  lines,
  unit,
  title,
  source,
}: {
  lines: VintageLine[];
  unit: string;
  title: string;
  source: string;
}) {
  const gaps = useMemo(() => revisionGaps(lines), [lines]);
  const editions = lines.filter((l) => l.kind === "edition");
  const build = useMemo<Build>(
    () => (_w, t) => {
      const ramp = [t["seq-1"], t["seq-2"], t["seq-3"], t["seq-4"]];
      const colorOf = (l: VintageLine) =>
        l.kind === "first" ? t["ink-2"] : ramp[rampStep(l.rank, editions.length)]!;
      const pts = lines.flatMap((l) =>
        l.points.map((p) => ({ ...p, line: l.label, color: colorOf(l) })),
      );
      const newest = editions.at(-1);
      const labelled = [lines.find((l) => l.kind === "first"), newest].filter(
        (l): l is VintageLine => l !== undefined,
      );
      return {
        x: {
          label: "Fiscal year",
          tickFormat: (d: number) => `FY${String(d).slice(2)}`,
          grid: false,
        },
        y: { label: unit, grid: false, zero: false, nice: true },
        marks: [
          Plot.gridY({ stroke: t["chart-grid"], strokeOpacity: 1 }),
          // One amber band per revised year (never an area across years).
          Plot.ruleX(gaps, {
            x: "fy",
            y1: "first",
            y2: "latest",
            stroke: t["revision-rule"],
            strokeWidth: 12,
            strokeOpacity: 0.35,
          }),
          Plot.ruleX(gaps, {
            x: "fy",
            y1: "first",
            y2: "latest",
            stroke: t.revision,
            strokeWidth: 2,
            strokeDasharray: "3,2",
          }),
          ...lines.map((l) =>
            Plot.lineY(l.points, {
              x: "fy",
              y: "value",
              stroke: colorOf(l),
              strokeWidth: l === newest || l.kind === "first" ? 2.5 : 1.5,
              strokeDasharray: l.kind === "first" ? "6,3" : undefined,
            }),
          ),
          Plot.dot(pts, {
            x: "fy",
            y: "value",
            r: 3.5,
            fill: "color",
            stroke: t.card,
            strokeWidth: 1.5,
          }),
          // Direct labels for the two lines that tell the story.
          ...labelled.map((l) =>
            Plot.text(l.points.slice(-1), {
              x: "fy",
              y: "value",
              text: () => (l.kind === "first" ? "As first published" : `${l.label} (newest)`),
              dx: 8,
              textAnchor: "start",
              fill: t.ink,
              fontWeight: 600,
            }),
          ),
          Plot.tip(
            pts,
            Plot.pointer({
              x: "fy",
              y: "value",
              title: (d: {
                line: string;
                fy: number;
                value: number;
                edition: string;
                table: string;
              }) =>
                `${d.line}\nFY${d.fy}: ${fmtValue(d.value)}\n${editionLabel(d.edition)}, Table ${d.table}`,
            }),
          ),
        ],
        marginRight: 150,
      };
    },
    [lines, gaps, unit, editions],
  );
  const years = [...new Set(lines.flatMap((l) => l.points.map((p) => p.fy)))].sort();
  return (
    <PlotFigure
      build={build}
      title={title}
      label={`${title}. ${lines.length} series; ${gaps.length} years differ between first publication and the newest edition.`}
      caption={
        <>
          Dashed: each year as first published. Solid: one line per edition, darker for newer.{" "}
          {gaps.length ? (
            <span className="text-revision">
              Amber marks the {gaps.length} years a later edition revised (first published vs the
              newest edition printing that year).
            </span>
          ) : (
            "No year was revised."
          )}{" "}
          {source}
        </>
      }
      table={
        <DataTable
          columns={["Fiscal year", ...lines.map((l) => l.label)]}
          rows={years.map((fy) => [
            `FY${fy}`,
            ...lines.map((l) => {
              const p = l.points.find((q) => q.fy === fy);
              return p
                ? l.kind === "first"
                  ? `${fmtValue(p.value)} (${p.edition})`
                  : fmtValue(p.value)
                : "—";
            }),
          ])}
        />
      }
    />
  );
}

// ── ContributorWaterfall ─────────────────────────────────────────────────────

export function ContributorWaterfall({
  start,
  end,
  contributions,
  startLabel,
  endLabel,
  title,
  unit,
  source,
}: {
  start: number;
  end: number;
  contributions: Contribution[];
  startLabel: string;
  endLabel: string;
  title: string;
  unit: string;
  source: string;
}) {
  const steps = useMemo(
    () => waterfall(start, end, contributions, 6, startLabel, endLabel),
    [start, end, contributions, startLabel, endLabel],
  );
  const build = useMemo<Build>(
    () => (w, t) => {
      const fill = (s: WaterfallStep) =>
        s.kind === "up" ? t["pole-up"] : s.kind === "down" ? t["pole-down"] : t["ink-2"];
      const narrow = w < 560;
      return {
        x: { label: null, domain: steps.map((s) => s.label), tickRotate: narrow ? -30 : 0 },
        y: { label: unit, grid: true, nice: true },
        marginBottom: narrow ? 70 : 40,
        marks: [
          Plot.gridY({ stroke: t["chart-grid"], strokeOpacity: 1 }),
          Plot.barY(steps, {
            x: "label",
            y1: "from",
            y2: "to",
            fill,
            rx: 3,
            inset: 3,
          }),
          Plot.text(steps, {
            x: "label",
            y: (s: WaterfallStep) => Math.max(s.from, s.to),
            text: (s: WaterfallStep) =>
              s.kind === "start" || s.kind === "end" ? fmtValue(s.to) : fmtSigned(s.change),
            dy: -8,
            fill: t.ink,
            fontWeight: 600,
          }),
          Plot.ruleY([0], { stroke: t.muted }),
          Plot.tip(
            steps,
            Plot.pointerX({
              x: "label",
              y: "to",
              title: (s: WaterfallStep) =>
                s.kind === "start" || s.kind === "end"
                  ? `${s.label}: ${fmtValue(s.to)}`
                  : `${s.label}: ${fmtSigned(s.change)}${s.key ? " (key contributor)" : ""}`,
            }),
          ),
        ],
      };
    },
    [steps, unit],
  );
  return (
    <PlotFigure
      build={build}
      title={title}
      label={`${title}: from ${fmtValue(start)} to ${fmtValue(end)}`}
      caption={<>Blue bars add, red bars subtract; the steps sum exactly to the change. {source}</>}
      table={
        <DataTable
          columns={["Step", "Change", "Running total"]}
          rows={steps.map((s) => [
            s.label,
            s.kind === "start" || s.kind === "end" ? "" : fmtSigned(s.change),
            fmtValue(s.to),
          ])}
        />
      }
    />
  );
}

// ── Charts the agent sends (ChartSpec) ───────────────────────────────────────

export function SpecChart({ spec }: { spec: ChartSpec }) {
  const points = spec.series.flatMap((s) => s.points.map((p) => ({ ...p, series: s.name })));
  const build = useMemo<Build>(
    () => (w, t) => {
      if (spec.kind === "waterfall") {
        return {
          x: { label: null, tickRotate: w < 560 ? -30 : 0 },
          y: { label: spec.y_label, grid: true, nice: true },
          marginBottom: w < 560 ? 80 : 40,
          marks: [
            Plot.gridY({ stroke: t["chart-grid"], strokeOpacity: 1 }),
            Plot.barY(points, {
              x: "x",
              y: "y",
              fill: (d: { y: number }) => (d.y >= 0 ? t["pole-up"] : t["pole-down"]),
              rx: 3,
              inset: 3,
              sort: { x: "-y", reduce: (v: number[]) => Math.abs(v[0] ?? 0) },
            }),
            Plot.ruleY([0], { stroke: t.muted }),
            Plot.tip(
              points,
              Plot.pointerX({
                x: "x",
                y: "y",
                title: (d: { x: string; y: number }) => `${d.x}: ${fmtSigned(d.y)}`,
              }),
            ),
          ],
        };
      }
      const horizontal = spec.kind === "bar";
      if (horizontal) {
        return {
          marginLeft: Math.min(160, 12 + 7 * Math.max(...points.map((p) => p.x.length))),
          x: { label: spec.y_label, grid: true, nice: true },
          y: { label: null, domain: points.map((p) => p.x) },
          height: 28 * points.length + 40,
          marks: [
            Plot.gridX({ stroke: t["chart-grid"], strokeOpacity: 1 }),
            Plot.barX(points, {
              y: "x",
              x: "y",
              fill: t["seq-3"],
              rx: 3,
              insetTop: 3,
              insetBottom: 3,
            }),
            Plot.text(points, {
              y: "x",
              x: "y",
              text: (d: { label?: string | null; y: number }) => d.label ?? fmtValue(d.y),
              dx: 6,
              textAnchor: "start",
              fill: t.ink,
            }),
            Plot.tip(
              points,
              Plot.pointerY({
                y: "x",
                x: "y",
                title: (d: { x: string; y: number }) => `${d.x}: ${fmtValue(d.y)}`,
              }),
            ),
          ],
        };
      }
      // "editions": one figure's value in every edition that printed it.
      return {
        x: { label: spec.x_label, domain: points.map((p) => p.x) },
        y: { label: spec.y_label, grid: true, nice: true, zero: true },
        marks: [
          Plot.gridY({ stroke: t["chart-grid"], strokeOpacity: 1 }),
          Plot.barY(points, {
            x: "x",
            y: "y",
            fill: (_d: unknown, i: number) =>
              i > 0 && points[i]!.y !== points[i - 1]!.y ? t.revision : t["seq-3"],
            rx: 3,
            inset: 4,
          }),
          Plot.text(points, {
            x: "x",
            y: "y",
            text: (d: { y: number }) => fmtValue(d.y),
            dy: -8,
            fill: t.ink,
            fontWeight: 600,
          }),
          Plot.tip(
            points,
            Plot.pointerX({
              x: "x",
              y: "y",
              title: (d: { x: string; y: number }) => `${d.x}: ${fmtValue(d.y)}`,
            }),
          ),
        ],
      };
    },
    [spec, points],
  );
  return (
    <PlotFigure
      build={build}
      title={spec.title}
      label={spec.title}
      height={spec.kind === "bar" ? 28 * points.length + 40 : 300}
      caption={
        <>
          {spec.kind === "editions" && (
            <span className="text-revision">Amber bars are editions that changed the value. </span>
          )}
          Source: {spec.source}
        </>
      }
      table={
        <DataTable
          columns={[spec.x_label, spec.y_label]}
          rows={points.map((p) => [
            p.x,
            spec.kind === "waterfall" ? fmtSigned(p.y) : fmtValue(p.y),
          ])}
        />
      }
    />
  );
}
