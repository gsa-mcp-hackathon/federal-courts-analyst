"""MDL origin flags and the origin-13 validity break."""

from __future__ import annotations

from pathlib import Path

import duckdb

from tests.conftest import build_idb_from_zip
from tests.idb_rows import row, write_zip


def test_origin_13_before_july_2016_is_flagged(tmp_path: Path) -> None:
    rows = [
        row(DOCKET="1", ORIGIN="13", FILEDATE="06/30/2016", FDATEUSE="06/01/2016",
            TERMDATE="08/01/2016", TDATEUSE="08/01/2016", TAPEYEAR="2016"),
        row(DOCKET="2", ORIGIN="13", FILEDATE="07/01/2016", FDATEUSE="07/01/2016",
            TERMDATE="08/01/2016", TDATEUSE="08/01/2016", TAPEYEAR="2016"),
    ]  # fmt: skip
    b = build_idb_from_zip(write_zip(tmp_path / "in.zip", rows), tmp_path)
    con = duckdb.connect(str(b.db), read_only=True)
    got = con.execute(
        "SELECT docket, codes_outside_validity, is_mdl_direct_filed "
        "FROM idb_civil_record ORDER BY docket"
    ).fetchall()
    assert got == [("1", ["origin"], True), ("2", [], True)]
    # The registry says why.
    assert con.execute(
        "SELECT date::VARCHAR FROM data_breaks WHERE id = 'origin-13-mdl-direct'"
    ).fetchone() == ("2016-07-01",)
    assert con.execute(
        "SELECT field, code, valid_from::VARCHAR FROM code_validity"
    ).fetchall() == [("origin", "13", "2016-07-01")]


def test_direct_and_transferred_are_exclusive(
    idb_con: duckdb.DuckDBPyConnection,
) -> None:
    both, direct, transferred = (
        idb_con.execute(
            """SELECT count(*) FILTER (WHERE is_mdl_direct_filed AND is_mdl_transferred),
                  count(*) FILTER (WHERE is_mdl_direct_filed),
                  count(*) FILTER (WHERE is_mdl_transferred)
           FROM idb_civil_record"""
        ).fetchone()
        or ()
    )
    assert both == 0 and direct > 0 and transferred > 0
    assert idb_con.execute(
        """SELECT count(*) FROM idb_civil_record
           WHERE is_mdl_direct_filed <> (origin_code = '13')
              OR is_mdl_transferred <> (origin_code = '6')"""
    ).fetchone() == (0,)


def test_fixture_has_nd_fla_earplug_stratum(idb_con: duckdb.DuckDBPyConnection) -> None:
    n, docket = (
        idb_con.execute(
            """SELECT count(*), mode(mdl_docket) FROM idb_civil
           WHERE court = 'FL-N' AND filing_fy = 2020 AND is_mdl_direct_filed"""
        ).fetchone()
        or ()
    )
    assert n >= 150
    assert docket == "2885"  # In re 3M Combat Arms Earplug Products Liability
