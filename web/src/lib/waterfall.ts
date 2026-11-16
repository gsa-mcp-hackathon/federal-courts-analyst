// ContributorWaterfall data: start → contributors (largest first, the rest
// folded into "All other") → end. The steps always sum to end − start.
import type { Contribution } from "@/api/types";

export interface WaterfallStep {
  label: string;
  kind: "start" | "up" | "down" | "end";
  from: number;
  to: number;
  change: number;
  key?: boolean;
}

export function waterfall(
  start: number,
  end: number,
  contributions: Contribution[],
  maxSteps = 6,
  startLabel = "Start",
  endLabel = "End",
): WaterfallStep[] {
  const sorted = [...contributions].sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
  const shown = sorted.slice(0, maxSteps);
  const folded = sorted.slice(maxSteps).reduce((s, c) => s + c.change, 0);
  const explained = shown.reduce((s, c) => s + c.change, 0) + folded;
  // Anything the breakdown doesn't cover (rounding, or a different series)
  // goes into "All other" so the steps land exactly on `end`.
  const rest = folded + (end - start - explained);
  const steps: WaterfallStep[] = [
    { label: startLabel, kind: "start", from: 0, to: start, change: start },
  ];
  let level = start;
  const push = (label: string, change: number, key?: boolean) => {
    if (change === 0) return;
    steps.push({
      label,
      kind: change > 0 ? "up" : "down",
      from: level,
      to: level + change,
      change,
      key,
    });
    level += change;
  };
  for (const c of shown) push(c.label, c.change, c.key_contributor);
  if (Math.abs(rest) > 1e-9) push("All other", rest);
  steps.push({ label: endLabel, kind: "end", from: 0, to: end, change: end });
  return steps;
}
