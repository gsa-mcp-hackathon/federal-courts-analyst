"""Federal fiscal years: Python and the loader's SQL agree on every date."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.core.fiscal import fiscal_year, fiscal_year_bounds
from courts_analyst.pipeline.idb.load import SQL_FY

dates = st.dates(min_value=date(1970, 1, 1), max_value=date(2100, 12, 31))


def test_boundaries() -> None:
    assert fiscal_year(date(2019, 9, 30)) == 2019
    assert fiscal_year(date(2019, 10, 1)) == 2020
    assert fiscal_year(date(2020, 1, 1)) == 2020
    assert fiscal_year(date(2020, 9, 30)) == 2020
    assert fiscal_year_bounds(2020) == (date(2019, 10, 1), date(2020, 9, 30))


@given(dates)
def test_october_first_starts_a_new_year(d: date) -> None:
    fy = fiscal_year(d)
    start, end = fiscal_year_bounds(fy)
    assert start <= d <= end
    assert fiscal_year(start - timedelta(days=1)) == fy - 1
    assert fiscal_year(end + timedelta(days=1)) == fy + 1


@given(st.lists(dates, min_size=1, max_size=50))
def test_sql_matches_python(ds: list[date]) -> None:
    con = duckdb.connect()
    sql = SQL_FY.format(d="d")
    got = con.execute(f"SELECT {sql} FROM unnest(?::DATE[]) t(d)", [ds]).fetchall()
    assert [r[0] for r in got] == [fiscal_year(d) for d in ds]
