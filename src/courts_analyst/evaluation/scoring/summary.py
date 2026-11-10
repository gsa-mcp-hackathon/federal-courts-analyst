"""Aggregate item scores: accuracy by suite and split, behaviour confusion
matrix with precision/recall per class, error taxonomy, latency."""

from __future__ import annotations

import math
from collections import Counter
from statistics import median

from pydantic import BaseModel, Field

from courts_analyst.evaluation.records import ItemScore

BEHAVIORS = ("answer", "clarify", "decline")


class SubsetInfo(BaseModel):
    """Metadata about an ``--agent-tools`` subset filter applied to a run."""

    tools: list[str]
    n_slice: int
    n_subset: int
    preset: str | None = None


class ClassMetrics(BaseModel):
    precision: float | None
    recall: float | None
    support: int


class WilsonCI(BaseModel):
    low: float
    high: float


class RunSummary(BaseModel):
    """Headline numbers for one run."""

    n: int
    correct: int
    accuracy: float | None
    by_suite: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    by_split: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    by_check: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    behavior_confusion: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="expected → actual → count"
    )
    behavior_metrics: dict[str, ClassMetrics] = Field(default_factory=dict)
    error_categories: dict[str, int] = Field(default_factory=dict)
    latency_p50_s: float | None = None
    latency_p95_s: float | None = None
    cost_usd: float | None = Field(
        default=None, description="Total model cost of the run (paid answerers)."
    )
    cost_per_question_usd: float | None = None
    # Repeats fields – present only when K > 1, always loadable (defaults None/empty)
    repeats: int | None = Field(
        default=None, description="K value; None or 1 means a single-attempt run."
    )
    accuracy_ci95: WilsonCI | None = Field(
        default=None, description="Wilson 95% CI on the overall accuracy."
    )
    pass_at_k: float | None = Field(
        default=None,
        description="Share of items correct in at least one attempt.",
    )
    pass_hat_k: float | None = Field(
        default=None,
        description="Share of items correct in every attempt.",
    )
    per_item: dict[str, int] = Field(
        default_factory=dict,
        description="question_id → number of correct attempts (repeats runs only).",
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def wilson_ci95(k: int, n: int, z: float = 1.96) -> WilsonCI:
    """Wilson score 95% confidence interval for a proportion.

    Args:
        k: number of successes
        n: total trials
        z: normal quantile (1.96 for 95%)

    Returns a WilsonCI with ``low`` and ``high`` in [0, 1].
    """
    if n == 0:
        return WilsonCI(low=0.0, high=1.0)
    p_hat = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p_hat + z2 / (2 * n)) / denom
    half = z * math.sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n)) / denom
    return WilsonCI(
        low=max(0.0, centre - half),
        high=min(1.0, centre + half),
    )


def _acc(scores: list[ItemScore]) -> dict[str, float | int | None]:
    n = len(scores)
    c = sum(s.correct for s in scores)
    return {"n": n, "correct": c, "accuracy": c / n if n else None}


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


# ---------------------------------------------------------------------------
# Main aggregation
# ---------------------------------------------------------------------------


def summarize(
    scores: list[ItemScore],
    repeats: int = 1,
) -> RunSummary:
    """Aggregate *scores* into a RunSummary.

    When *repeats* > 1 the scores list contains K attempts per question_id
    (in repeat order).  The overall ``accuracy`` is the mean over **all**
    attempts; ``pass_at_k``/``pass_hat_k`` are per-item aggregates.
    """
    confusion = {e: dict.fromkeys(BEHAVIORS, 0) for e in BEHAVIORS}
    for s in scores:
        confusion[s.expected_behavior][s.actual_behavior] += 1
    metrics = {}
    for b in BEHAVIORS:
        tp = confusion[b][b]
        predicted = sum(confusion[e][b] for e in BEHAVIORS)
        actual = sum(confusion[b].values())
        metrics[b] = ClassMetrics(
            precision=_ratio(tp, predicted), recall=_ratio(tp, actual), support=actual
        )
    check_counts: dict[str, list[bool]] = {}
    for s in scores:
        for name, ok in s.checks.items():
            key = "claim" if name.startswith("claim:") else name
            check_counts.setdefault(key, []).append(ok)
    latencies = [s.latency_s for s in scores if s.latency_s is not None]
    costs = [s.cost_usd for s in scores if s.cost_usd is not None]
    head = _acc(scores)

    # --- repeats-specific fields ---
    ci95: WilsonCI | None = None
    pass_at_k: float | None = None
    pass_hat_k: float | None = None
    per_item: dict[str, int] = {}

    n_total = len(scores)
    ci95 = wilson_ci95(int(head["correct"] or 0), n_total)

    if repeats > 1:
        # Group by question_id preserving insertion order
        item_correct: dict[str, list[bool]] = {}
        for s in scores:
            item_correct.setdefault(s.question_id, []).append(s.correct)
        per_item = {qid: sum(v) for qid, v in item_correct.items()}
        n_items = len(item_correct)
        pass_at_k = (
            sum(1 for v in item_correct.values() if any(v)) / n_items
            if n_items
            else None
        )
        pass_hat_k = (
            sum(1 for v in item_correct.values() if all(v)) / n_items
            if n_items
            else None
        )

    return RunSummary(
        n=len(scores),
        correct=int(head["correct"] or 0),
        accuracy=head["accuracy"],
        by_suite={
            suite: _acc([s for s in scores if s.suite == suite])
            for suite in sorted({s.suite for s in scores})
        },
        by_split={
            split: _acc([s for s in scores if s.split == split])
            for split in sorted({s.split for s in scores})
        },
        by_check={
            k: {"n": len(v), "passed": sum(v), "rate": _ratio(sum(v), len(v))}
            for k, v in sorted(check_counts.items())
        },
        behavior_confusion=confusion,
        behavior_metrics=metrics,
        error_categories=dict(
            Counter(s.error_category for s in scores if s.error_category).most_common()
        ),
        latency_p50_s=median(latencies) if latencies else None,
        latency_p95_s=_p95(latencies) if latencies else None,
        cost_usd=sum(costs) if costs else None,
        cost_per_question_usd=sum(costs) / len(costs) if costs else None,
        repeats=repeats if repeats > 1 else None,
        accuracy_ci95=ci95,
        pass_at_k=pass_at_k,
        pass_hat_k=pass_hat_k,
        per_item=per_item,
    )


def summary_markdown(
    summary: RunSummary,
    title: str,
    *,
    subset_info: SubsetInfo | None = None,
    repeats: int = 1,
) -> str:
    """A small Markdown report for a run."""

    def pct(v: float | int | None) -> str:
        return "—" if v is None else f"{100 * float(v):.1f}%"

    # Build the headline correct line
    if subset_info is not None:
        n_items = subset_info.n_subset
        if repeats > 1:
            # mean items correct per attempt, 1 decimal; denominator is item count
            mean_correct = summary.correct / repeats
            correct_str = f"{mean_correct:.1f}"
        else:
            correct_str = str(summary.correct)
        correct_line = (
            f"**{correct_str}/{n_items} on the {subset_info.preset} subset "
            f"({subset_info.n_subset} of {subset_info.n_slice} items in the slice)**"
        )
    else:
        correct_line = (
            f"**{summary.correct}/{summary.n} correct ({pct(summary.accuracy)})**"
        )

    lines = [
        f"### {title}",
        "",
        correct_line,
        "",
        "| Suite | n | Correct | Accuracy |",
        "| --- | ---: | ---: | ---: |",
    ]
    for suite, a in summary.by_suite.items():
        lines.append(f"| {suite} | {a['n']} | {a['correct']} | {pct(a['accuracy'])} |")
    lines += ["", "| Check | n | Passed | Rate |", "| --- | ---: | ---: | ---: |"]
    for check, a in summary.by_check.items():
        lines.append(f"| {check} | {a['n']} | {a['passed']} | {pct(a['rate'])} |")
    lines += [
        "",
        "| Behaviour | Precision | Recall | Support |",
        "| --- | ---: | ---: | ---: |",
    ]
    for b, m in summary.behavior_metrics.items():
        lines.append(f"| {b} | {pct(m.precision)} | {pct(m.recall)} | {m.support} |")
    if summary.error_categories:
        lines += ["", "| Error category | Count |", "| --- | ---: |"]
        lines += [f"| {k} | {v} |" for k, v in summary.error_categories.items()]
    if summary.latency_p50_s is not None:
        lines += [
            "",
            f"Latency p50 {summary.latency_p50_s:.2f} s, "
            f"p95 {summary.latency_p95_s:.2f} s.",
        ]
    if summary.cost_usd is not None:
        lines += [
            "",
            f"Model cost ${summary.cost_usd:.4f} "
            f"(${summary.cost_per_question_usd:.4f} per question).",
        ]

    # --- Repeats block (K > 1 only) ---
    if summary.repeats and summary.repeats > 1:
        ci = summary.accuracy_ci95
        ci_str = f" (95% CI {pct(ci.low)}–{pct(ci.high)})" if ci is not None else ""
        lines += [
            "",
            f"**Repeats** — {summary.repeats} runs per item: "
            f"mean {pct(summary.accuracy)}{ci_str}, "
            f"pass@K {pct(summary.pass_at_k)}, "
            f"pass^K {pct(summary.pass_hat_k)}",
        ]
        # Table of items not correct in every attempt
        partial = {qid: c for qid, c in summary.per_item.items() if c < summary.repeats}
        if partial:
            lines += [
                "",
                "| Item | Correct attempts |",
                "| --- | ---: |",
            ]
            for qid, c in sorted(partial.items()):
                lines.append(f"| {qid} | {c}/{summary.repeats} |")

    return "\n".join(lines) + "\n"
