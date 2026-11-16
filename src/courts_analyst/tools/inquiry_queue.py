"""`inquiry_queue`: the statistics office's queue. Registered only when
``desk_staff_mode`` is on (ADR 0013)."""

from __future__ import annotations

from fastmcp import FastMCP

from courts_analyst.core.desk.models import InquiryQueue
from courts_analyst.core.desk.service import inquiry_queue
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db, get_desk
from courts_analyst.tools._desk import OFFICE

DESCRIPTION = """\
Use this only as the statistics office (staff mode, sandbox): the inquiries \
waiting for a response, one per revised figure, most-asked first, with how \
many requests wait on each.

Not for answering one (use record_official_response) or for approving \
answers (use publish_answer).

Returns the inquiries with their revision, route and any response. Read-only.

Example: → inquiry #1, FY2020 weighted civil filings per judgeship, 554 → \
322, 2 requests waiting."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="inquiry_queue",
        description=DESCRIPTION,
        annotations={"title": "Inquiry queue (staff)", **READ_ONLY},
    )
    @core_errors
    async def inquiry_queue_tool() -> Result[InquiryQueue]:
        return inquiry_queue(get_db(), get_desk(), OFFICE)
