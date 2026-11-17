"""Compare two wxO eval runs item by item.

Usage:
    uv run python eval/wxo/compare_runs.py BASE.jsonl NEW.jsonl \
        [--shared-with REF.summary.json] [--group PREFIX ...]

Reports, for each run, on the items both runs share (or on the items of
--shared-with, when given), on the items only one run has, and on any
--group of item-id prefixes:
  attempts correct / attempts, the mean with a Wilson 95% interval,
  pass@k (an item right at least once) and pass^k (right on every repeat),
  and infra errors (wxO tool-runtime failures), counted separately.
Infra errors count as wrong in the mean, as in the run summaries.
Then lists the items whose per-item score changed.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (mid - half, mid + half)


def load(path: Path) -> dict[str, list[dict[str, Any]]]:
    items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            items[row["score"]["question_id"]].append(row["score"])
    return dict(items)


def stats(run: dict[str, list[dict[str, Any]]], ids: list[str]) -> dict[str, Any]:
    k = n = infra = pass_any = pass_all = 0
    for qid in ids:
        scores = run.get(qid, [])
        good = [bool(s["correct"]) for s in scores]
        k += sum(good)
        n += len(good)
        infra += sum(bool(s.get("infra_error")) for s in scores)
        pass_any += any(good)
        pass_all += bool(good) and all(good)
    lo, hi = wilson(k, n)
    m = len(ids)
    return {
        "items": m,
        "correct": k,
        "attempts": n,
        "mean": k / n if n else math.nan,
        "ci": (lo, hi),
        "pass_at_k": pass_any / m if m else math.nan,
        "pass_hat_k": pass_all / m if m else math.nan,
        "infra": infra,
    }


def fmt(s: dict[str, Any]) -> str:
    return (
        f"{s['correct']}/{s['attempts']} = {s['mean']:.1%} "
        f"({s['ci'][0]:.1%}–{s['ci'][1]:.1%}), pass@k {s['pass_at_k']:.1%}, "
        f"pass^k {s['pass_hat_k']:.1%}, infra {s['infra']}  [{s['items']} items]"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument(
        "--shared-with", type=Path, help="summary.json whose items define 'shared'"
    )
    ap.add_argument(
        "--group", action="append", default=[], help="item-id prefix to report on"
    )
    a = ap.parse_args()

    base, new = load(a.base), load(a.new)
    if a.shared_with:
        ref = json.loads(a.shared_with.read_text())["items"]
        shared = [q for q in ref if q in base and q in new]
    else:
        shared = sorted(set(base) & set(new))
    only_base = sorted(set(base) - set(new))
    only_new = sorted(set(new) - set(base))
    extra = sorted((set(base) | set(new)) - set(shared))

    print(f"base: {a.base.name}\nnew:  {a.new.name}\n")
    print("shared items")
    print("  base", fmt(stats(base, shared)))
    print("  new ", fmt(stats(new, shared)))

    def both(title: str, ids: list[str]) -> None:
        print(title)
        for name, run in (("base", base), ("new ", new)):
            have = [q for q in ids if q in run]
            print(f"  {name}", fmt(stats(run, have)) if have else "-")

    if extra:
        both("not in the shared set", extra)
    for prefix in a.group:
        both(
            f"group {prefix!r}",
            sorted(q for q in set(base) | set(new) if q.startswith(prefix)),
        )
    print("all items")
    print("  base", fmt(stats(base, sorted(base))))
    print("  new ", fmt(stats(new, sorted(new))))
    if only_base:
        print("\nonly in base:", ", ".join(only_base))
    if only_new:
        print("only in new: ", ", ".join(only_new))

    print("\nchanged items (correct/repeats, infra in brackets)")
    for qid in sorted(set(base) | set(new)):
        b, n = base.get(qid, []), new.get(qid, [])

        def cell(sc: list[dict[str, Any]]) -> str:
            if not sc:
                return "  -  "
            inf = sum(bool(s.get("infra_error")) for s in sc)
            ok = sum(bool(s["correct"]) for s in sc)
            return f"{ok}/{len(sc)}" + (f"[{inf}]" if inf else "")

        cb, cn = cell(b), cell(n)
        if cb.split("[")[0] != cn.split("[")[0]:
            print(f"  {qid:55s} {cb:>7s} -> {cn}")


if __name__ == "__main__":
    main()
