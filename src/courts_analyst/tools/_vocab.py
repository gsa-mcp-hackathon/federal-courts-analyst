"""Tool-level vocabularies: ambiguous measure names the server asks about.

A model that doesn't know whether the user meant raw or weighted filings can
pass one of these instead of guessing; the tool then asks the user
(elicitation) or returns the choices (``needs_clarification``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from courts_analyst.core.enums import MEASURE_IDS, closed_str
from courts_analyst.core.measures import get_measure
from courts_analyst.core.results import Choice, Clarification


def _choice(measure_id: str, label: str | None = None) -> Choice:
    m = get_measure(measure_id)
    return Choice(value=m.id, label=label or m.label, description=m.definition)


AMBIGUOUS: dict[str, Clarification] = {
    "filings_per_judgeship": Clarification(
        parameter="measure",
        question="Which filings per judgeship: weighted or unweighted, total or "
        "civil only?",
        choices=[
            _choice("weighted_total_filings_per_judgeship"),
            _choice("total_filings_per_judgeship"),
            _choice("weighted_civil_filings_per_judgeship"),
            _choice("civil_filings_per_judgeship"),
        ],
        default="weighted_total_filings_per_judgeship",
    ),
    "civil_filings": Clarification(
        parameter="measure",
        question="Civil filings as a count of all civil cases, or per judgeship "
        "(weighted by case type, or unweighted)?",
        choices=[
            _choice("civil_cases_filed", "All civil cases filed (count, Table C-1)"),
            _choice("weighted_civil_filings_per_judgeship"),
            _choice("civil_filings_per_judgeship"),
        ],
        default="civil_cases_filed",
    ),
}

_MeasureOrAlias = closed_str(
    (*MEASURE_IDS, *AMBIGUOUS),
    "measure",
    "A published statistic. If the user didn't say whether they mean weighted or "
    "unweighted filings, pass 'filings_per_judgeship' (or 'civil_filings') and "
    "the server will ask them.",
)

if TYPE_CHECKING:
    MeasureOrAlias = str
else:
    MeasureOrAlias = _MeasureOrAlias
