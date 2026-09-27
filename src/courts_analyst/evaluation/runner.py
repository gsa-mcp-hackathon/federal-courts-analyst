"""Run an answerer over a slice of the bank and write the results.

Output, per run, in ``eval/results/``:

- ``<run_id>.jsonl``: one line per item: the answer record and its score
- ``<run_id>.summary.json``: :class:`~.scoring.summary.RunSummary` plus run metadata
- ``<run_id>.md``: the same summary as a Markdown table
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
from courts_analyst.evaluation.scoring.summary import summary_markdown

DEFAULT_RESULTS = ROOT / "eval" / "results"


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
) -> RunResult:
    """Answer and score ``items``; write JSONL, summary JSON and Markdown.

    ``workers`` > 1 answers several items at once (for slow answerers such as
    a model); results keep the items' order.
    """
    run_id = run_id or make_run_id(answerer.name, label)
    results_dir.mkdir(parents=True, exist_ok=True)
    records, scores = [], []
    jsonl = results_dir / f"{run_id}.jsonl"
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            answered = list(pool.map(lambda i: _safe_answer(answerer, i), items))
    else:
        answered = None
    with jsonl.open("w") as fh:
        for n, item in enumerate(items):
            record = answered[n] if answered else _safe_answer(answerer, item)
            score = score_item(item, record)
            records.append(record)
            scores.append(score)
            fh.write(
                json.dumps(
                    {
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
    summary = summarize(scores)
    meta = {
        "run_id": run_id,
        "answerer": answerer.name,
        "label": label,
        "items": [i.id for i in items],
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    summary_path = results_dir / f"{run_id}.summary.json"
    summary_path.write_text(
        json.dumps({**meta, "summary": summary.model_dump(mode="json")}, indent=2)
        + "\n"
    )
    md_path = results_dir / f"{run_id}.md"
    md_path.write_text(summary_markdown(summary, f"{answerer.name} · {label}"))
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
    skipped."""
    by_id = {i.id: i for i in items}
    records = []
    for line in source.read_text().splitlines():
        rec = AnswerRecord.model_validate(json.loads(line)["record"])
        if rec.question_id in by_id:
            records.append(rec)
    if not records:
        raise ValueError(f"no records in {source} match the bank")
    replay = {r.question_id: r for r in records}

    class _Replay:
        name = records[0].answerer

        def answer(self, item: QuestionItem) -> AnswerRecord:
            return replay[item.id]

    base = source.name.removesuffix(".jsonl")
    return run(
        _Replay(),
        [by_id[r.question_id] for r in records],
        label=f"rescored:{base}",
        results_dir=results_dir,
        run_id=run_id or f"{base}-rescored",
    )
