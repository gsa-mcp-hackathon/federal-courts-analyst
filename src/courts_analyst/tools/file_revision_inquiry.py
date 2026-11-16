"""`file_revision_inquiry`: ask the statistics office about one revision."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import DeskOutcome
from courts_analyst.core.desk.service import file_revision_inquiry
from courts_analyst.core.enums import CourtCode, MeasureId
from courts_analyst.core.results import Result
from courts_analyst.tools._common import WRITE, confirmed, core_errors, get_db, get_desk
from courts_analyst.tools._desk import AskerName, Confirm, IdempotencyKey, public_actor

DESCRIPTION = """\
Use this when the user picked "Ask the statistics office why this changed" \
for a figure in a saved answer: a figure that was revised between editions \
with no published explanation (e.g. FY2020 national weighted civil filings \
per judgeship, 554 → 322). It files one inquiry per revision; if someone \
already asked, the request joins that inquiry instead.

Not for figures that weren't revised or whose revision is routine (pending \
counts restated in Table C-1); get_official_figure shows a figure's \
revision_notes first. Not for free-text messages: an inquiry is always about \
one revision.

Returns the inquiry, how many requests wait on it, and where it would go (AO \
Statistics Division for published tables). Sandbox: nothing is sent. Writes \
only after the user confirms.

Example: request_id=1001, measure='weighted_civil_filings_per_judgeship', \
court='US', fiscal_year=2020 → inquiry #1, waiting_for_office."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="file_revision_inquiry",
        description=DESCRIPTION,
        annotations={"title": "Ask the statistics office (sandbox)", **WRITE},
    )
    @core_errors
    async def file_revision_inquiry_tool(
        request_id: Annotated[int, Field(ge=1, description="The request.")],
        measure: Annotated[MeasureId, Field(description="The revised statistic.")],
        fiscal_year: Annotated[int, Field(ge=1990, le=2030)],
        court: Annotated[CourtCode, Field(description="US or a court.")] = "US",
        asker_name: AskerName = "MCP user",
        idempotency_key: IdempotencyKey = None,
        confirm: Confirm = False,
        ctx: Context | None = None,
    ) -> Result[DeskOutcome] | mcp_types.InputRequiredResult:
        ok = await confirmed(
            ctx,
            confirm,
            f"Ask the statistics office why FY{fiscal_year} {measure} ({court}) "
            "changed? (Sandbox: nothing is sent.)",
        )
        if isinstance(ok, mcp_types.InputRequiredResult):
            return ok
        return file_revision_inquiry(
            get_db(),
            get_desk(),
            public_actor(asker_name),
            request_id,
            measure,
            court,
            fiscal_year,
            idempotency_key,
            ok,
        )
