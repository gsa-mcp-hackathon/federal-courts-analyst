"""The ``engine`` answerer: our analytics core answering the engine suite.

Each engine item names a count (civil cases filed, terminated or pending), a
court and a fiscal year. The answerer rebuilds it from the IDB with
``core.reconcile`` and reports the IDB value; the scorer compares it with the
official figure the item expects.
"""

from __future__ import annotations

import time

from courts_analyst.config import settings
from courts_analyst.core.db import Database
from courts_analyst.core.reconcile import reconcile_figure
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure, ToolCall
from courts_analyst.evaluation.schema import QuestionItem


class EngineAnswerer:
    """Answers ``engine`` items from the core; declines anything else."""

    name = "engine"

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database(
            settings.resolved_duckdb_path, settings.resolved_idb_path
        )

    def answer(self, item: QuestionItem) -> AnswerRecord:
        q = item.expected.engine
        if q is None:
            return AnswerRecord(
                question_id=item.id,
                answerer=self.name,
                error="the engine answerer only answers engine items",
            )
        start = time.perf_counter()
        result = reconcile_figure(self.db, q.measure, q.court, q.fiscal_year)
        assert result.data is not None
        rec = result.data
        return AnswerRecord(
            question_id=item.id,
            answerer=self.name,
            final_text=(
                f"IDB rebuild {rec.idb_value:,} vs official {rec.official.value:,.0f} "
                f"({rec.official.edition}): {rec.status}."
            ),
            tool_calls=[
                ToolCall(
                    name="reconcile",
                    arguments=q.model_dump(),
                    output=result.model_dump(mode="json"),
                    latency_s=time.perf_counter() - start,
                )
            ],
            cited_figures=[ReportedFigure(value=rec.idb_value, measure=q.measure)],
            behavior="answer",
            latency_s=time.perf_counter() - start,
        )
