"""`publish_answer`: approve a verified answer into the public library.
Registered only when ``desk_staff_mode`` is on (ADR 0013)."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import DeskOutcome
from courts_analyst.core.desk.service import publish_answer
from courts_analyst.core.results import Result
from courts_analyst.tools._common import WRITE, confirmed, core_errors, get_db, get_desk
from courts_analyst.tools._desk import OFFICE, Confirm, IdempotencyKey

DESCRIPTION = """\
Use this only as the statistics office (staff mode, sandbox), when the person \
playing the office approves a request's verified answer for the public \
library. A person must approve; never approve on your own.

Not for recording the office's explanation (use record_official_response) or \
for searching the library (use find_published_answers).

Returns the published request; its asker gets an update and the answer \
becomes searchable. Writes only after confirmation.

Example: request_id=1001 → published."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="publish_answer",
        description=DESCRIPTION,
        annotations={"title": "Publish an answer (staff)", **WRITE},
    )
    @core_errors
    async def publish_answer_tool(
        request_id: Annotated[int, Field(ge=1)],
        idempotency_key: IdempotencyKey = None,
        confirm: Confirm = False,
        ctx: Context | None = None,
    ) -> Result[DeskOutcome] | mcp_types.InputRequiredResult:
        ok = await confirmed(
            ctx, confirm, f"Publish request #{request_id}'s answer to the library?"
        )
        if isinstance(ok, mcp_types.InputRequiredResult):
            return ok
        return publish_answer(
            get_db(), get_desk(), OFFICE, request_id, idempotency_key, ok
        )
