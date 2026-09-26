"""Resources submodule — data the client can read directly by URI.

Resources use the `courts://` scheme (catalog, methodology, codebooks) and
`ui://` for MCP App bundles. Each resource module exposes a `register(mcp)`
function; this file aggregates them. The first resources arrive in Phase 5.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_resources(mcp: FastMCP) -> None:
    """Register all resources with the MCP server."""


__all__ = ["register_resources"]
