// Data for the VintageChart: one line per edition (each a consistent series
// the server returned, never a splice), plus "as first published". The gap
// between first publication and the newest edition is the revision story.
import type { OfficialSeries } from "@/api/types";
import type { EditionVintage } from "@/api/types.gen";

export interface VintagePoint {
  fy: number;
  value: number;
  edition: string;
  table: string;
}

export interface VintageLine {
  key: string;
  label: string;
  kind: "first" | "edition";
  /** Publication order among edition lines (0 = oldest). */
  rank: number;
  points: VintagePoint[];
}

export interface RevisionGap {
  fy: number;
  first: number;
  latest: number;
  firstEdition: string;
  latestEdition: string;
}

export function toPoints(s: OfficialSeries | null | undefined): VintagePoint[] {
  return (s?.points ?? []).map((p) => ({
    fy: p.fiscal_year,
    value: p.value,
    edition: p.edition,
    table: p.table_code,
  }));
}

/** Lines: the server's first-published series (dashed) and one line per
 * edition exactly as that edition prints it (oldest first). Editions that
 * print one year only (each Judicial Business edition) are already the
 * first-published line. */
export function vintageLines(
  first: OfficialSeries | null | undefined,
  editions: EditionVintage[],
  fromFy = -Infinity,
): VintageLine[] {
  const lines: VintageLine[] = [];
  const f = toPoints(first);
  if (f.length)
    lines.push({ key: "first", label: "As first published", kind: "first", rank: -1, points: f });
  editions
    .map((e) => ({
      edition: e.edition,
      points: e.points
        .filter((p) => p.fiscal_year >= fromFy)
        .map((p) => ({
          fy: p.fiscal_year,
          value: p.value,
          edition: e.edition,
          table: p.table_code,
        })),
    }))
    .filter((e) => e.points.length >= 2)
    .forEach((e, i) =>
      lines.push({ key: e.edition, label: e.edition, kind: "edition", rank: i, points: e.points }),
    );
  return lines;
}

/** For each year, the first-published value against the newest edition
 * (among the lines shown) that prints that year; years where they differ. */
export function revisionGaps(lines: VintageLine[]): RevisionGap[] {
  const first = lines.find((l) => l.kind === "first");
  const eds = lines.filter((l) => l.kind === "edition").sort((a, b) => a.rank - b.rank);
  if (!first || !eds.length) return [];
  const newest = new Map<number, VintagePoint>();
  for (const l of eds) for (const p of l.points) newest.set(p.fy, p);
  return first.points
    .map((f) => ({ f, l: newest.get(f.fy) }))
    .filter(({ f, l }) => l !== undefined && l.value !== f.value)
    .map(({ f, l }) => ({
      fy: f.fy,
      first: f.value,
      latest: l!.value,
      firstEdition: f.edition,
      latestEdition: l!.edition,
    }));
}

/** A figure's value in every edition that printed it, flagging changes. */
export function editionHistory(
  editions: { value: number; edition: string; table_code: string }[],
): { edition: string; value: number; table: string; changed: boolean }[] {
  return editions.map((e, i) => ({
    edition: e.edition,
    value: e.value,
    table: e.table_code,
    changed: i > 0 && e.value !== editions[i - 1]!.value,
  }));
}

/** Ramp step (0–3) for an edition line: older lighter, newest darkest. */
export function rampStep(rank: number, count: number): number {
  if (count <= 1) return 3;
  return Math.round((rank / (count - 1)) * 3);
}
