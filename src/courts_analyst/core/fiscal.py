"""Federal fiscal years.

The federal fiscal year runs October 1 to September 30 and is named for the
calendar year it ends in: FY2020 is 2019-10-01 through 2020-09-30. Every
official table in the catalog and every IDB cohort is keyed this way.

Pure domain logic: no I/O (ADR 0002). The IDB loader computes the same thing in
SQL (``year(d + INTERVAL 3 MONTH)``); a test keeps the two in step.
"""

from __future__ import annotations

from datetime import date


def fiscal_year(d: date) -> int:
    """Federal fiscal year that ``d`` falls in (October 1 starts the next FY)."""
    return d.year + 1 if d.month >= 10 else d.year


def fiscal_year_bounds(fy: int) -> tuple[date, date]:
    """First and last day of fiscal year ``fy``, inclusive."""
    return date(fy - 1, 10, 1), date(fy, 9, 30)
