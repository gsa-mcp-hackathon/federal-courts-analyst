"""judgeship_context: thresholds and recommendations come from sourced data;
the server never recommends."""

from __future__ import annotations

import re

import pytest

from courts_analyst.core.courts import COURTS
from courts_analyst.core.db import Database
from courts_analyst.core.errors import NotPublishedError, OutOfScopeError
from courts_analyst.core.judgeships import judgeship_context, reference


def test_reference_data_is_sourced() -> None:
    ref = reference()
    ids = {t["id"]: t for t in ref["thresholds"]}
    assert ids["new_judgeship_standard"]["value"] == 430
    assert ids["judicial_emergency_vacancy_600"]["value"] == 600
    for t in ref["thresholds"]:
        assert t["source"] and t["url"].startswith("https://")
    rec = ref["recommendations"][0]
    assert rec["url"].startswith("https://www.uscourts.gov/")
    assert len(rec["sha256"]) == 64
    assert set(rec["districts"]) <= set(COURTS)
    # The 2025 table: 69 district judgeships across 25 districts.
    assert len(rec["districts"]) == 25
    assert sum(v[1] for v in rec["districts"].values()) == 69


def test_context_for_a_recommended_district(core_db: Database) -> None:
    r = judgeship_context(core_db, "TX-E", 2025)
    c = r.data
    assert c is not None
    assert c.weighted_total.edition == "JB-2025" and c.weighted_total.value == 894
    assert [t.above for t in c.thresholds] == [True, True]
    assert c.recommendation is not None and c.recommendation.recommended_additional == 2
    assert c.national_weighted_total is not None
    assert c.authorized_judgeships is not None
    assert "makes no recommendation" in c.statement
    assert any(p.edition == "JC-2025" for p in r.provenance)


def test_below_threshold_district(core_db: Database) -> None:
    c = judgeship_context(core_db, "WY", 2025).data
    assert c is not None and not any(t.above for t in c.thresholds)
    assert c.recommendation is None and "below the 430 standard" in c.statement


def test_national_mentions_revision(core_db: Database) -> None:
    c = judgeship_context(core_db, "US", 2025).data
    assert c is not None and "later revised" in c.statement


@pytest.mark.parametrize("court", ["TX-E", "FL-N", "NY-S", "WY", "US", "NC-E"])
def test_never_recommends(core_db: Database, court: str) -> None:
    statement = judgeship_context(core_db, court, 2024).data.statement  # type: ignore[union-attr]
    assert not re.search(r"\b(should|needs? (?:more|new)|we recommend|deserves)\b",
                         statement, re.I)  # fmt: skip


def test_errors(core_db: Database) -> None:
    with pytest.raises(NotPublishedError, match="territorial"):
        judgeship_context(core_db, "GU")
    with pytest.raises(OutOfScopeError):
        judgeship_context(core_db, "CIR-05")


def test_default_year_is_latest(core_db: Database) -> None:
    c = judgeship_context(core_db, "NJ").data
    assert c is not None and c.fiscal_year == 2025
