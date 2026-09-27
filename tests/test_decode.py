"""Decoding raw IDB records: labels, missing values, unknown codes, derived columns."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest

from courts_analyst.pipeline.idb.load import PolicyError
from tests.conftest import build_idb_from_zip
from tests.idb_rows import pending, row, write_zip


def _build(tmp_path: Path, rows: list[str]) -> duckdb.DuckDBPyConnection:
    z = write_zip(tmp_path / "in.zip", rows)
    b = build_idb_from_zip(z, tmp_path)
    return duckdb.connect(str(b.db), read_only=True)


def _one(con: duckdb.DuckDBPyConnection, where: str = "TRUE") -> dict[str, Any]:
    cur = con.execute(f"SELECT * FROM idb_civil_record WHERE {where}")
    names = [d[0] for d in cur.description]
    rows = cur.fetchall()
    assert len(rows) == 1, rows
    return dict(zip(names, rows[0], strict=True))


def test_known_row_decodes(tmp_path: Path) -> None:
    con = _build(
        tmp_path,
        [
            row(
                CIRCUIT="11",
                DISTRICT="29",
                ORIGIN="13",
                NOS="365",
                JURIS="4",
                MDLDOCK="2885",
                FILEDATE="04/16/2020",
                FDATEUSE="04/01/2020",
                TERMDATE="08/08/2024",
                TDATEUSE="08/01/2024",
                PROCPROG="1",
                DISP="12",
                JURY="P",
                PROSE="1",
                IFP="FP",
                TAPEYEAR="2024",
            )
        ],
    )
    r = _one(con)
    assert r["court"] == "FL-N" and r["circuit"] == "CIR-11"
    assert r["origin"].startswith("Multidistrict litigation originating")
    assert r["is_mdl_direct_filed"] and not r["is_mdl_transferred"]
    assert r["nos"] == "Personal injury product liability"
    assert r["nos_group"] == "Personal Injury/Product Liability"
    assert r["nos_category"] == "Tort Actions"
    assert r["jurisdiction"] == "Diversity of citizenship"
    assert r["jurisdiction_group"] == "private"
    assert r["disposition"] == "Dismissed voluntarily"
    assert r["disposition_group"] == "dismissed"
    assert r["procedural_stage"] == "before_issue_joined"
    assert r["jury_demand"] == "Plaintiff"
    assert r["pro_se"] == "Pro se plaintiff(s) only"
    assert r["is_ifp"] and r["fee_status"] == "In forma pauperis"
    assert r["status"] == "Terminated"
    assert r["mdl_docket"] == "2885"
    assert r["filing_fy"] == 2020 and r["termination_fy"] == 2024
    assert r["days_to_disposition"] == (date(2024, 8, 8) - date(2020, 4, 16)).days
    assert r["codes_outside_validity"] == []


def test_missing_values_are_null_not_unknown(tmp_path: Path) -> None:
    con = _build(tmp_path, [row(JURY="-8", CLASSACT="-8", JUDGMENT="0")])
    r = _one(con)
    assert r["jury_demand"] is None and r["jury_demand_code"] is None
    assert r["class_action_alleged"] is None and not r["is_class_action"]
    assert r["judgment_for"] is None  # 0 is listed as missing in the codebook
    assert r["fee_status"] == "Not in forma pauperis"  # -8 is a real IFP value
    assert r["mdl_docket"] is None


def test_unknown_codes_are_kept_and_counted(tmp_path: Path) -> None:
    con = _build(tmp_path, [row(NOS="999", DISP="77"), row(DOCKET="2000002")])
    r = _one(con, "nos_code = '999'")
    assert r["nos"] == "UNKNOWN(999)" and r["nos_group"] is None
    assert r["disposition"] == "UNKNOWN(77)"
    assert con.execute("SELECT count(*) FROM idb_civil_record").fetchone() == (2,)
    unknown = con.execute(
        "SELECT col, code, records FROM idb_unknown_code ORDER BY col"
    ).fetchall()
    assert unknown == [("DISP", "77", 1), ("NOS", "999", 1)]


def test_pending_record(tmp_path: Path) -> None:
    con = _build(tmp_path, [pending()])
    r = _one(con)
    assert r["status_code"] == "S" and r["status"] == "Pending"
    assert r["termination_fy"] is None and r["days_to_disposition"] is None
    assert r["disposition"] is None and r["procedural_progress"] is None
    assert con.execute("SELECT count(*) FROM idb_civil_terminations").fetchone() == (0,)


def test_populated_judge_codes_stop_the_build(tmp_path: Path) -> None:
    with pytest.raises(PolicyError, match="judge"):
        _build(tmp_path, [row(TERMJUDG="0123")])


def test_consistency_warnings(tmp_path: Path) -> None:
    z = write_zip(
        tmp_path / "in.zip",
        [row(TAPEYEAR="2021"), pending(TAPEYEAR="2020", DOCKET="2000002")],
    )
    b = build_idb_from_zip(z, tmp_path)
    text = " ".join(b.result.warnings)
    assert "tape year isn't their termination fiscal year" in text
    assert "pending records with a termination date or tape year" in text


def test_court_checks_warn_on_unmapped_district(tmp_path: Path) -> None:
    z = write_zip(tmp_path / "in.zip", [row(DISTRICT="99")])
    b = build_idb_from_zip(z, tmp_path)
    assert any("no court" in w for w in b.result.warnings)
    assert b.result.unknown_codes == {"DISTRICT": {"99": 1}}


def test_circuit_mismatch_warns(tmp_path: Path) -> None:
    z = write_zip(tmp_path / "in.zip", [row(CIRCUIT="2")])  # Maine is 1st Cir.
    b = build_idb_from_zip(z, tmp_path)
    assert any("disagree with the registry" in w for w in b.result.warnings)
