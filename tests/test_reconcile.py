"""reconcile: classification rules, the fixture build, full data, report."""

from __future__ import annotations

from pathlib import Path

import pytest

from courts_analyst.core.cohorts import CohortSpec, CohortStore, find_cases
from courts_analyst.core.db import Database
from courts_analyst.core.errors import OutOfScopeError
from courts_analyst.core.reconcile import (
    classify,
    reconcile_cohort,
    reconcile_figure,
    variance_rows,
)
from courts_analyst.pipeline.reports import render, write_variance_report


def test_within_tolerance_is_matched() -> None:
    assert classify("civil_cases_filed", 470581, 470332, []) == ("matched", [])
    assert classify("civil_cases_terminated", 396635, 396635, [])[0] == "matched"
    # Terminations get almost no slack.
    assert classify("civil_cases_terminated", 100_000, 99_900, [])[0] != "matched"


def test_restated_figure_explains() -> None:
    status, why = classify("civil_cases_pending", 339131, 363601, [366195.0, 339131.0])
    assert status == "matched" or status == "explained_variance"
    status, why = classify("civil_cases_pending", 366195, 339500, [339131.0])
    assert status == "explained_variance" and why[0].cause == "restated"


def test_repeat_records_explain_a_filings_shortfall() -> None:
    status, why = classify("civil_cases_filed", 10_000, 9_500, [], repeat_records=600)
    assert status == "explained_variance" and why[0].cause == "repeat_records"
    # Not when the IDB has *more* cases than the table.
    status, _ = classify("civil_cases_filed", 10_000, 10_500, [], repeat_records=600)
    assert status == "unexplained"


def test_undated_reopenings_explain_a_pending_shortfall() -> None:
    status, why = classify(
        "civil_cases_pending", 10_000, 9_000, [], undated_reopenings=950
    )
    assert status == "explained_variance" and why[0].cause == "undated_reopenings"


def test_snapshot_drift_and_unexplained() -> None:
    status, why = classify("civil_cases_filed", 10_000, 9_850, [])
    assert status == "explained_variance" and why[0].cause == "snapshot_drift"
    assert classify("civil_cases_filed", 10_000, 9_000, [])[0] == "unexplained"


def test_engineered_mismatch_is_unexplained() -> None:
    status, why = classify("civil_cases_terminated", 5_000, 4_000, [])
    assert status == "unexplained" and why == []


def test_reconcile_figure_on_fixture(core_db: Database) -> None:
    r = reconcile_figure(core_db, "civil_cases_terminated", "US", 2020)
    x = r.data
    assert x is not None
    assert x.official.value == 271256 and x.official.edition == "JB-2020"
    assert x.idb_value < 10_000  # the fixture is a 4,182-record sample
    assert x.status == "unexplained"
    assert x.badge.status == "unexplained" and r.provenance[0].reconciliation
    assert any(w.code == "inexact_match" for w in r.warnings)
    assert r.provenance[-1].source == "idb_derived"


def test_reconcile_errors(core_db: Database) -> None:
    with pytest.raises(OutOfScopeError, match="no IDB counterpart"):
        reconcile_figure(core_db, "weighted_civil_filings_per_judgeship", "US", 2020)
    with pytest.raises(OutOfScopeError):
        reconcile_figure(core_db, "civil_cases_filed", "US", 2010)


def test_reconcile_cohort(core_db: Database) -> None:
    store = CohortStore()
    pure = find_cases(
        core_db, store, CohortSpec(courts=["CIR-11"], fy_from=2020, fy_to=2020)
    ).data
    assert pure is not None
    r = reconcile_cohort(core_db, store, pure.handle).data
    assert r is not None and r.court == "CIR-11" and r.measure == "civil_cases_filed"
    filtered = find_cases(
        core_db,
        store,
        CohortSpec(courts=["FL-N"], fy_from=2020, fy_to=2020, nos_groups=["Antitrust"]),
    ).data
    assert filtered is not None
    with pytest.raises(OutOfScopeError, match="no published counterpart"):
        reconcile_cohort(core_db, store, filtered.handle)


def test_variance_report_renders(core_db: Database, tmp_path: Path) -> None:
    out = tmp_path / "variance.md"
    rows = write_variance_report(core_db, out, [2020, 2021])
    assert {r.fiscal_year for r in rows} == {2020, 2021}
    text = out.read_text()
    assert "## Summary" in text and "## National" in text and "## Unexplained" in text
    assert render(rows, "test").count("| Civil cases terminated |") >= 1


@pytest.mark.fulldata
def test_full_data_national_counts_all_match(full_db: Database) -> None:
    rows = variance_rows(full_db, list(range(2016, 2026)))
    national = [r for r in rows if r.court == "US"]
    assert len(national) == 30
    assert {r.status for r in national} == {"matched"}
    terminations = [r for r in rows if r.measure == "civil_cases_terminated"]
    assert {r.status for r in terminations} == {"matched"}
    unexplained = [r for r in rows if r.status == "unexplained"]
    assert len(unexplained) / len(rows) < 0.03


@pytest.mark.fulldata
def test_fy2017_pending_matches_the_restated_figure(full_db: Database) -> None:
    """Issue #11: the IDB's FY2017 pending count is close to the figure JB-2018
    restated (366,195), not the 339,131 first published in JB-2017."""
    x = reconcile_figure(full_db, "civil_cases_pending", "US", 2017).data
    assert x is not None
    assert x.official.edition == "JB-2018" and x.official.value == 366195
    assert x.status == "matched" and abs(x.variance_pct or 0) < 1
    wv = reconcile_figure(full_db, "civil_cases_pending", "WV-S", 2017).data
    assert wv is not None and wv.status == "matched"
