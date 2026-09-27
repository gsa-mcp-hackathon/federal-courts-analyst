"""Periods: requests for 12-month periods the catalog doesn't hold get a
factual answer from the server; statistical and fiscal years are flagged."""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from courts_analyst.core.db import Database
from courts_analyst.core.errors import OutOfScopeError
from courts_analyst.core.guardrails.periods import overlap_months, period_caveats
from courts_analyst.core.official import get_official_figure
from courts_analyst.core.provenance import Period


@pytest.mark.parametrize(
    ("year", "month", "fy", "months"),
    [(2020, 6, 2020, 9), (2020, 6, 2019, 3), (2023, 12, 2023, 9), (2023, 12, 2024, 3),
     (2021, 3, 2021, 6), (2021, 3, 2020, 6), (2020, 9, 2020, 12)],
)  # fmt: skip
def test_overlap(year: int, month: int, fy: int, months: int) -> None:
    assert overlap_months(year, month, fy) == months


def test_june_2020_is_out_of_scope_with_facts(core_db: Database) -> None:
    with pytest.raises(OutOfScopeError) as exc:
        get_official_figure(
            core_db, "civil_cases_filed", "US", 2020, period_ending="june_30"
        )
    msg = exc.value.message
    assert "June 30, 2020" in msg and "September 30" in msg
    assert "FY2020 (October 1, 2019 to September 30, 2020)" in msg and "9 of" in msg


def test_march_period_names_both_nearest_years(core_db: Database) -> None:
    with pytest.raises(OutOfScopeError, match=r"FY2020 .* or FY2021"):
        get_official_figure(
            core_db, "civil_cases_filed", "US", 2021, period_ending="march_31"
        )


def test_june_1990_is_the_statistical_year(core_db: Database) -> None:
    r = get_official_figure(
        core_db, "civil_filings_per_judgeship", "US", 1990, period_ending="june_30"
    )
    assert r.data is not None and r.data.period.period_type == "statistical_year"
    assert "statistical year ending June 30, 1990" in r.data.citation


def test_mismatch_caveat() -> None:
    from datetime import date

    stat = Period.for_end(1990, date(1990, 6, 30))
    assert period_caveats([stat, Period.fiscal(2020)])[0].code == "period_mismatch"
    assert period_caveats([Period.fiscal(2019), Period.fiscal(2020)]) == []


async def test_period_ending_over_mcp(tools: Client) -> None:
    with pytest.raises(ToolError, match=r"\[out_of_scope\].*June 30, 2020"):
        await tools.call_tool(
            "get_official_figure",
            {
                "measure": "civil_cases_filed",
                "fiscal_year": 2020,
                "period_ending": "june_30",
            },
        )
