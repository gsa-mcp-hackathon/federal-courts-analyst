"""`analyze_cohort`: medians, outcome rates, trends for a cohort handle."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.cohorts import CohortAnalysis, GroupBy, Metric, analyze_cohort
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db, get_store

DESCRIPTION = """\
Use this after find_cases, to compute a statistic for its cohort handle: \
count, trend (by fiscal year), median_days_to_disposition, disposition_rates \
(dismissed / judgment / transferred), judgment_for_rates, share_by_nos_group, \
pro_se_share or still_pending_share, optionally grouped by court, \
fiscal_year, nos_group or origin.

Not for published statistics (get_official_figure) or whole-court changes \
(explain_change); it needs a handle from find_cases.

Returns one value per group with n (cases it's computed over) and a 95% \
confidence interval (Wilson for shares, order statistics for medians). \
Groups under 30 cases carry a caution; under 10 the value is withheld: say \
there are too few cases rather than guessing. Report n with every figure.

Example: handle from find_cases(courts=['DE'], fy_from=2019, fy_to=2019, \
nos_codes=['830']), metric='median_days_to_disposition' → 166 days \
(95% CI 154–183), n=845."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="analyze_cohort",
        description=DESCRIPTION,
        annotations={"title": "Analyze a cohort", **READ_ONLY},
    )
    @core_errors
    async def analyze_cohort_tool(
        handle: Annotated[
            str,
            Field(pattern=r"^coh_[0-9a-f]{12}$", description="From find_cases."),
        ],
        metric: Metric,
        group_by: Annotated[
            GroupBy | None, Field(description="Optional grouping (≤ 25 groups).")
        ] = None,
    ) -> Result[CohortAnalysis]:
        return analyze_cohort(get_db(), get_store(), handle, metric, group_by)
