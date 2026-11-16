"""Invented courts, measures and editions are rejected by the schema."""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from courts_analyst.core.courts import COURTS
from courts_analyst.core.enums import EDITIONS, MEASURE_IDS


async def test_schemas_publish_enums(client: Client) -> None:
    tools = {t.name: t for t in await client.list_tools()}
    fig = tools["get_official_figure"].input_schema["properties"]
    assert fig["court"]["enum"] == list(COURTS)
    assert set(MEASURE_IDS) <= set(fig["measure"]["enum"])
    assert {"filings_per_judgeship", "civil_filings"} <= set(fig["measure"]["enum"])
    assert fig["edition"]["enum"] == ["latest", "first_published", *EDITIONS]
    find = tools["find_cases"].input_schema["properties"]
    court_items = find["courts"]["anyOf"][0]["items"]
    assert court_items["enum"] == list(COURTS)
    metric = tools["analyze_cohort"].input_schema["properties"]["metric"]
    assert "median_days_to_disposition" in metric["enum"]


@pytest.mark.parametrize(
    "args",
    [
        {"measure": "civil_cases_filed", "fiscal_year": 2020, "court": "N.D. Fla."},
        {"measure": "civil_cases_filed", "fiscal_year": 2020, "court": "SDNY"},
        {"measure": "civil_filings_total", "fiscal_year": 2020},
        {"measure": "civil_cases_filed", "fiscal_year": 2020, "edition": "JB2020"},
        {"measure": "civil_cases_filed", "fiscal_year": 2020, "edition": "JFF-2030"},
    ],
)
async def test_invented_values_rejected(
    client: Client, args: dict[str, object]
) -> None:
    with pytest.raises(ToolError, match="unknown"):
        await client.call_tool("get_official_figure", args)
