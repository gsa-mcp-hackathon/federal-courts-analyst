"""`check_inquiry_eligibility`: can this figure's revision go to the
statistics office? (ADR 0013)"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import Eligibility
from courts_analyst.core.desk.service import inquiry_eligibility
from courts_analyst.core.enums import CourtCode, MeasureId
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db

DESCRIPTION = """\
Use this before offering "Ask the statistics office why this changed": it \
says whether a figure was revised between editions with no published \
explanation, which is the only kind of question the office gets.

Not for the figure itself or its edition history (use get_official_figure), \
or for filing the question (use keep_answer with option 'ask_office').

Returns eligible true or false, why, and the revision (first and latest \
edition and value). Read-only.

Example: measure='weighted_civil_filings_per_judgeship', court='US', \
fiscal_year=2020 → eligible: 554 (JB-2020) → 322 (JFF-2025), no published \
explanation."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="check_inquiry_eligibility",
        description=DESCRIPTION,
        annotations={"title": "Can this go to the statistics office?", **READ_ONLY},
    )
    @core_errors
    async def check_inquiry_eligibility_tool(
        measure: Annotated[MeasureId, Field(description="The statistic.")],
        fiscal_year: Annotated[int, Field(ge=1990, le=2030)],
        court: Annotated[CourtCode, Field(description="US or a court.")] = "US",
    ) -> Result[Eligibility]:
        return inquiry_eligibility(get_db(), measure, court, fiscal_year)
