"""Records vs cases: repeat terminations, sequencing, scope."""

from __future__ import annotations

from pathlib import Path

import duckdb

from tests.conftest import IdbBuild, build_idb_from_zip
from tests.idb_rows import pending, row, write_zip

REOPENED = [
    # Same case key; terminated in FY2016, reopened and terminated in FY2018.
    row(
        FILEDATE="03/02/2015",
        FDATEUSE="03/01/2015",
        TERMDATE="05/05/2016",
        TDATEUSE="05/01/2016",
        TAPEYEAR="2016",
        DISP="18",
    ),
    row(
        FILEDATE="03/02/2015",
        FDATEUSE="03/01/2015",
        TERMDATE="11/20/2017",
        TDATEUSE="11/01/2017",
        TAPEYEAR="2018",
        DISP="13",
    ),
]


def _con(tmp_path: Path, rows: list[str]) -> duckdb.DuckDBPyConnection:
    b = build_idb_from_zip(write_zip(tmp_path / "in.zip", rows), tmp_path)
    return duckdb.connect(str(b.db), read_only=True)


def test_repeat_terminations_collapse_to_one_case(tmp_path: Path) -> None:
    con = _con(tmp_path, REOPENED)
    recs = con.execute(
        """SELECT record_seq, n_records, is_latest, is_repeat_record, termination_fy,
                  disposition_code, prev_termination_date_ao::VARCHAR
           FROM idb_civil_record ORDER BY record_seq"""
    ).fetchall()
    assert recs == [
        (1, 2, False, False, 2016, "18", None),
        (2, 2, True, True, 2018, "13", "2016-05-01"),
    ]
    # One case (for filings), two terminations (for terminations).
    assert con.execute(
        "SELECT count(*), max(disposition_code) FROM idb_civil"
    ).fetchone() == (1, "13")
    assert con.execute(
        "SELECT list(termination_fy ORDER BY termination_fy) FROM idb_civil_terminations"
    ).fetchone() == ([2016, 2018],)
    ids = [
        r[0]
        for r in con.execute(
            "SELECT record_id FROM idb_civil_record ORDER BY 1"
        ).fetchall()
    ]
    assert ids == ["00-1-2000001-20150302#1", "00-1-2000001-20150302#2"]


def test_sequence_counts_records_outside_the_window(tmp_path: Path) -> None:
    before = row(
        FILEDATE="03/02/2012",
        FDATEUSE="03/01/2012",
        TERMDATE="05/05/2013",
        TDATEUSE="05/01/2013",
        TAPEYEAR="2013",
    )
    after = row(
        FILEDATE="03/02/2012",
        FDATEUSE="03/01/2012",
        TERMDATE="05/05/2019",
        TDATEUSE="05/01/2019",
        TAPEYEAR="2019",
    )
    con = _con(tmp_path, [before, after])
    # Only the FY2019 record is in scope, but it's still the case's 2nd record.
    assert con.execute(
        "SELECT record_seq, n_records, prev_termination_date_ao::VARCHAR FROM idb_civil_record"
    ).fetchall() == [(2, 2, "2013-05-01")]


def test_scope_window(tmp_path: Path) -> None:
    rows = [
        row(DOCKET="1", FILEDATE="01/02/2014", FDATEUSE="01/01/2014",
            TERMDATE="09/15/2014", TDATEUSE="09/01/2014", TAPEYEAR="2014"),  # ended FY2014
        row(DOCKET="2", FILEDATE="01/02/2014", FDATEUSE="01/01/2014",
            TERMDATE="10/15/2014", TDATEUSE="10/01/2014", TAPEYEAR="2015"),  # ended FY2015
        pending(DOCKET="3", FILEDATE="09/29/2025", FDATEUSE="09/01/2025"),  # filed FY2025
        pending(DOCKET="4", FILEDATE="10/02/2025", FDATEUSE="10/01/2025"),  # filed FY2026
        pending(DOCKET="5", FILEDATE="06/02/2001", FDATEUSE="06/01/2001"),  # old, pending
    ]  # fmt: skip
    con = _con(tmp_path, rows)
    got = [
        r[0]
        for r in con.execute(
            "SELECT docket FROM idb_civil_record ORDER BY 1"
        ).fetchall()
    ]
    assert got == ["2", "3", "5"]
    assert con.execute("SELECT release_rows FROM idb_release").fetchone() == (5,)


def test_fixture_counts(idb: IdbBuild, idb_con: duckdb.DuckDBPyConnection) -> None:
    n_rec, n_keys, n_cases, n_term, n_l = (
        idb_con.execute(
            """SELECT (SELECT count(*) FROM idb_civil_record),
                  (SELECT count(DISTINCT case_key) FROM idb_civil_record),
                  (SELECT count(*) FROM idb_civil),
                  (SELECT count(*) FROM idb_civil_terminations),
                  (SELECT count(*) FROM idb_civil_record WHERE status_code = 'L')"""
        ).fetchone()
        or ()
    )
    assert n_cases == n_keys < n_rec
    assert n_term == n_l
    # The sample includes reopened cases on purpose.
    assert (
        idb_con.execute(
            "SELECT count(*) FROM idb_civil_record WHERE is_repeat_record"
        ).fetchone()[0]
        >= 50
    )  # type: ignore[index]
    assert idb.result.counts["idb_civil"] == n_cases
