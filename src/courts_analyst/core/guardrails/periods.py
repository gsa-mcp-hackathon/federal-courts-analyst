"""Reporting periods: fiscal years, statistical years, and periods we don't hold.

The catalog holds fiscal-year tables (12 months ending September 30) and, in
the national JFF rows for 1990, a statistical year (12 months ending June 30).
A question about any other 12-month period gets a factual ``out_of_scope``
answer from the server, with the nearest fiscal year and how much of the
period it covers, so a model never has to improvise facts about periods.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from courts_analyst.core.errors import OutOfScopeError
from courts_analyst.core.provenance import Period
from courts_analyst.core.results import Caveat

PeriodEnding = Literal["september_30", "june_30", "march_31", "december_31"]
PERIOD_ENDINGS: tuple[PeriodEnding, ...] = (
    "september_30",
    "june_30",
    "march_31",
    "december_31",
)
_END_MONTH = {"september_30": 9, "june_30": 6, "march_31": 3, "december_31": 12}
_END_DAY = {9: 30, 6: 30, 3: 31, 12: 31}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")  # fmt: skip


def _months(end_year: int, end_month: int) -> set[tuple[int, int]]:
    """The 12 (year, month) pairs of the period ending in that month."""
    out = set()
    y, m = end_year, end_month
    for _ in range(12):
        out.add((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def overlap_months(end_year: int, end_month: int, fiscal_year: int) -> int:
    """How many months a 12-month period shares with a fiscal year."""
    return len(_months(end_year, end_month) & _months(fiscal_year, 9))


def period_label(end_year: int, end_month: int) -> str:
    month = _MONTHS[end_month - 1]
    return f"the 12 months ending {month} {_END_DAY[end_month]}, {end_year}"


def check_period(
    period_ending: PeriodEnding, year: int, printed: Iterable[Period]
) -> None:
    """Raise ``out_of_scope`` unless the catalog holds this period.

    ``printed`` are the periods the catalog has for the figure and year: a
    June 30 request is answerable when the year's row is a statistical year.
    """
    if period_ending == "september_30":
        return
    month = _END_MONTH[period_ending]
    if month == 6 and any(p.period_type == "statistical_year" for p in printed):
        return
    near = sorted(
        (fy for fy in (year - 1, year, year + 1)),
        key=lambda fy: -overlap_months(year, month, fy),
    )
    best = overlap_months(year, month, near[0])
    tied = [fy for fy in near if overlap_months(year, month, fy) == best]
    nearest = " or ".join(
        f"FY{fy} (October 1, {fy - 1} to September 30, {fy})" for fy in sorted(tied)
    )
    raise OutOfScopeError(
        f"This server holds fiscal-year figures (the 12 months ending September 30) "
        f"and, for 1990 only, national statistical-year rows (ending June 30). It has "
        f"no tables for {period_label(year, month)}. uscourts.gov publishes tables "
        "for other 12-month periods (March 31, June 30, December 31), but they "
        f"aren't loaded here. The nearest fiscal year is {nearest}, which shares "
        f"{best} of those 12 months; say so if you use it.",
        [f"get_official_figure with fiscal_year={tied[-1]} (a different period)"],
    )


def period_caveats(periods: Iterable[Period | None]) -> list[Caveat]:
    """A ``period_mismatch`` caution when statistical and fiscal years mix."""
    kinds = {p.period_type for p in periods if p is not None}
    if len(kinds) < 2:
        return []
    return [
        Caveat(
            code="period_mismatch",
            message="This result compares a statistical year (12 months ending June "
            "30) with fiscal years (12 months ending September 30); the periods "
            "don't line up, so say so when comparing them.",
        )
    ]
