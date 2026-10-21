"""`open_request`: create a request on the sandbox request desk (ADR 0013)."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import OPTION_LABELS, DeskOutcome, Option
from courts_analyst.core.desk.service import open_request
from courts_analyst.core.results import Result
from courts_analyst.tools._common import WRITE, confirmed, core_errors, get_db, get_desk
from courts_analyst.tools._desk import (
    AskerName,
    AskerRole,
    Confirm,
    IdempotencyKey,
    public_actor,
)

DESCRIPTION = """\
Use this only when the user explicitly asks to keep an answer: to ask the \
statistics office why a figure changed (option 'ask_office'), to save a \
verified copy ('verified_copy'), or to be notified if its numbers change \
('notify'). It creates a request on the sandbox request desk. Answering a \
question never needs it; never call it on your own initiative.

Not for answering questions (use get_official_figure, explain_change and the \
other read tools) or for saving the answer text (call save_verified_answer \
next, with the answer and its citations).

Returns the new request: its number, status and inbox updates. It writes only \
after the user confirms; without confirmation it returns a preview. Sandbox: \
nothing is sent to the AO or the FJC.

Example: option='ask_office', question='Why did FY2020 national weighted civil \
filings per judgeship change from 554 to 322?' → request #1001, status \
'received'."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="open_request",
        description=DESCRIPTION,
        annotations={"title": "Open a request (sandbox)", **WRITE},
    )
    @core_errors
    async def open_request_tool(
        option: Annotated[Option, Field(description="What the user wants kept.")],
        question: Annotated[
            str,
            Field(min_length=1, max_length=2000, description="The user's question."),
        ],
        asker_name: AskerName = "MCP user",
        asker_role: AskerRole = "public",
        idempotency_key: IdempotencyKey = None,
        confirm: Confirm = False,
        ctx: Context | None = None,
    ) -> Result[DeskOutcome] | mcp_types.InputRequiredResult:
        ok = await confirmed(
            ctx,
            confirm,
            f'Create a "{OPTION_LABELS[option]}" request on the sandbox request desk?',
        )
        if isinstance(ok, mcp_types.InputRequiredResult):
            return ok
        return open_request(
            get_db(),
            get_desk(),
            public_actor(asker_name, asker_role),
            option,
            question,
            idempotency_key,
            ok,
        )
