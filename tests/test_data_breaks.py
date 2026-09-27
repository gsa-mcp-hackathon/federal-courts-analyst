"""Data-break cautions: windows crossing the July 2016 origin-code change
(origin 13, directly filed MDL) are flagged; windows after it aren't."""

from __future__ import annotations

import pytest

from courts_analyst.core.cohorts import CohortSpec, CohortStore, find_cases
from courts_analyst.core.db import Database
from courts_analyst.core.explain import explain_change

BREAK = "origin-13-mdl-direct"


def _break_warnings(warnings: list) -> list[str]:  # type: ignore[type-arg]
    return [
        w.message for w in warnings if w.code == "data_break" and BREAK in w.message
    ]


@pytest.mark.parametrize(
    ("fy_from", "fy_to", "flagged"),
    [(2015, 2016, True), (2016, 2016, True), (2016, 2018, True), (2017, 2018, False),
     (2020, 2025, False)],
)  # fmt: skip
def test_mdl_cohort_across_the_break(
    core_db: Database, store: CohortStore, fy_from: int, fy_to: int, flagged: bool
) -> None:
    spec = CohortSpec(fy_from=fy_from, fy_to=fy_to, origins=["mdl_direct"])
    r = find_cases(core_db, store, spec)
    hits = _break_warnings(r.warnings)
    assert bool(hits) is flagged
    if flagged:
        assert "July 1, 2016" in hits[0]
        assert all(
            w.severity == "caution" for w in r.warnings if w.code == "data_break"
        )


def test_non_mdl_cohort_not_flagged(core_db: Database, store: CohortStore) -> None:
    r = find_cases(core_db, store, CohortSpec(fy_from=2015, fy_to=2016))
    assert not _break_warnings(r.warnings)


def test_explain_change_across_the_break(core_db: Database) -> None:
    across = explain_change(core_db, "civil_cases_filed", "US", 2016, 2017)
    assert any(
        d.code == "data_break" and BREAK in d.evidence for d in across.data.drivers
    )  # type: ignore[union-attr]
    assert _break_warnings(across.warnings)
    after = explain_change(core_db, "civil_cases_filed", "US", 2017, 2018)
    assert not any(BREAK in d.evidence for d in after.data.drivers)  # type: ignore[union-attr]
    assert not _break_warnings(after.warnings)
