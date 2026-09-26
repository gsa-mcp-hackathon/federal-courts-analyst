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

from courts_analyst.tools import server_info


def register_tools(mcp: FastMCP) -> None:
    """Register all tools with the MCP server."""
    server_info.register(mcp)


__all__ = ["register_tools"]
