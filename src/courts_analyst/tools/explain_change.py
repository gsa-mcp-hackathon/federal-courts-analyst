"""`explain_change`: why a measure changed between two fiscal years."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.enums import CourtCode
from courts_analyst.core.explain import ChangeExplanation, explain_change
from courts_analyst.core.results import Result, clarify
from courts_analyst.tools._common import READ_ONLY, ask, core_errors, get_db
from courts_analyst.tools._vocab import AMBIGUOUS, MeasureOrAlias

DESCRIPTION = """\
Use this when the user asks why a number went up or down, or what drove a \
change between two fiscal years: "Why did civil filings jump in FY2020?", \
"what drove the drop in terminations", "break the change down by district \
and case type". Works for civil cases filed, terminated and pending, and for \
filings per judgeship (weighted or unweighted).

Not for a single year's figure (use get_official_figure) or a ranking (use \
compare_courts).

Returns the official change (Table C-1 or X-1A), breakdowns by district and \
by case type that sum exactly to the change, the change excluding directly \
filed MDL cases (filings), and drivers, each labelled by what backs it: \
official, idb_derived, inferred (our reasoning, not an official statement: \
say so) or context. A plain "civil filings" means civil_cases_filed (the count); pass \
measure='civil_filings' only when the user asks about workload without saying \
count or per judgeship.

Example: measure='civil_cases_filed', court='US', period_from=2019, \
period_to=2020 → +172,704; N.D. Fla. +199,881, driven by directly filed MDL \
cases (MDL 2885, 3M earplugs)."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="explain_change",
        description=DESCRIPTION,
        annotations={"title": "Explain a change", **READ_ONLY},
    )
    @core_errors
    async def explain_change_tool(
        measure: Annotated[MeasureOrAlias, Field(description="The statistic.")],
        period_from: Annotated[
            int, Field(ge=2016, le=2025, description="Earlier fiscal year.")
        ],
        period_to: Annotated[
            int, Field(ge=2016, le=2025, description="Later fiscal year.")
        ],
        court: Annotated[
            CourtCode, Field(description="US, a circuit or a district.")
        ] = "US",
        ctx: Context | None = None,
    ) -> Result[ChangeExplanation] | mcp_types.InputRequiredResult:
        if measure in AMBIGUOUS:
            answer = await ask(ctx, AMBIGUOUS[measure])
            if isinstance(answer, mcp_types.InputRequiredResult):
                return answer
            if answer is None:
                return clarify(AMBIGUOUS[measure], ChangeExplanation)
            measure = answer
        return explain_change(get_db(), measure, court, period_from, period_to)
