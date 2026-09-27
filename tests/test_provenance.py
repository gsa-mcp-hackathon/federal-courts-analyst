"""Every result carries provenance; revised figures carry first_published."""

from __future__ import annotations

from datetime import date

import pytest

from courts_analyst.core.db import Database
from courts_analyst.core.official import OfficialFigure, get_official_figure
from courts_analyst.core.provenance import Period, Provenance
from courts_analyst.core.results import Caveat, Choice, Clarification, clarify, ok


def test_ok_requires_provenance(core_db: Database) -> None:
    fig = get_official_figure(core_db, "civil_cases_filed", "US", 2020).data
    assert fig is not None
    with pytest.raises(ValueError, match="without provenance"):
        ok(fig, [])


def test_clarify_envelope() -> None:
    c = Clarification(
        parameter="measure",
        question="Raw or weighted?",
        choices=[Choice(value="a", label="A"), Choice(value="b", label="B")],
        default="a",
    )
    r = clarify(c)
    assert r.status == "needs_clarification" and r.data is None
    assert r.clarification == c and r.provenance == []


def test_caveat_schema_title() -> None:
    assert Caveat.model_json_schema()["title"] == "Warning"


def test_period_kinds() -> None:
    assert Period.for_end(1990, date(1990, 6, 30)).period_type == "statistical_year"
    assert Period.for_end(2020, date(2020, 9, 30)).period_type == "fiscal_year"
    assert Period.fiscal(2020).period_end == date(2020, 9, 30)


@pytest.mark.parametrize(
    ("measure", "court", "fy"),
    [("weighted_civil_filings_per_judgeship", "US", fy) for fy in range(2019, 2026)]
    + [("civil_cases_pending", "US", 2017), ("authorized_judgeships", "US", 2020)],
)
def test_revised_figures_carry_first_published(
    core_db: Database, measure: str, court: str, fy: int
) -> None:
    r = get_official_figure(core_db, measure, court, fy)
    f: OfficialFigure | None = r.data
    assert f is not None and f.revision_status == "revised"
    p: Provenance = r.provenance[0]
    assert p.first_published is not None and p.later_revisions
    assert p.first_published.edition.startswith("JB-")
    assert p.revision_status == "revised" and p.period is not None
