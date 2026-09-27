"""Elicitation: modern (MRTR), legacy (ctx.elicit) and no-handler clients.

An ambiguous measure ('filings_per_judgeship') makes the tool ask. The
chosen answer must be honoured; without a handler (or when the user
declines) the tool returns a structured needs_clarification result with the
same choices, and passing a choice as an ordinary argument always works.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from courts_analyst.app import mcp

ARGS = {"measure": "filings_per_judgeship", "fiscal_year": 2020}


def _handler(choice: str | None, seen: list[str]) -> Any:
    async def handler(
        message: str, response_type: Any, params: Any, context: Any
    ) -> Any:
        seen.append(message)
        if choice is None:
            from fastmcp.client.elicitation import ElicitResult

            return ElicitResult(action="decline")
        # Modern requests carry our form schema (a 'choice' property); legacy
        # single-select prompts wrap the value as {'value': ...}.
        try:
            return response_type(choice=choice)
        except TypeError:
            return {"value": choice}

    return handler


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_answer_is_honoured(server_data: None, mode: str) -> None:
    seen: list[str] = []
    handler = _handler("civil_filings_per_judgeship", seen)
    async with Client(mcp, mode=mode, elicitation_handler=handler) as c:
        r = await c.call_tool("get_official_figure", ARGS)
    assert seen and "weighted or unweighted" in seen[0]
    data = r.structured_content
    assert data["status"] == "ok"
    assert data["data"]["measure"] == "civil_filings_per_judgeship"
    assert data["data"]["value"] == 675  # JFF-2025


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_decline_returns_clarification(server_data: None, mode: str) -> None:
    seen: list[str] = []
    async with Client(mcp, mode=mode, elicitation_handler=_handler(None, seen)) as c:
        r = await c.call_tool("get_official_figure", ARGS)
    assert seen
    assert r.structured_content["status"] == "needs_clarification"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_no_handler_gets_structured_choices(server_data: None, mode: str) -> None:
    async with Client(mcp, mode=mode) as c:
        r = await c.call_tool("get_official_figure", ARGS)
    data = r.structured_content
    assert data["status"] == "needs_clarification" and data["data"] is None
    clar = data["clarification"]
    assert clar["parameter"] == "measure"
    values = [ch["value"] for ch in clar["choices"]]
    assert values == [
        "weighted_total_filings_per_judgeship",
        "total_filings_per_judgeship",
        "weighted_civil_filings_per_judgeship",
        "civil_filings_per_judgeship",
    ]
    assert clar["default"] == "weighted_total_filings_per_judgeship"
    # The same choice as an ordinary argument answers it.
    r2 = await Client(mcp).__aenter__()
    try:
        answered = await r2.call_tool(
            "get_official_figure", {**ARGS, "measure": values[2]}
        )
    finally:
        await r2.__aexit__(None, None, None)
    assert answered.structured_content["data"]["value"] == 322


@pytest.mark.parametrize(
    ("tool", "args", "model_field"),
    [
        ("explain_change", {"measure": "civil_filings", "period_from": 2019,
                            "period_to": 2020}, "civil_cases_filed"),
        ("compare_courts", {"measure": "filings_per_judgeship", "fiscal_year": 2024,
                            "top_n": 3}, "weighted_total_filings_per_judgeship"),
    ],
)  # fmt: skip
async def test_other_tools_ask_too(
    server_data: None, tool: str, args: dict[str, Any], model_field: str
) -> None:
    async with Client(mcp) as c:
        r = await c.call_tool(tool, args)
    assert r.structured_content["status"] == "needs_clarification"
    seen: list[str] = []
    async with Client(mcp, elicitation_handler=_handler(model_field, seen)) as c:
        r = await c.call_tool(tool, args)
    assert seen and r.structured_content["status"] == "ok"
    assert r.structured_content["data"]["measure"] == model_field
