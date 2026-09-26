"""Full-data checks against the real downloaded tables (`make data-tables` first)."""

from __future__ import annotations

import duckdb
import pytest

from courts_analyst.config import settings
from courts_analyst.core.courts import COURTS, TERRITORIAL, CourtLevel
from courts_analyst.pipeline.tables.manifest import load_manifest

from .conftest import MANIFEST_PATH

pytestmark = pytest.mark.fulldata


@pytest.fixture(scope="module")
def full() -> duckdb.DuckDBPyConnection:
    path = settings.resolved_duckdb_path
    if not path.is_file():
        pytest.skip("run `make data-tables` first")
    return duckdb.connect(str(path), read_only=True)


def test_every_manifest_table_has_observations(full: duckdb.DuckDBPyConnection) -> None:
    parsed = {
        r[0]
        for r in full.execute("SELECT DISTINCT file_id FROM observation").fetchall()
    }
    for t in load_manifest(MANIFEST_PATH).tables:
        assert t.file_id(t.primary_format) in parsed, t.edition


def test_no_district_missing(full: duckdb.DuckDBPyConnection) -> None:
    districts = {c.code for c in COURTS.values() if c.level is CourtLevel.DISTRICT}
    for table, expected in [
        ("X-1A", districts - TERRITORIAL),
        ("C-1", districts),
        ("C-5", districts),
    ]:
        rows = full.execute(
            "SELECT edition, list(DISTINCT court) FROM observation WHERE table_code = ? GROUP BY 1",
            [table],
        ).fetchall()
        assert len(rows) == 10, table
        for edition, courts in rows:
            missing = expected - set(courts)
            assert not missing, f"{table} {edition} missing {sorted(missing)}"


def test_every_pdf_cross_check_ran_and_agreed(full: duckdb.DuckDBPyConnection) -> None:
    both = sum(len(t.files) == 2 for t in load_manifest(MANIFEST_PATH).tables)
    checked = full.execute(
        "SELECT COUNT(DISTINCT edition || table_code) FROM format_check"
    ).fetchone()
    assert checked == (both,)
    assert full.execute(
        "SELECT COUNT(*) FROM format_check WHERE NOT agrees"
    ).fetchone() == (0,)
