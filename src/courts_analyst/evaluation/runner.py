"""Run an answerer over a slice of the bank and write the results.

Output, per run, in ``eval/results/``:

- ``<run_id>.jsonl``: one line per item: the answer record and its score
- ``<run_id>.summary.json``: :class:`~.scoring.summary.RunSummary` plus run metadata
- ``<run_id>.md``: the same summary as a Markdown table

When ``repeats`` > 1 each item is answered K times.  Every JSONL line gains a
``repeat`` field (0-based index).  Items with the same ``question_id`` are kept
in repeat order.  ``--workers`` parallelises over all item × repeat pairs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from courts_analyst.evaluation.answerers import Answerer
from courts_analyst.evaluation.bank import ROOT
from courts_analyst.evaluation.records import AnswerRecord, ItemScore
from courts_analyst.evaluation.schema import QuestionItem
from courts_analyst.evaluation.scoring import RunSummary, score_item, summarize
from courts_analyst.evaluation.scoring.summary import SubsetInfo, summary_markdown

DEFAULT_RESULTS = ROOT / "eval" / "results"


def _git_head() -> str | None:
    """Return the current git HEAD SHA of the repo, or None if git fails."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


@dataclass
class RunResult:
    run_id: str
    records: list[AnswerRecord]
    scores: list[ItemScore]
    summary: RunSummary
    paths: dict[str, Path]


def make_run_id(answerer: str, label: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{answerer}-{label}"


def _safe_answer(answerer: Answerer, item: QuestionItem) -> AnswerRecord:
    start = time.perf_counter()
    try:
        record = answerer.answer(item)
    except Exception as exc:  # one bad item mustn't stop a run
        record = AnswerRecord(
            question_id=item.id,
            answerer=answerer.name,
            error=f"{type(exc).__name__}: {exc}",
        )
    if record.latency_s is None:
        record.latency_s = time.perf_counter() - start
    return record


def run(
    answerer: Answerer,
    items: list[QuestionItem],
    label: str = "all",
    results_dir: Path = DEFAULT_RESULTS,
    run_id: str | None = None,
    progress: Callable[[QuestionItem, ItemScore], None] | None = None,
    workers: int = 1,
    repeats: int = 1,
    subset_info: SubsetInfo | None = None,
    provenance: dict[str, object] | None = None,
    split: str | None = None,
) -> RunResult:
    """Answer and score ``items``; write JSONL, summary JSON and Markdown.

    ``workers`` > 1 answers several items at once (for slow answerers such as
    a model); results keep the items' order.

    ``repeats`` > 1 answers every item K times.  Parallelism (when
    ``workers`` > 1) is over all item × repeat pairs.

    ``subset_info`` is written into the summary JSON ``meta`` when provided
    (set by ``--agent-tools``).
    """
    run_id = run_id or make_run_id(answerer.name, label)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Build the flat list of (item, repeat_index) pairs in repeat-major order:
    # (item0, 0), (item1, 0), ..., (item0, 1), (item1, 1), ...
    # This keeps all first-attempts together in output order, matching the
    # original single-repeat behaviour exactly when repeats == 1.
    pairs: list[tuple[QuestionItem, int]] = [
        (item, r) for r in range(repeats) for item in items
    ]

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            answered = list(pool.map(lambda p: _safe_answer(answerer, p[0]), pairs))
    else:
        answered = None

    records: list[AnswerRecord] = []
    scores: list[ItemScore] = []
    jsonl = results_dir / f"{run_id}.jsonl"
    with jsonl.open("w") as fh:
        for n, (item, repeat_idx) in enumerate(pairs):
            record = answered[n] if answered else _safe_answer(answerer, item)
            score = score_item(item, record)
            records.append(record)
            scores.append(score)
            fh.write(
                json.dumps(
                    {
                        "repeat": repeat_idx,
                        "question": item.question,
                        "record": record.model_dump(mode="json"),
                        "score": score.model_dump(mode="json"),
                    }
                )
                + "\n"
            )
            fh.flush()
            if progress:
                progress(item, score)

    summary = summarize(scores, repeats=repeats)

    # --- preview rule check ---
    from courts_analyst.evaluation.preview_check import (
        PreviewResult,
        check_events,
        events_from_record,
    )

    preview_confirms = 0
    preview_violations = 0
    for n, (item, _) in enumerate(pairs):
        record = records[n]
        evs = events_from_record(item.question, record)
        pr: PreviewResult = check_events(evs)
        preview_confirms += pr.confirm_calls
        preview_violations += len(pr.violations)

    run_date = datetime.now(UTC).isoformat(timespec="seconds")
    meta: dict[str, object] = {
        "run_id": run_id,
        "answerer": answerer.name,
        "label": label,
        "repeats": repeats,
        "items": [i.id for i in items],
        "finished_at": run_date,
        "preview_rule": {
            "confirm_calls": preview_confirms,
            "violations": preview_violations,
        },
    }
    if subset_info is not None:
        meta["subset"] = subset_info.model_dump(mode="json")
    if provenance is not None:
        bank_commit: str | None = _git_head()
        meta["provenance"] = {
            **provenance,
            "bank_commit": bank_commit,
            "split": split,
            "repeats": repeats,
            "run_date": run_date,
        }
    summary_path = results_dir / f"{run_id}.summary.json"
    summary_path.write_text(
        json.dumps({**meta, "summary": summary.model_dump(mode="json")}, indent=2)
        + "\n"
    )
    md_path = results_dir / f"{run_id}.md"
    # Provenance dict written into the markdown is the enriched version (with
    # bank_commit etc.) if provenance was provided, else None.
    md_provenance: dict[str, object] | None = meta.get("provenance")  # type: ignore[assignment]
    md_path.write_text(
        summary_markdown(
            summary,
            f"{answerer.name} · {label}",
            subset_info=subset_info,
            repeats=repeats,
            preview_confirms=preview_confirms,
            preview_violations=preview_violations,
            provenance=md_provenance,
        )
    )
    return RunResult(
        run_id=run_id,
        records=records,
        scores=scores,
        summary=summary,
        paths={"jsonl": jsonl, "summary": summary_path, "markdown": md_path},
    )


def rescore(
    source: Path,
    items: list[QuestionItem],
    results_dir: Path = DEFAULT_RESULTS,
    run_id: str | None = None,
) -> RunResult:
    """Score the answer records of a past run again with the current bank and
    scorer, without re-asking the answerer. Items no longer in the bank are
    skipped.

    Handles repeated runs: records sharing a ``question_id`` are replayed in
    their original order (all repeats) and the repeat count is inferred from
    the JSONL.
    """
    by_id = {i.id: i for i in items}

    # Parse lines preserving repeat index (default 0 for old single-attempt files)
    parsed: list[tuple[int, AnswerRecord]] = []
    for line in source.read_text().splitlines():
        obj = json.loads(line)
        rec = AnswerRecord.model_validate(obj["record"])
        if rec.question_id in by_id:
            repeat_idx: int = obj.get("repeat", 0)
            parsed.append((repeat_idx, rec))

    if not parsed:
        raise ValueError(f"no records in {source} match the bank")

    # Infer repeats K from the maximum repeat index seen
    inferred_repeats = max(idx for idx, _ in parsed) + 1

    # Build replay map: question_id → list of (idx, record) in repeat order
    replay_lists: dict[str, list[tuple[int, AnswerRecord]]] = {}
    for idx, rec in parsed:
        replay_lists.setdefault(rec.question_id, []).append((idx, rec))
    # Sort each list by repeat index, then drop the index
    replay_ordered: dict[str, list[AnswerRecord]] = {
        qid: [r for _, r in sorted(pairs, key=lambda p: p[0])]
        for qid, pairs in replay_lists.items()
    }

    # Unique items in the order they first appear
    seen: dict[str, QuestionItem] = {}
    for _, rec in parsed:
        if rec.question_id not in seen:
            seen[rec.question_id] = by_id[rec.question_id]
    unique_items = list(seen.values())

    # Replay answerer: tracks how many times each item has been called
    counters: dict[str, int] = {}

    class _Replay:
        name = parsed[0][1].answerer

        def answer(self, item: QuestionItem) -> AnswerRecord:
            n = counters.get(item.id, 0)
            counters[item.id] = n + 1
            recs = replay_ordered[item.id]
            return recs[n] if n < len(recs) else recs[-1]

    base = source.name.removesuffix(".jsonl")
    return run(
        _Replay(),
        unique_items,
        label=f"rescored:{base}",
        results_dir=results_dir,
        run_id=run_id or f"{base}-rescored",
        repeats=inferred_repeats,
    )
