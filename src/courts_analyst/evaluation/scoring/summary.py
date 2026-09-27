"""Aggregate item scores: accuracy by suite and split, behaviour confusion
matrix with precision/recall per class, error taxonomy, latency."""

from __future__ import annotations

from collections import Counter
from statistics import median

from pydantic import BaseModel, Field

from courts_analyst.evaluation.records import ItemScore

BEHAVIORS = ("answer", "clarify", "decline")


class ClassMetrics(BaseModel):
    precision: float | None
    recall: float | None
    support: int


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


def _acc(scores: list[ItemScore]) -> dict[str, float | int | None]:
    n = len(scores)
    c = sum(s.correct for s in scores)
    return {"n": n, "correct": c, "accuracy": c / n if n else None}


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def summarize(scores: list[ItemScore]) -> RunSummary:
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
    )


def summary_markdown(summary: RunSummary, title: str) -> str:
    """A small Markdown report for a run."""

    def pct(v: float | int | None) -> str:
        return "—" if v is None else f"{100 * float(v):.1f}%"

    lines = [
        f"### {title}",
        "",
        f"**{summary.correct}/{summary.n} correct ({pct(summary.accuracy)})**",
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
    return "\n".join(lines) + "\n"
