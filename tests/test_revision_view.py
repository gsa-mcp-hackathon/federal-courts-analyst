"""Revision view and log: first publication, later revisions, display precision."""

from __future__ import annotations

import duckdb


def test_fy2020_weighted_civil_revision(con: duckdb.DuckDBPyConnection) -> None:
    rows = con.execute(
        """
        SELECT edition, ROUND(value), first_published, revised, delta
        FROM revision
        WHERE measure_id = 'weighted_civil_filings_per_judgeship'
          AND court = 'US' AND fiscal_year = 2020
        ORDER BY pub_order
        """
    ).fetchall()
    assert rows[0] == ("JB-2020", 554, True, False, None)
    by_edition = {r[0]: r for r in rows}
    # JFF repeated 554 until the 2023 edition, which printed 322.
    for ed in ("JFF-2020", "JFF-2021", "JFF-2022"):
        assert by_edition[ed][1:4] == (554, False, False)
    assert by_edition["JFF-2023"][1:5] == (322, False, True, -232)
    assert by_edition["JFF-2025"][1] == 322


def test_revision_log_entry(con: duckdb.DuckDBPyConnection) -> None:
    row = con.execute(
        """
        SELECT first_edition, ROUND(first_value), latest_edition, ROUND(latest_value),
               delta, n_revisions
        FROM revision_log
        WHERE measure_id = 'weighted_civil_filings_per_judgeship'
          AND court = 'US' AND fiscal_year = 2020
        """
    ).fetchone()
    assert row == ("JB-2020", 554, "JFF-2025", 322, -232, 1)


def test_judgeship_and_unweighted_revisions(con: duckdb.DuckDBPyConnection) -> None:
    """673→674 judgeships and 676→675 unweighted civil, both in JFF-2023."""
    got = dict(
        con.execute(
            """
            SELECT measure_id, delta FROM revision
            WHERE court = 'US' AND fiscal_year = 2020 AND edition = 'JFF-2023'
              AND measure_id IN ('authorized_judgeships', 'civil_filings_per_judgeship')
            """
        ).fetchall()
    )
    assert got == {"authorized_judgeships": 1, "civil_filings_per_judgeship": -1}


def test_every_recent_year_revised_down(con: duckdb.DuckDBPyConnection) -> None:
    """The weighted civil series was lowered for FY2019-FY2025 (the revision log's story)."""
    deltas = dict(
        con.execute(
            """
            SELECT fiscal_year, delta FROM revision_log
            WHERE measure_id = 'weighted_civil_filings_per_judgeship' AND court = 'US'
              AND fiscal_year BETWEEN 2019 AND 2025
            """
        ).fetchall()
    )
    assert set(deltas) >= {2019, 2020, 2021, 2022, 2023, 2024, 2025}
    assert all(d < 0 for d in deltas.values())


def test_display_precision_is_not_a_revision(con: duckdb.DuckDBPyConnection) -> None:
    """553.95 in the JB-2020 workbook and 554 in JFF-2020 are the same printed figure."""
    row = con.execute(
        """
        SELECT value, revised FROM revision
        WHERE measure_id = 'weighted_civil_filings_per_judgeship' AND court = 'US'
          AND fiscal_year = 2020 AND edition IN ('JB-2020', 'JFF-2020')
        ORDER BY pub_order
        """
    ).fetchall()
    assert row[0][0] != row[1][0]  # different stored precision…
    assert row[1][1] is False  # …but not a revision


def test_prior_year_pending_lines_up(con: duckdb.DuckDBPyConnection) -> None:
    """C-1 (pre-2023 layout) reprints last year's closing pending count."""
    rows = con.execute(
        """
        SELECT edition, value FROM revision
        WHERE measure_id = 'civil_cases_pending' AND court = 'US' AND fiscal_year = 2019
        ORDER BY pub_order
        """
    ).fetchall()
    assert [r[0] for r in rows][:2] == ["JB-2019", "JB-2020"]


def test_first_published_is_unique(con: duckdb.DuckDBPyConnection) -> None:
    dupes = con.execute(
        """
        SELECT measure_id, court, fiscal_year, COUNT(*) FROM revision
        WHERE first_published GROUP BY ALL HAVING COUNT(*) > 1
        """
    ).fetchall()
    assert dupes == []


def test_editions_ordered_jb_before_jff(con: duckdb.DuckDBPyConnection) -> None:
    order = [
        r[0]
        for r in con.execute(
            "SELECT edition FROM edition WHERE year(period_end) = 2020 ORDER BY pub_order"
        ).fetchall()
    ]
    assert order == ["JB-2020", "JFF-2020"]
