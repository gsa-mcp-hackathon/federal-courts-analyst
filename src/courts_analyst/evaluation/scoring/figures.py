"""Find the figures an answer reports and the edition each is attributed to.

Structured citations (:attr:`AnswerRecord.cited_figures`) come first. Prose is
the fallback, read by :mod:`courts_analyst.core.figures_text` (shared with
the request desk's verification gate).
"""

from __future__ import annotations

import re

from courts_analyst.core.figures_text import WINDOW, find_editions
from courts_analyst.core.figures_text import figures_in_text as _figures_in_text
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure

__all__ = [
    "WINDOW",
    "figures_in_text",
    "find_editions",
    "plain_digit_groups",
    "reported_figures",
]

_GROUP_SPACE = re.compile(r"(?<=\d)[  ](?=\d{3}(?!\d))")
"""A narrow no-break space (U+202F) or thin space (U+2009) between digit
groups, as in "297 877": a thousands separator, not a gap between two
numbers. The wxO agent writes counts this way."""


def plain_digit_groups(text: str) -> str:
    """Write typographic thousands separators as commas, one character for
    one, so text positions don't move."""
    return _GROUP_SPACE.sub(",", text)


def figures_in_text(text: str) -> list[ReportedFigure]:
    """Numbers in prose, each with its nearest edition (or None)."""
    return [
        ReportedFigure(value=f.value, edition=f.edition)
        for f in _figures_in_text(plain_digit_groups(text))
    ]


def reported_figures(record: AnswerRecord) -> list[ReportedFigure]:
    """Declared citations plus figures found in the final text."""
    return [*record.cited_figures, *figures_in_text(record.final_text)]
