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

from courts_analyst.tools import (
    analyze_cohort,
    compare_courts,
    explain_change,
    explain_term,
    find_cases,
    get_official_figure,
    judgeship_context,
    reconcile,
    sample_dockets,
    server_info,
)

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
    server_info,
)


def register_tools(mcp: FastMCP) -> None:
    """Register all tools with the MCP server."""
    for module in MODULES:
        module.register(mcp)


__all__ = ["register_tools"]
