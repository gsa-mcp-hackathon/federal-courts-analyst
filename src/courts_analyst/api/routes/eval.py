"""Committed eval runs (``eval/results``), for the web app's eval page."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from courts_analyst.api.common import cached_json
from courts_analyst.config import settings

router = APIRouter(tags=["eval"])

RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _summaries(root: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted(root.glob("*.summary.json")):
        try:
            s = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        summ = s.get("summary", {})
        out.append(
            {
                "run_id": s.get("run_id", path.name.removesuffix(".summary.json")),
                "answerer": s.get("answerer"),
                "label": s.get("label"),
                "finished_at": s.get("finished_at"),
                "n": summ.get("n"),
                "correct": summ.get("correct"),
                "accuracy": summ.get("accuracy"),
            }
        )
    return out


@router.get("/eval/runs", summary="Every committed eval run, with its headline score")
async def runs(request: Request) -> Response:
    return cached_json(request, {"runs": _summaries(settings.eval_results_dir)})


@router.get("/eval/runs/{run_id}", summary="One run: summary and per-question scores")
async def run(request: Request, run_id: str) -> Response:
    if not RUN_ID.fullmatch(run_id) or ".." in run_id:
        return JSONResponse({"error": "invalid_run_id"}, status_code=422)
    root = settings.eval_results_dir
    summary_path = root / f"{run_id}.summary.json"
    if not summary_path.is_file():
        return JSONResponse(
            {"error": "not_found", "message": f"No run {run_id!r}."}, status_code=404
        )
    summary = json.loads(summary_path.read_text())
    items = []
    records = root / f"{run_id}.jsonl"
    if records.is_file():
        for line in records.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            score = row.get("score") or {}
            rec = row.get("record") or {}
            items.append(
                {
                    "question_id": score.get("question_id"),
                    "question": row.get("question"),
                    "suite": score.get("suite"),
                    "split": score.get("split"),
                    "correct": score.get("correct"),
                    "error_category": score.get("error_category"),
                    "latency_s": score.get("latency_s"),
                    "tools_called": [c.get("name") for c in rec.get("tool_calls", [])],
                }
            )
    return cached_json(request, {"summary": summary, "items": items})
