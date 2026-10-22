"""`save_verified_answer`: the verification gate, then the save (ADR 0013)."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import CitationIn, DeskOutcome
from courts_analyst.core.desk.service import save_verified_answer
from courts_analyst.core.results import Result
from courts_analyst.tools._common import WRITE, confirmed, core_errors, get_db, get_desk
from courts_analyst.tools._desk import AskerName, Confirm, IdempotencyKey, public_actor
from courts_analyst.tools._rerun import ToolCalls, recompute

DESCRIPTION = """\
Use this after open_request, when the user wants the answer kept: it checks \
the answer and saves it to the request only if it passes. The check: every \
number in the text is a cited official value, a number the server's read \
tools produce (pass the calls the answer relied on in tool_calls; the server \
re-runs them), a published threshold such as 430, or a difference or \
percentage of backed numbers; each citation matches what its edition \
printed; and one measure's figures come from consistent editions. An \
earlier edition's value may be quoted as history in a sentence that says so \
("first published as 554").

Not for creating the request (use open_request) or for asking why a figure \
changed (use file_revision_inquiry after saving).

Returns whether it was saved and, if not, each problem with the number and \
what to write instead. Writes only after the user confirms.

Example: text='322 in FY2020 and 318 in FY2021 (JFF-2024)', citations for \
both → saved; quoting 554 (JB-2020) beside 318 (JFF-2024) → refused, mixed \
editions."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="save_verified_answer",
        description=DESCRIPTION,
        annotations={"title": "Save a verified answer (sandbox)", **WRITE},
    )
    @core_errors
    async def save_verified_answer_tool(
        request_id: Annotated[int, Field(ge=1, description="From open_request.")],
        text: Annotated[
            str, Field(min_length=1, max_length=8000, description="The answer.")
        ],
        citations: Annotated[
            list[CitationIn],
            Field(
                max_length=60,
                description="One entry per official figure the answer quotes, "
                "with the edition it was quoted from.",
            ),
        ],
        tool_calls: ToolCalls,
        asker_name: AskerName = "MCP user",
        idempotency_key: IdempotencyKey = None,
        confirm: Confirm = False,
        ctx: Context | None = None,
    ) -> Result[DeskOutcome] | mcp_types.InputRequiredResult:
        ok = await confirmed(
            ctx, confirm, f"Save this answer to request #{request_id} if it passes?"
        )
        if isinstance(ok, mcp_types.InputRequiredResult):
            return ok
        computed = await recompute(mcp, tool_calls)
        return save_verified_answer(
            get_db(),
            get_desk(),
            public_actor(asker_name),
            request_id,
            text,
            citations,
            idempotency_key,
            ok,
            computed,
        )
