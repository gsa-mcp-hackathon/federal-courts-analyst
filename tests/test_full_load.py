"""Full civil IDB checks (``@fulldata``: needs ``make data-idb``).

Run with ``make test-full``. They check the real build against the official
tables it was not derived from.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from courts_analyst.config import settings

pytestmark = pytest.mark.fulldata

GOLDEN = Path(__file__).parent / "golden" / "idb_checks.yaml"


@pytest.fixture(scope="module")
def full() -> Iterator[duckdb.DuckDBPyConnection]:
    db = settings.resolved_idb_path
    if not db.is_file():
        pytest.skip("run `make data-idb` first")
    con = duckdb.connect(str(db), read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return yaml.safe_load(GOLDEN.read_text())


def test_rows_per_fy_in_expected_range(full: duckdb.DuckDBPyConnection) -> None:
    rows = dict(
        full.execute(
            "SELECT filing_fy, count(*) FROM idb_civil WHERE filing_fy BETWEEN 2015 AND 2025 GROUP BY 1"
        ).fetchall()
    )
    assert sorted(rows) == list(range(2015, 2026))
    for fy, n in rows.items():
        assert 250_000 <= n <= 500_000, (fy, n)


def test_unknown_code_rate_below_half_percent(full: duckdb.DuckDBPyConnection) -> None:
    total = full.execute("SELECT count(*) FROM idb_civil_record").fetchone()[0]  # type: ignore[index]
    per_col = full.execute(
        "SELECT col, sum(records) FROM idb_unknown_code GROUP BY 1"
    ).fetchall()
    for col, n in per_col:
        assert n / total < 0.005, (col, n)


def test_terminations_match_c1_exactly(
    full: duckdb.DuckDBPyConnection, golden: dict[str, Any]
) -> None:
    """Every terminated record counted = the official JB C-1 total, FY2016–FY2025."""
    for fy, official in golden["c1_terminations"].items():
        got = full.execute(
            "SELECT count(*) FROM idb_civil_terminations WHERE termination_fy = ?", [fy]
        ).fetchone()
        assert got == (official,), fy


def test_filings_within_half_percent_of_c1(
    full: duckdb.DuckDBPyConnection, golden: dict[str, Any]
) -> None:
    for fy, official in golden["c1_filings"].items():
        got = full.execute(
            "SELECT count(*) FROM idb_civil WHERE filing_fy = ?", [fy]
        ).fetchone()[0]  # type: ignore[index]
        assert abs(got - official) / official < 0.005, (fy, got, official)


def test_nos_groups_match_c2_fy2024(
    full: duckdb.DuckDBPyConnection, golden: dict[str, Any]
) -> None:
    got = dict(
        full.execute(
            "SELECT nos_group, count(*) FROM idb_civil WHERE filing_fy = 2024 GROUP BY 1"
        ).fetchall()
    )
    got.update(
        full.execute(
            "SELECT nos_category, count(*) FROM idb_civil WHERE filing_fy = 2024 GROUP BY 1"
        ).fetchall()
    )
    for group, official in golden["c2_fy2024"].items():
        tol = max(0.01 * official, 25)
        assert abs(got.get(group, 0) - official) <= tol, (
            group,
            got.get(group),
            official,
        )


def test_nd_fla_surge(full: duckdb.DuckDBPyConnection) -> None:
    """FY2020 N.D. Fla. direct-filed MDL filings exceed 200,000 (the concept's claim)."""
    n = full.execute(
        """SELECT count(*) FROM idb_civil
           WHERE court = 'FL-N' AND filing_fy = 2020 AND is_mdl_direct_filed"""
    ).fetchone()[0]  # type: ignore[index]
    assert n > 200_000


def test_no_origin_13_before_valid_date(full: duckdb.DuckDBPyConnection) -> None:
    assert full.execute(
        "SELECT count(*) FROM idb_civil_record WHERE len(codes_outside_validity) > 0"
    ).fetchone() == (0,)
