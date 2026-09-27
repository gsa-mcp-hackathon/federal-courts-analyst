"""No tool result exceeds the size budget, even on the largest queries."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp import Client

BUDGET_BYTES = 64_000
"""About 16k tokens: large enough for every district, small for a context."""

LARGEST: list[tuple[str, dict[str, Any]]] = [
    ("compare_courts", {"measure": "civil_cases_filed", "fiscal_year": 2024}),
    ("explain_change", {"measure": "civil_cases_filed", "period_from": 2019,
                        "period_to": 2020}),
    ("explain_change", {"measure": "weighted_civil_filings_per_judgeship",
                        "period_from": 2019, "period_to": 2020}),
    ("find_cases", {"fy_from": 2015, "fy_to": 2025}),
    ("get_official_figure", {"measure": "authorized_judgeships", "fiscal_year": 2015}),
    ("judgeship_context", {"court": "US"}),
]  # fmt: skip


@pytest.mark.parametrize(("tool", "args"), LARGEST, ids=lambda x: str(x)[:40])
async def test_within_budget(tools: Client, tool: str, args: dict[str, Any]) -> None:
    r = await tools.call_tool(tool, args)
    size = len(json.dumps(r.structured_content))
    assert size < BUDGET_BYTES, (tool, size)


async def test_grouped_analysis_within_budget(tools: Client) -> None:
    found = await tools.call_tool("find_cases", {"fy_from": 2015, "fy_to": 2025})
    handle = found.structured_content["data"]["handle"]
    for metric in ("share_by_nos_group", "disposition_rates"):
        r = await tools.call_tool(
            "analyze_cohort", {"handle": handle, "metric": metric, "group_by": "court"}
        )
        assert len(json.dumps(r.structured_content)) < BUDGET_BYTES
