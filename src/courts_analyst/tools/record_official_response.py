"""`record_official_response`: the simulated statistics office answers an
inquiry. Registered only when ``desk_staff_mode`` is on (ADR 0013)."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import DeskOutcome, Outcome
from courts_analyst.core.desk.service import check_text, record_official_response
from courts_analyst.core.results import Result
from courts_analyst.tools._common import WRITE, confirmed, core_errors, get_db, get_desk
from courts_analyst.tools._desk import OFFICE, Confirm, IdempotencyKey

DESCRIPTION = """\
Use this only as the statistics office (staff mode, sandbox): record the \
office's answer to an inquiry about a revised figure, written by the person \
playing the office. Never write the response yourself.

Not for approving the answer into the library (use publish_answer) or for \
public users (they ask with file_revision_inquiry).

Returns the inquiry with its response; every request waiting on it gets an \
update, and get_official_figure and explain_change show the response, \
labelled as from the simulated office. Writes only after confirmation.

Example: inquiry_id=1, outcome='confirmed', text='The 2023 edition \
re-weighted directly filed MDL cases.'"""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="record_official_response",
        description=DESCRIPTION,
        annotations={"title": "Record the office's response (staff)", **WRITE},
    )
    @core_errors
    async def record_official_response_tool(
        inquiry_id: Annotated[int, Field(ge=1)],
        outcome: Annotated[Outcome, Field(description="Confirmed or corrected.")],
        text: Annotated[str, Field(min_length=1, max_length=4000)],
        idempotency_key: IdempotencyKey = None,
        confirm: Confirm = False,
        ctx: Context | None = None,
    ) -> Result[DeskOutcome] | mcp_types.InputRequiredResult:
        check_text(get_db(), response=text)
        ok = await confirmed(
            ctx, confirm, f"Record this response to inquiry #{inquiry_id}?"
        )
        if isinstance(ok, mcp_types.InputRequiredResult):
            return ok
        return record_official_response(
            get_db(), get_desk(), OFFICE, inquiry_id, outcome, text, idempotency_key, ok
        )
