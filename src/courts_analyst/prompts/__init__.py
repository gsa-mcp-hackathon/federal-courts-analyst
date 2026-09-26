"""Prompts submodule — reusable conversation starters.

Prompts appear in the client UI as slash commands / preset starters. Each
prompt module exposes a `register(mcp)` function; this file aggregates them
into `register_prompts(mcp)`. The analyst prompts arrive in Phase 5.
"""

from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register all prompts with the MCP server."""


__all__ = ["register_prompts"]
