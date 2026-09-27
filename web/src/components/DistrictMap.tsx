// The 94 districts shaded by one measure. Geometry: us-atlas counties (Albers
// USA, already projected to a 975×610 frame) merged by an IDB-derived
// county → district crosswalk (scripts/build-districts.mjs); territories are
// tiles. The ranking table beside the map is the accessible view; the map
// adds pointer hover and click-through.
import { useEffect, useMemo, useState } from "react";
import { geoPath } from "d3-geo";
import { feature, mesh } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import type { Feature, Geometry } from "geojson";
import { fmtValue } from "@/lib/format";
import { useTokens } from "@/lib/tokens";

export interface Bin {
  lo: number;
  hi: number;
  label: string;
}

/** Judicial Conference thresholds for weighted filings; quartiles otherwise. */
export function binsFor(values: number[], thresholds: boolean): Bin[] {
  if (thresholds) {
    return [
      { lo: -Infinity, hi: 430, label: "Under 430" },
      { lo: 430, hi: 600, label: "430–600" },
      { lo: 600, hi: 1000, label: "600–1,000" },
      { lo: 1000, hi: Infinity, label: "Over 1,000" },
    ];
  }
  const s = [...values].sort((a, b) => a - b);
  if (s.length < 4) return [{ lo: -Infinity, hi: Infinity, label: "All" }];
  const q = (p: number) => s[Math.min(s.length - 1, Math.floor(p * s.length))]!;
  const cuts = [q(0.25), q(0.5), q(0.75)];
  return [
    { lo: -Infinity, hi: cuts[0]!, label: `Under ${fmtValue(cuts[0]!)}` },
    { lo: cuts[0]!, hi: cuts[1]!, label: `${fmtValue(cuts[0]!)}–${fmtValue(cuts[1]!)}` },
    { lo: cuts[1]!, hi: cuts[2]!, label: `${fmtValue(cuts[1]!)}–${fmtValue(cuts[2]!)}` },
    { lo: cuts[2]!, hi: Infinity, label: `${fmtValue(cuts[2]!)} and over` },
  ];
}

export function binIndex(v: number, bins: Bin[]): number {
  const i = bins.findIndex((b) => v >= b.lo && v < b.hi);
  return i < 0 ? bins.length - 1 : i;
}

type Topo = Topology<{ districts: GeometryCollection; states: GeometryCollection }>;

let cache: Promise<Topo> | null = null;
function loadTopo(): Promise<Topo> {
  cache ??= fetch("/geo/districts.topo.json").then((r) => {
    if (!r.ok) throw new Error(`map geometry: HTTP ${r.status}`);
    return r.json() as Promise<Topo>;
  });
  return cache;
}

const TERRITORIES = [
  { code: "PR", label: "P.R." },
  { code: "VI", label: "V.I." },
  { code: "GU", label: "Guam" },
  { code: "MP", label: "N. Mar. I." },
];

export function DistrictMap({
  values,
  names,
  thresholds,
  onSelect,
  selected,
  unitLabel,
}: {
  values: Map<string, number>;
  names: Map<string, string>;
  thresholds: boolean;
  onSelect?: (court: string) => void;
  selected?: string | null;
  unitLabel: string;
}) {
  const t = useTokens();
  const [topo, setTopo] = useState<Topo | null>(null);
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState<{ code: string; x: number; y: number } | null>(null);
  useEffect(() => {
    let live = true;
    loadTopo()
      .then((x) => live && setTopo(x))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);
  const bins = useMemo(() => binsFor([...values.values()], thresholds), [values, thresholds]);
  const ramp = [t["seq-1"], t["seq-2"], t["seq-3"], t["seq-4"]];
  const color = (code: string) => {
    const v = values.get(code);
    return v === undefined ? t["paper"] : ramp[Math.min(3, binIndex(v, bins))]!;
  };
  const shapes = useMemo(() => {
    if (!topo) return null;
    const path = geoPath();
    const fc = feature(topo, topo.objects.districts) as { features: Feature<Geometry>[] };
    return {
      districts: fc.features.map((f) => ({ id: String(f.id), d: path(f) ?? "" })),
      states: path(mesh(topo, topo.objects.states, (a, b) => a !== b)) ?? "",
      outline: path(mesh(topo, topo.objects.states, (a, b) => a === b)) ?? "",
    };
  }, [topo]);

  if (failed)
    return (
      <p className="text-sm text-muted">The map couldn't load; the table has every district.</p>
    );
  const hv = hover ? values.get(hover.code) : undefined;
  return (
    <div className="relative">
      <svg
        viewBox="0 0 975 655"
        className="h-auto w-full"
        role="img"
        aria-label={`Map of federal judicial districts shaded by ${unitLabel}. The table lists every value.`}
        onMouseLeave={() => setHover(null)}
      >
        {shapes?.districts.map((s) => (
          <path
            key={s.id}
            d={s.d}
            fill={color(s.id)}
            stroke={selected === s.id ? t.ink : t.card}
            strokeWidth={selected === s.id ? 2.5 : 0.8}
            className={onSelect ? "cursor-pointer" : undefined}
            onMouseMove={(e) => {
              const box = (
                e.currentTarget.ownerSVGElement as SVGSVGElement
              ).getBoundingClientRect();
              setHover({ code: s.id, x: e.clientX - box.left, y: e.clientY - box.top });
            }}
            onClick={() => onSelect?.(s.id)}
          >
            <title>
              {`${names.get(s.id) ?? s.id}: ${values.has(s.id) ? fmtValue(values.get(s.id)!) : "not published"}`}
            </title>
          </path>
        ))}
        {shapes && (
          <path
            d={shapes.states}
            fill="none"
            stroke={t["ink-2"]}
            strokeWidth={0.9}
            strokeOpacity={0.55}
          />
        )}
        {shapes && (
          <path
            d={shapes.outline}
            fill="none"
            stroke={t["ink-2"]}
            strokeWidth={1}
            strokeOpacity={0.5}
          />
        )}
        {TERRITORIES.map((tt, i) => (
          <g
            key={tt.code}
            transform={`translate(${600 + i * 90}, 628)`}
            className={onSelect ? "cursor-pointer" : undefined}
            onClick={() => onSelect?.(tt.code)}
            onMouseMove={(e) => {
              const box = (
                e.currentTarget.ownerSVGElement as SVGSVGElement
              ).getBoundingClientRect();
              setHover({ code: tt.code, x: e.clientX - box.left, y: e.clientY - box.top });
            }}
          >
            <rect
              width={30}
              height={22}
              rx={4}
              fill={color(tt.code)}
              stroke={selected === tt.code ? t.ink : t["rule"]}
              strokeWidth={selected === tt.code ? 2.5 : 1}
            />
            <text x={36} y={15} fontSize={12} fill={t["ink-2"]}>
              {tt.label}
            </text>
            <title>
              {`${names.get(tt.code) ?? tt.code}: ${values.has(tt.code) ? fmtValue(values.get(tt.code)!) : "not published"}`}
            </title>
          </g>
        ))}
      </svg>
      {!shapes && <div className="absolute inset-0 animate-pulse rounded bg-paper-2" aria-hidden />}
      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-rule bg-card px-3 py-2 text-sm shadow"
          style={{ left: Math.min(hover.x + 14, 700), top: hover.y + 14 }}
        >
          <p className="font-semibold text-ink">{names.get(hover.code) ?? hover.code}</p>
          <p className="num text-ink-2">
            {hv === undefined ? "Not published" : `${fmtValue(hv)} ${unitLabel}`}
          </p>
        </div>
      )}
      <MapLegend bins={bins} ramp={ramp} thresholds={thresholds} missing={t.paper} rule={t.rule} />
    </div>
  );
}

function MapLegend({
  bins,
  ramp,
  thresholds,
  missing,
  rule,
}: {
  bins: Bin[];
  ramp: string[];
  thresholds: boolean;
  missing: string;
  rule: string;
}) {
  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2"
      aria-label="Legend"
    >
      {bins.map((b, i) => (
        <span key={b.label} className="inline-flex items-center gap-1.5">
          <span
            className="inline-block size-3 rounded-sm"
            style={{ background: ramp[Math.min(3, i)] }}
          />
          <span className="num">{b.label}</span>
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-block size-3 rounded-sm border"
          style={{ background: missing, borderColor: rule }}
        />
        Not published
      </span>
      {thresholds && (
        <span className="text-muted">
          430: the Judicial Conference's standard for considering a judgeship. 600: the
          judicial-emergency filings threshold (with a vacancy).
        </span>
      )}
    </div>
  );
}
