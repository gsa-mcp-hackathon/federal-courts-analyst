"""REST and MCP return the same envelope for the same inputs.

The explorer (REST) and the agent (MCP tools) must never disagree: for each
case, ``data``, ``provenance``, ``warnings`` and ``status`` from the REST
endpoint equal the MCP tool's structured result exactly.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from courts_analyst.app import mcp

KEYS = ("status", "data", "provenance", "warnings", "clarification", "declined")

CASES = [
    (
        "get_official_figure",
        {
            "measure": "weighted_civil_filings_per_judgeship",
            "court": "US",
            "fiscal_year": 2020,
        },
        "/api/figures",
    ),
    (
        "get_official_figure",
        {
            "measure": "weighted_civil_filings_per_judgeship",
            "court": "US",
            "fiscal_year": 2020,
            "edition": "first_published",
        },
        "/api/figures",
    ),
    (
        "get_official_figure",
        {"measure": "civil_cases_filed", "court": "FL-N", "fiscal_year": 2020},
        "/api/figures",
    ),
    (
        "get_official_figure",
        {"measure": "filings_per_judgeship", "fiscal_year": 2020},
        "/api/figures",
    ),
    (
        "compare_courts",
        {"measure": "civil_cases_filed", "fiscal_year": 2020, "top_n": 5},
        "/api/compare",
    ),
    (
        "compare_courts",
        {
            "measure": "weighted_civil_filings_per_judgeship",
            "fiscal_year": 2020,
            "courts": ["FL-N", "TX-E", "NY-S"],
            "order": "asc",
        },
        "/api/compare",
    ),
    (
        "explain_change",
        {
            "measure": "civil_cases_filed",
            "court": "US",
            "period_from": 2019,
            "period_to": 2020,
        },
        "/api/explain-change",
    ),
    (
        "judgeship_context",
        {"court": "FL-N", "fiscal_year": 2020},
        "/api/courts/FL-N/profile",
    ),
]

REST_NAMES = {"period_from": "from", "period_to": "to"}


def _params(tool: str, args: dict[str, Any]) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for k, v in args.items():
        if tool == "judgeship_context" and k == "court":
            continue
        if isinstance(v, list):
            out.extend((k, x) for x in v)
        else:
            out.append((REST_NAMES.get(k, k), v))
    return out


@pytest.mark.parametrize(("tool", "args", "path"), CASES)
async def test_rest_matches_mcp(
    api: Any, tool: str, args: dict[str, Any], path: str
) -> None:
    async with Client(mcp) as c:
        via_mcp = (await c.call_tool(tool, args)).structured_content
    r = api.get(path, params=_params(tool, args))
    assert r.status_code == 200, r.text
    via_rest = r.json()
    for key in KEYS:
        assert via_rest.get(key) == via_mcp.get(key), key
    assert via_rest["status"] in ("ok", "needs_clarification")


async def test_errors_match_too(api: Any) -> None:
    """The same core error: MCP ToolError text, REST 422 with the same code."""
    from fastmcp.exceptions import ToolError

    async with Client(mcp) as c:
        with pytest.raises(ToolError) as err:
            await c.call_tool(
                "get_official_figure",
                {"measure": "civil_cases_filed", "court": "US", "fiscal_year": 1991},
            )
    r = api.get(
        "/api/figures",
        params={"measure": "civil_cases_filed", "court": "US", "fiscal_year": 1991},
    )
    body = r.json()
    assert f"[{body['error']}]" in str(err.value)
    assert body["message"] in str(err.value)
