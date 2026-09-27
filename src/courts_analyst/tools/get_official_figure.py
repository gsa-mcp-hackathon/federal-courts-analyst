"""`get_official_figure`: one published statistic, with its edition history."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.enums import CourtCode, EditionSelector
from courts_analyst.core.official import OfficialFigure, get_official_figure
from courts_analyst.core.results import Result, clarify
from courts_analyst.tools._common import READ_ONLY, ask, core_errors, get_db
from courts_analyst.tools._vocab import AMBIGUOUS, MeasureOrAlias

DESCRIPTION = """\
Use this when the user asks for a single published statistic: one measure, \
one court (or the nation), one fiscal year. For example weighted civil \
filings per judgeship nationally in FY2020, civil cases pending in S.D.N.Y. in \
FY2023, or the national median time to disposition.

Not for rankings across courts (use compare_courts), for why a number changed \
between years (use explain_change), or for counts with filters such as case \
type (use find_cases).

Returns the value in the latest edition by default, the first-published \
value, every edition that printed it and, when editions disagree \
(revision_status 'revised'), revision_notes on why. Always name the edition \
and say when a figure was revised, even if asked for one number; relay an \
'inferred' note as inference. Warnings flag statistical years (1990 ends \
June 30). A plain "civil filings" means civil_cases_filed; pass \
'filings_per_judgeship' only when the user didn't say weighted or unweighted.

Example: measure='weighted_civil_filings_per_judgeship', court='US', \
fiscal_year=2020 → 322 (JFF-2025), first published as 554 (JB-2020)."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="get_official_figure",
        description=DESCRIPTION,
        annotations={"title": "Get an official figure", **READ_ONLY},
    )
    @core_errors
    async def get_official_figure_tool(
        measure: Annotated[MeasureOrAlias, Field(description="The statistic.")],
        fiscal_year: Annotated[
            int,
            Field(ge=1990, le=2030, description="Fiscal year (ends September 30)."),
        ],
        court: Annotated[
            CourtCode, Field(description="US for all district courts, or a court.")
        ] = "US",
        edition: Annotated[
            EditionSelector,
            Field(
                description="'latest' (default), 'first_published' or an edition id."
            ),
        ] = "latest",
        ctx: Context | None = None,
    ) -> Result[OfficialFigure] | mcp_types.InputRequiredResult:
        if measure in AMBIGUOUS:
            answer = await ask(ctx, AMBIGUOUS[measure])
            if isinstance(answer, mcp_types.InputRequiredResult):
                return answer
            if answer is None:
                return clarify(AMBIGUOUS[measure], OfficialFigure)
            measure = answer
        return get_official_figure(get_db(), measure, court, fiscal_year, edition)
