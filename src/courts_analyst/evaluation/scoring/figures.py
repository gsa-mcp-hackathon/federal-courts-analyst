"""Find the figures an answer reports and the edition each is attributed to.

Structured citations (:attr:`AnswerRecord.cited_figures`) come first. Prose is
the fallback, read by :mod:`courts_analyst.core.figures_text` (shared with
the request desk's verification gate).
"""

from __future__ import annotations

from courts_analyst.core.figures_text import WINDOW, find_editions
from courts_analyst.core.figures_text import figures_in_text as _figures_in_text
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure

__all__ = ["WINDOW", "figures_in_text", "find_editions", "reported_figures"]


def figures_in_text(text: str) -> list[ReportedFigure]:
    """Numbers in prose, each with its nearest edition (or None)."""
    return [
        ReportedFigure(value=f.value, edition=f.edition) for f in _figures_in_text(text)
    ]


def reported_figures(record: AnswerRecord) -> list[ReportedFigure]:
    """Declared citations plus figures found in the final text."""
    return [*record.cited_figures, *figures_in_text(record.final_text)]
