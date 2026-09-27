"""explain_change: the FY2020 storyline, on the fixtures and on full data."""

from __future__ import annotations

import pytest

from courts_analyst.core.db import Database
from courts_analyst.core.errors import InvalidCohortError, OutOfScopeError
from courts_analyst.core.explain import explain_change


def _drivers(x: object) -> dict[str, list[object]]:
    out: dict[str, list[object]] = {}
    for d in x.drivers:  # type: ignore[attr-defined]
        out.setdefault(d.code, []).append(d)
    return out


def test_fy2020_filings_on_fixture(core_db: Database) -> None:
    r = explain_change(core_db, "civil_cases_filed", "US", 2019, 2020)
    x = r.data
    assert x is not None and x.mode == "count"
    # Totals are official (Table C-1, first published each year).
    assert (x.official_from.value, x.official_from.edition) == (297877, "JB-2019")
    assert (x.official_to.value, x.official_to.edition) == (470581, "JB-2020")
    assert x.official_change == 172704
    assert r.provenance[0].source == "official_table"
    assert r.provenance[-1].source == "idb_derived"
    # The breakdown sums to the IDB change, and N.D. Fla. leads it.
    assert sum(c.change for c in x.by_district) == x.idb_change
    assert sum(c.change for c in x.by_case_type) == x.idb_change
    assert x.by_district[0].key == "FL-N" and x.by_district[0].key_contributor
    assert x.by_case_type[0].key == "Personal Injury/Product Liability"
    drivers = _drivers(x)
    mdl = drivers["mdl_direct_filed"][0]
    assert mdl.basis == "idb_derived" and "MDL 2885" in mdl.evidence
    assert drivers["pandemic_window"][0].basis == "context"
    assert "N.D. Fla." in x.headline


def test_weighted_fy2020_labels_revision_as_inference(core_db: Database) -> None:
    r = explain_change(
        core_db, "weighted_civil_filings_per_judgeship", "US", 2019, 2020
    )
    x = r.data
    assert x is not None and x.mode == "per_judgeship"
    assert x.filings_effect is not None and x.judgeship_effect is not None
    assert x.filings_effect + x.judgeship_effect == pytest.approx(
        x.official_to.value - x.official_from.value, abs=1.0
    )
    assert sum(c.change for c in x.by_district) == pytest.approx(x.filings_effect)
    assert x.by_district[0].key == "FL-N"
    drivers = _drivers(x)
    revisions = drivers["methodology_revision"]
    official = [d for d in revisions if d.basis == "official"]
    inferred = [d for d in revisions if d.basis == "inferred"]
    assert any("554" in d.evidence and "322" in d.evidence for d in official)
    assert len(inferred) == 1
    assert "N.D. Fla." in inferred[0].evidence and "Unconfirmed" in inferred[0].evidence
    assert "211 points" in inferred[0].evidence and "232 points" in inferred[0].evidence
    assert any(w.code == "inferred_not_official" for w in r.warnings)
    assert any(w.code == "revised_figure" for w in r.warnings)


def test_district_count_and_errors(core_db: Database) -> None:
    x = explain_change(core_db, "civil_cases_filed", "FL-N", 2019, 2020).data
    assert x is not None and x.by_district == [] and x.by_case_type
    with pytest.raises(InvalidCohortError):
        explain_change(core_db, "civil_cases_filed", "US", 2020, 2019)
    with pytest.raises(OutOfScopeError, match="decompose"):
        explain_change(core_db, "civil_median_months_to_disposition", "US", 2019, 2020)
    with pytest.raises(OutOfScopeError):
        explain_change(core_db, "civil_cases_filed", "US", 2010, 2020)


def test_without_idb_totals_still_come_back(tables_only_db: Database) -> None:
    r = explain_change(tables_only_db, "civil_cases_filed", "US", 2019, 2020)
    assert r.data is not None and r.data.official_change == 172704
    assert r.data.by_district == [] and r.data.idb_change is None
    assert any(w.code == "out_of_scope" for w in r.warnings)


def test_pending_revision_driver_text(core_db: Database) -> None:
    x = explain_change(core_db, "civil_cases_pending", "US", 2016, 2017).data
    assert x is not None
    rev = [d for d in x.drivers if d.code == "methodology_revision"]
    assert any("339,131" in d.evidence and "366,195" in d.evidence for d in rev)
    assert all("restates the prior year" in d.evidence for d in rev)


@pytest.mark.fulldata
def test_fy2020_storyline_full_data(full_db: Database) -> None:
    r = explain_change(full_db, "civil_cases_filed", "US", 2019, 2020)
    x = r.data
    assert x is not None
    assert x.idb_change is not None and abs(x.idb_change - x.official_change) < 1000
    top = x.by_district[0]
    assert top.key == "FL-N" and top.change > 190_000
    assert [c.key for c in x.by_district if c.key_contributor] == ["FL-N"]
    mdl = next(d for d in x.drivers if d.code == "mdl_direct_filed")
    assert mdl.magnitude is not None and mdl.magnitude > 150_000
    # Take out directly filed MDL cases and filings fell.
    assert x.idb_change_excluding_mdl_direct is not None
    assert x.idb_change_excluding_mdl_direct < 0


@pytest.mark.fulldata
def test_fy2024_terminations_full_data(full_db: Database) -> None:
    x = explain_change(full_db, "civil_cases_terminated", "US", 2023, 2024).data
    assert x is not None and x.official_change == 102958
    assert x.idb_change == x.official_change  # terminations match C-1 exactly
    assert x.by_district[0].key == "FL-N"
    assert any(d.code == "mdl_cases" for d in x.drivers)
