"""Re-running an answer's read tools, so the verification gate can back the
numbers they produce (ADR 0013, decision 5).

Shared by the MCP desk tools and the REST routes, so every client gets the
same check. The request names tools and arguments only; every value comes
from this server's own re-run, never from the caller.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field, StringConstraints

from courts_analyst.core.figures_text import figures_in_text

log = logging.getLogger("courts_analyst.desk")

MAX_RERUNS = 8
RERUNNABLE = frozenset(
    {
        "get_official_figure",
        "explain_change",
        "compare_courts",
        "find_cases",
        "analyze_cohort",
        "reconcile",
        "judgeship_context",
    }
)
"""Deterministic read tools over the server's own data. Never desk tools,
never CourtListener."""


class ToolCallIn(BaseModel):
    """A read tool the answer relied on, with the arguments it was called with."""

    tool: Annotated[str, StringConstraints(max_length=64, pattern=r"^[a-z_]+$")]
    arguments: dict[str, Any] = Field(default_factory=dict)


ToolCalls = Annotated[
    list[ToolCallIn],
    Field(
        default_factory=list,
        max_length=MAX_RERUNS,
        description="The read tools the answer relied on (name and arguments, "
        "e.g. explain_change with its arguments). The server re-runs them; numbers "
        "their outputs hold count as backed. Never send values.",
    ),
]


def _numbers(node: Any, out: set[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        out |= {float(node), float(round(node)), round(float(node), 1)}
    elif isinstance(node, str):
        out |= {f.value for f in figures_in_text(node)}
    elif isinstance(node, dict):
        for v in node.values():
            _numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _numbers(v, out)


async def recompute(server: FastMCP, calls: list[ToolCallIn]) -> dict[float, str]:
    """Re-run the read tools in process; map every number their outputs hold to
    the tool that produced it."""
    out: dict[float, str] = {}
    for call in [c for c in calls if c.tool in RERUNNABLE][:MAX_RERUNS]:
        try:
            result = await server.call_tool(
                call.tool, call.arguments, run_middleware=False
            )
        except Exception as exc:  # bad arguments, a tool error: no values
            log.info(
                "desk re-run skipped",
                extra={"tool": call.tool, "error": type(exc).__name__},
            )
            continue
        structured = getattr(result, "structured_content", None)
        if getattr(result, "is_error", False) or not structured:
            continue
        found: set[float] = set()
        _numbers(structured, found)
        for v in found:
            out.setdefault(v, call.tool)
    return out
