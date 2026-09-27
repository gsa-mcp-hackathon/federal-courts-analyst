"""`reconcile`: does the IDB reproduce a published count?"""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.enums import CourtCode
from courts_analyst.core.errors import InvalidCohortError
from courts_analyst.core.reconcile import (
    Reconciliation,
    reconcile_cohort,
    reconcile_figure,
)
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db, get_store

DESCRIPTION = """\
Use this when the user asks whether case-level data matches the official \
tables, or how far an IDB count is from the published one: civil cases \
filed, terminated or pending for a court and fiscal year (Table C-1), or a \
find_cases handle that corresponds to one (courts, one year, no filters).

Not for the official figure itself (get_official_figure) or for explaining a \
change over time (explain_change).

Returns the official value (latest edition, with every edition), the IDB \
rebuild, the variance and a badge: matched, explained_variance (with the \
quantified cause: a restated figure, repeat records, undated reopenings or \
snapshot drift) or unexplained.

Example: measure='civil_cases_pending', court='US', fiscal_year=2017 → \
official 366,195 (JB-2018, restated from 339,131), IDB 363,601, matched."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="reconcile",
        description=DESCRIPTION,
        annotations={"title": "Reconcile IDB vs official", **READ_ONLY},
    )
    @core_errors
    async def reconcile_tool(
        measure: Annotated[
            Literal[
                "civil_cases_filed", "civil_cases_terminated", "civil_cases_pending"
            ]
            | None,
            Field(description="The count to rebuild (with court and fiscal_year)."),
        ] = None,
        court: CourtCode = "US",
        fiscal_year: Annotated[int | None, Field(ge=2016, le=2025)] = None,
        handle: Annotated[
            str | None,
            Field(
                pattern=r"^coh_[0-9a-f]{12}$",
                description="Or: a find_cases handle to reconcile instead.",
            ),
        ] = None,
    ) -> Result[Reconciliation]:
        if handle:
            return reconcile_cohort(get_db(), get_store(), handle)
        if measure is None or fiscal_year is None:
            raise InvalidCohortError(
                "Give either handle, or measure and fiscal_year (and court).",
                ["reconcile(measure='civil_cases_filed', fiscal_year=2024)"],
            )
        return reconcile_figure(get_db(), measure, court, fiscal_year)
