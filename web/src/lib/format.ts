// Number formatting for published figures: tabular, thousands separators,
// the table's own precision, and suppressed values that never become 0.

const nf = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });

/** A published value as printed: 322, 1,234, 8.5 (no trailing .0). */
export function fmtValue(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number.isInteger(v) ? nf0.format(v) : nf.format(v);
}

export function fmtSigned(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = fmtValue(Math.abs(v));
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : "0";
}

export function fmtPct(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = pct.format(Math.abs(v));
  if (!signed) return v < 0 ? `−${s}` : s;
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : "0%";
}

/** Counts from the IDB: null means suppressed (fewer than 10), never 0. */
export function fmtCount(n: number | null | undefined, suppressed = false): string {
  if (suppressed || n === null || n === undefined) return "fewer than 10";
  return nf0.format(n);
}

export function fmtCi(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo === null || lo === undefined || hi === null || hi === undefined) return "";
  return `95% CI ${fmtValue(lo)}–${fmtValue(hi)}`;
}

/** "JFF-2023" → "JFF 2023" (badge form). */
export function editionLabel(edition: string): string {
  return edition.replace("-", " ");
}

export function fyLabel(fy: number): string {
  return `FY${fy}`;
}

export function fmtMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function fmtUsd(v: number): string {
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
}
