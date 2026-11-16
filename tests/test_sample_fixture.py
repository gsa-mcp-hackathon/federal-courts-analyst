"""The committed IDB sample: deterministic, stratified, synthetic names."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import duckdb

from courts_analyst.pipeline.idb.sample import build_sample
from tests.conftest import IDB_SAMPLE_ZIP, IdbBuild


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_sampling_is_deterministic(tmp_path: Path) -> None:
    """Sampling the sample twice gives byte-identical zips."""
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    na = build_sample(
        IDB_SAMPLE_ZIP, "cv88on.txt", a, tmp_path, fy_from=2015, fy_to=2025
    )
    nb = build_sample(
        IDB_SAMPLE_ZIP, "cv88on.txt", b, tmp_path, fy_from=2015, fy_to=2025
    )
    assert na == nb > 1000
    assert _sha(a) == _sha(b)
    with zipfile.ZipFile(a) as zf:
        (info,) = zf.infolist()
        assert info.filename == "cv88on.txt" and info.date_time == (2026, 1, 1, 0, 0, 0)
        first = zf.read("cv88on.txt").split(b"\r\n")[1]
    assert b"PLAINTIFF 000001" in first


def test_committed_sample_shape(
    idb: IdbBuild, idb_con: duckdb.DuckDBPyConnection
) -> None:
    assert 3000 <= idb.stats.rows <= 6000
    assert IDB_SAMPLE_ZIP.stat().st_size < 500_000
    districts, fys, pending, discontinued = (
        idb_con.execute(
            """SELECT count(DISTINCT court),
                  count(DISTINCT termination_fy),
                  count(*) FILTER (WHERE status_code = 'S'),
                  count(*) FILTER (WHERE nos_code IN ('444', '610', '620', '650', '730'))
           FROM idb_civil_record"""
        ).fetchone()
        or ()
    )
    assert districts == 94
    assert fys == 12  # FY2015–FY2026 (partial)
    assert pending >= 150
    assert discontinued >= 1
    # Cases just outside the window were sampled and then dropped by the scope.
    assert idb.stats.rows > idb.result.counts["idb_civil_record"]


def test_every_nos_code_in_scope_is_sampled(idb_con: duckdb.DuckDBPyConnection) -> None:
    n = idb_con.execute(
        "SELECT count(DISTINCT nos_code) FROM idb_civil_record"
    ).fetchone()
    assert n is not None and n[0] >= 95
