"""explain_change: MDL driver from precomputed IDB counts when the IDB is not loaded."""

from __future__ import annotations

from courts_analyst.core.db import Database
from courts_analyst.core.explain import (
    ChangeExplanation,
    Driver,
    _load_mdl_cells,
    explain_change,
)

# ── CSV loader unit test ──────────────────────────────────────────────────────


def test_load_mdl_cells_basic() -> None:
    rows = _load_mdl_cells()
    # Non-empty
    assert len(rows) > 0
    # All rows have the expected columns
    for row in rows:
        assert set(row) >= {"rule", "court", "mdl_docket", "fiscal_year", "cases"}
    # rules are only the three expected values
    rules = {r["rule"] for r in rows}
    assert rules <= {"filed", "terminated", "pending"}
    # Spot-check: FL-N MDL 2885 filed FY2020 should be 202362
    fl_n_2885_2020 = next(
        (
            r
            for r in rows
            if r["rule"] == "filed"
            and r["court"] == "FL-N"
            and r["mdl_docket"] == "2885"
            and r["fiscal_year"] == "2020"
        ),
        None,
    )
    assert fl_n_2885_2020 is not None, "FL-N MDL 2885 filed FY2020 not found in CSV"
    assert int(fl_n_2885_2020["cases"]) == 202362


# ── Integration tests against the no-IDB fixture ─────────────────────────────


def _drivers(x: ChangeExplanation) -> dict[str, list[Driver]]:
    out: dict[str, list[Driver]] = {}
    for d in x.drivers:
        out.setdefault(d.code, []).append(d)
    return out


def test_us_civil_filed_2019_2020_no_idb_has_mdl_driver(
    tables_only_db: Database,
) -> None:
    """US civil_cases_filed 2019→2020 without IDB returns an MDL driver from CSV."""
    r = explain_change(tables_only_db, "civil_cases_filed", "US", 2019, 2020)
    x = r.data
    assert x is not None and x.mode == "count"
    drivers = _drivers(x)
    assert "mdl_direct_filed" in drivers, (
        "Expected 'mdl_direct_filed' driver but got: " + str(list(drivers))
    )
    mdl = drivers["mdl_direct_filed"][0]
    assert mdl.basis == "idb_derived"
    assert "MDL 2885" in mdl.evidence
    assert "3M" in mdl.evidence
    assert "precomputed" in mdl.evidence


def test_nj_civil_filed_2023_2024_no_idb_names_mdl_2738(
    tables_only_db: Database,
) -> None:
    """NJ civil_cases_filed 2023→2024 without IDB names MDL 2738 (J&J talcum powder)."""
    r = explain_change(tables_only_db, "civil_cases_filed", "NJ", 2023, 2024)
    x = r.data
    assert x is not None
    drivers = _drivers(x)
    assert "mdl_direct_filed" in drivers, (
        "Expected 'mdl_direct_filed' driver for NJ 2023→2024 but got: "
        + str(list(drivers))
    )
    mdl = drivers["mdl_direct_filed"][0]
    assert "2738" in mdl.evidence
