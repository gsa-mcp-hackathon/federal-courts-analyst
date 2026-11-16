"""Our MCP server as a tool provider for API answerers.

The answerers talk to the real server through FastMCP's in-memory client (the
same tools, schemas and descriptions any MCP client sees), so an eval run
measures the server, not a re-implementation of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

MAX_RESULT_CHARS = 20_000
"""Tool results sent back to the model are cut here (the output budget test
keeps real results under 64 KB; this bounds the cost of any outlier)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


async def list_tools(client: Client[Any]) -> list[ToolSpec]:
    return [
        ToolSpec(t.name, t.description or "", dict(t.input_schema))
        for t in await client.list_tools()
    ]


async def call_tool(
    client: Client[Any], name: str, arguments: dict[str, Any]
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Run one tool. Returns (text for the model, structured output, error)."""
    try:
        result = await client.call_tool(name, arguments)
    except ToolError as err:
        return f"Error: {err}", None, str(err)
    structured = result.structured_content
    text = (
        json.dumps(structured, separators=(",", ":"), default=str)
        if structured is not None
        else "".join(getattr(c, "text", "") for c in result.content)
    )
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " …[truncated]"
    return text, structured, None


SYSTEM_PROMPT = (
    "You answer questions about federal court statistics using the "
    "courts-analyst tools. Next to every figure you report, name the edition it "
    "comes from using its id (for example 322 (JFF-2025) or 554 (JB-2020)). You "
    "can't ask the user follow-up questions mid-answer: if the question is too "
    "ambiguous to answer, end with one clarifying question instead of guessing."
)
"""Same instructions as the Claude Code answerer, so runs are comparable."""
