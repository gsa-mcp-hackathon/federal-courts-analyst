"""`my_requests`: the asker's inbox on the request desk (ADR 0013)."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.desk.models import RequestList
from courts_analyst.core.desk.service import mark_read, my_requests
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db, get_desk
from courts_analyst.tools._desk import AskerName, public_actor

DESCRIPTION = """\
Use this when the user asks what happened to something they kept: their \
requests on the request desk, newest first, with each one's status \
(received, verified, waiting for the statistics office, office responded, \
published), the verified answer, the inquiry and the office's response, and \
every update.

Not for creating a request (use keep_answer) or for approved answers \
everyone can see (use find_published_answers).

Returns the requests and how many updates are unread. Read-only; \
mark_read=true only marks the updates as read.

Example: asker_name='Priya' → request #1002, 'Statistics office responded', \
with the response text."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="my_requests",
        description=DESCRIPTION,
        annotations={"title": "My requests", **READ_ONLY},
    )
    @core_errors
    async def my_requests_tool(
        asker_name: AskerName = "MCP user",
        request_id: Annotated[
            int | None, Field(default=None, ge=1, description="Just this one.")
        ] = None,
        mark_read_too: Annotated[
            bool, Field(description="Also mark the updates as read.")
        ] = False,
    ) -> Result[RequestList]:
        actor = public_actor(asker_name)
        db, store = get_db(), get_desk()
        if mark_read_too and request_id is not None:
            mark_read(db, store, actor, request_id)
        result = my_requests(db, store, actor)
        if request_id is not None and result.data is not None:
            result.data.requests = [
                r for r in result.data.requests if r.id == request_id
            ]
        return result
