"""`judgeship_context`: weighted caseload against published thresholds."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.enums import CourtCode
from courts_analyst.core.judgeships import JudgeshipContext, judgeship_context
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db

DESCRIPTION = """\
Use this when the user asks how a district's workload compares with the \
Judicial Conference's standards for new judgeships, or whether the \
Conference recommended judgeships for it: "Is E.D. Tex. above the 430 \
threshold?", "judgeship context for E.D.N.C.".

Not for rankings (compare_courts) or for the raw figure alone \
(get_official_figure).

Returns the court's official weighted filings per judgeship (Table X-1A), \
weighted civil filings and authorized judgeships from the same edition, the \
national figure, the 430 and 600 thresholds with their sources, the \
Conference's 2025 recommendation for the court if any, and a neutral \
summary. The server never recommends judgeships itself and can't say \
whether a court has a judicial emergency (that needs vacancy data): don't \
imply either. Asked whether a court should get judgeships, give these facts \
and the Conference's recommendation, say it's a decision for Congress, and \
don't argue either side.

Example: court='TX-E', fiscal_year=2025 → 894 weighted filings per judgeship \
(JB-2025), above 430 and 600; the Conference recommended 2 more judgeships."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="judgeship_context",
        description=DESCRIPTION,
        annotations={"title": "Judgeship context", **READ_ONLY},
    )
    @core_errors
    async def judgeship_context_tool(
        court: Annotated[CourtCode, Field(description="A district, or US.")],
        fiscal_year: Annotated[
            int | None, Field(ge=2016, le=2025, description="Default: latest.")
        ] = None,
    ) -> Result[JudgeshipContext]:
        return judgeship_context(get_db(), court, fiscal_year)
