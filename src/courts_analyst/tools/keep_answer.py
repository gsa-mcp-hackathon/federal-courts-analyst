"""`keep_answer`: everything one click on an option does, in one call
(ADR 0013). The same core function the web app's button uses."""

from __future__ import annotations

from typing import Annotated

import mcp_types
from fastmcp import Context, FastMCP
from pydantic import Field

from courts_analyst.core.desk import previews
from courts_analyst.core.desk.models import (
    OPTION_LABELS,
    CitationIn,
    DeskOutcome,
    InquiryTarget,
    Option,
)
from courts_analyst.core.desk.service import check_text, submit_option
from courts_analyst.core.results import Result
from courts_analyst.tools._common import WRITE, confirmed, core_errors, get_db, get_desk
from courts_analyst.tools._desk import (
    AskerName,
    AskerRole,
    Confirm,
    IdempotencyKey,
    public_actor,
)
from courts_analyst.tools._rerun import ToolCalls, recompute

DESCRIPTION = """\
Use this when the user asks to keep an answer you just gave: to ask the \
statistics office why a figure changed ('ask_office'), to save a verified \
copy ('verified_copy'), or to be told if its numbers change ('notify'). \
It checks the answer and, only if it passes, creates the request, saves \
the answer and (for 'ask_office') files the inquiry. Never call it on \
your own initiative.

Not for answering questions (use the read tools), for checking if a \
figure can go to the office (use check_inquiry_eligibility), or for following \
up (use my_requests).

Returns whether it was saved; if not, each problem with the number and the \
fix; if so, the request, inquiry and stamp to quote. Pass the \
answer's citations and the read tools it used (tool_calls). confirm=false \
writes nothing and returns a preview_id: describe the save, ask 'Shall I go \
ahead?', and only after a yes call with confirm=true and that preview_id. Changed \
text, or a retry after a refusal, needs a new preview. Sandbox: nothing \
reaches the AO or FJC.

Example: option='ask_office', inquiry={measure: \
'weighted_civil_filings_per_judgeship', fiscal_year: 2020}, an answer \
quoting 322 (JFF-2025) and 554 (JB-2020) → saved, inquiry #1."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="keep_answer",
        description=DESCRIPTION,
        annotations={"title": "Keep this answer (sandbox)", **WRITE},
    )
    @core_errors
    async def keep_answer_tool(
        option: Annotated[Option, Field(description="What the user wants kept.")],
        question: Annotated[
            str, Field(min_length=1, max_length=2000, description="The question.")
        ],
        answer_text: Annotated[
            str, Field(min_length=1, max_length=8000, description="The answer.")
        ],
        citations: Annotated[
            list[CitationIn],
            Field(
                max_length=60,
                description="Each official figure the answer quotes, with the "
                "edition it was quoted from.",
            ),
        ],
        tool_calls: ToolCalls,
        inquiry: Annotated[
            InquiryTarget | None,
            Field(
                default=None,
                description="For 'ask_office': the revised figure to ask about.",
            ),
        ] = None,
        asker_name: AskerName = "MCP user",
        asker_role: AskerRole = "public",
        idempotency_key: IdempotencyKey = None,
        confirm: Confirm = False,
        preview_id: Annotated[
            str | None,
            Field(
                default=None,
                max_length=40,
                description="With confirm=true: the preview_id from the "
                "confirm=false call the user said yes to.",
            ),
        ] = None,
        ctx: Context | None = None,
    ) -> Result[DeskOutcome] | mcp_types.InputRequiredResult:
        check_text(get_db(), question=question, answer=answer_text)
        ok = await confirmed(
            ctx, confirm, f'"{OPTION_LABELS[option]}": check and save this answer?'
        )
        if isinstance(ok, mcp_types.InputRequiredResult):
            return ok
        actor = public_actor(asker_name, asker_role)
        if not ok:
            pid = previews.issue(
                get_desk(), actor, option, answer_text, citations, inquiry
            )
            return Result[DeskOutcome](
                data=DeskOutcome(
                    written=False,
                    preview=True,
                    preview_id=pid,
                    message="Nothing written yet. Tell the user what will be "
                    f'saved as "{OPTION_LABELS[option]}" and ask \'Shall I go '
                    "ahead?'. Only after they say yes, call keep_answer again "
                    f"with confirm=true and preview_id='{pid}'.",
                ),
            )
        if confirm and not previews.redeem(
            get_desk(),
            actor,
            preview_id,
            option,
            answer_text,
            citations,
            inquiry,
            idempotency_key,
        ):
            return Result[DeskOutcome](
                data=DeskOutcome(written=False, message=previews.PREVIEW_REQUIRED)
            )
        computed = await recompute(mcp, tool_calls)
        return submit_option(
            get_db(),
            get_desk(),
            actor,
            option,
            question,
            answer_text,
            citations,
            inquiry,
            idempotency_key,
            computed,
        )
