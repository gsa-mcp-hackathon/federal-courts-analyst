"""Tools submodule — one tool per file.

Each tool module exposes a `register(mcp)` function that attaches its
`@mcp.tool`-decorated function to the server. Tools are thin adapters: they
validate input, call `core/`, and return a Pydantic model.

To add a tool:
  1. Create `tools/<your_tool>.py` with a `register(mcp)` function.
  2. Import it below and call `<your_tool>.register(mcp)` inside register_tools.
  3. Add its name to EXPECTED_TOOLS in tests/test_registration.py.
"""

from __future__ import annotations

from fastmcp import FastMCP

from courts_analyst.config import settings
from courts_analyst.core.desk import hooks
from courts_analyst.tools import (
    analyze_cohort,
    check_inquiry_eligibility,
    compare_courts,
    explain_change,
    explain_term,
    file_revision_inquiry,
    find_cases,
    find_published_answers,
    get_official_figure,
    inquiry_queue,
    judgeship_context,
    keep_answer,
    my_requests,
    open_request,
    publish_answer,
    reconcile,
    record_official_response,
    sample_dockets,
    save_verified_answer,
    server_info,
)
from courts_analyst.tools._common import get_desk

# Registration order is the tools/list order (spec 2026-07-28 asks for a
# stable one): the flagship first, then the rest in the order an analyst
# usually reaches for them.
MODULES = (
    explain_change,
    get_official_figure,
    compare_courts,
    find_cases,
    analyze_cohort,
    reconcile,
    judgeship_context,
    explain_term,
    sample_dockets,
    find_published_answers,
    check_inquiry_eligibility,
    keep_answer,
    my_requests,
    open_request,
    save_verified_answer,
    file_revision_inquiry,
    server_info,
)

# The request desk (ADR 0013). The agent never gets these (agent/mcp_clients.py):
# a person picks every write in the web app.
DESK_TOOLS = frozenset(
    {
        "find_published_answers",
        "check_inquiry_eligibility",
        "keep_answer",
        "my_requests",
        "inquiry_queue",
        "open_request",
        "save_verified_answer",
        "file_revision_inquiry",
        "record_official_response",
        "publish_answer",
    }
)
# Staff-only: registered only with DESK_STAFF_MODE, so a public client never
# sees them.
STAFF_MODULES = (inquiry_queue, record_official_response, publish_answer)


def register_tools(mcp: FastMCP, staff: bool | None = None) -> None:
    """Register all tools with the MCP server (staff tools only in staff mode)."""
    for module in MODULES:
        module.register(mcp)
    if settings.desk_staff_mode if staff is None else staff:
        for module in STAFF_MODULES:
            module.register(mcp)
    # Read tools show statistics-office responses recorded on the desk. Lazy:
    # registering opens no file.
    hooks.set_store_provider(get_desk)


__all__ = ["register_tools"]
