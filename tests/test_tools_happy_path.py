"""One call per tool on the fixture data; snapshot the structured output
and check it against the tool's declared outputSchema."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from fastmcp import Client
from syrupy.assertion import SnapshotAssertion

CALLS: dict[str, dict[str, Any]] = {
    "get_official_figure": {
        "measure": "weighted_civil_filings_per_judgeship",
        "fiscal_year": 2020,
    },
    "compare_courts": {
        "measure": "weighted_total_filings_per_judgeship",
        "fiscal_year": 2024,
        "top_n": 5,
    },
    "explain_change": {
        "measure": "civil_cases_filed",
        "period_from": 2019,
        "period_to": 2020,
    },
    "find_cases": {"courts": ["FL-N"], "fy_from": 2020, "fy_to": 2020},
    "reconcile": {"measure": "civil_cases_pending", "court": "US", "fiscal_year": 2017},
    "judgeship_context": {"court": "TX-E", "fiscal_year": 2025},
    "explain_term": {"term": "nature of suit 442"},
    "server_info": {},
}


async def _schema(client: Client, name: str) -> dict[str, Any]:
    tool = next(t for t in await client.list_tools() if t.name == name)
    assert tool.output_schema is not None
    return tool.output_schema


def _validate(schema: dict[str, Any], data: dict[str, Any]) -> None:
    jsonschema.validate(data, schema)


def _stable(data: dict[str, Any]) -> dict[str, Any]:
    """Drop values that depend on the machine (paths, build times)."""
    out = dict(data)
    for p in out.get("provenance", []) or []:
        if p.get("dataset_release"):
            p["dataset_release"] = "<release>"
    return out


@pytest.mark.parametrize("name", sorted(CALLS))
async def test_tool_output_matches_schema_and_snapshot(
    tools: Client, name: str, snapshot: SnapshotAssertion
) -> None:
    result = await tools.call_tool(name, CALLS[name])
    data = result.structured_content
    assert data is not None
    _validate(await _schema(tools, name), data)
    if name == "server_info":
        assert data["tools"] == sorted(t.name for t in await tools.list_tools())
        return
    assert data["status"] == "ok"
    assert data["provenance"], "every result carries provenance"
    assert _stable(data) == snapshot


async def test_cohort_chain(tools: Client) -> None:
    """find_cases → analyze_cohort → sample_dockets → refine → reconcile."""
    found = await tools.call_tool(
        "find_cases", {"courts": ["FL-N"], "fy_from": 2020, "fy_to": 2020}
    )
    handle = found.structured_content["data"]["handle"]
    for metric in ("count", "median_days_to_disposition", "disposition_rates"):
        r = await tools.call_tool(
            "analyze_cohort", {"handle": handle, "metric": metric}
        )
        _validate(await _schema(tools, "analyze_cohort"), r.structured_content)
        assert r.structured_content["data"]["results"][0]["n"] > 0
    docs = await tools.call_tool("sample_dockets", {"handle": handle, "n": 3})
    _validate(await _schema(tools, "sample_dockets"), docs.structured_content)
    refs = docs.structured_content["data"]["dockets"]
    assert len(refs) == 3
    assert all(r["match_note"] == "match may be inexact" for r in refs)
    assert all("courtlistener.com" in r["courtlistener_search"] for r in refs)
    again = await tools.call_tool("sample_dockets", {"handle": handle, "n": 3})
    assert again.structured_content["data"]["dockets"] == refs  # deterministic
    narrow = await tools.call_tool(
        "find_cases",
        {
            "fy_from": 2020,
            "fy_to": 2020,
            "origins": ["mdl_direct"],
            "parent_handle": handle,
        },
    )
    child = narrow.structured_content["data"]
    assert child["parent"] == handle and child["mdl_direct_share"] == 1.0
    rec = await tools.call_tool("reconcile", {"handle": handle})
    assert rec.structured_content["data"]["court"] == "FL-N"


async def test_compare_circuit_expands_to_districts(tools: Client) -> None:
    r = await tools.call_tool(
        "compare_courts",
        {
            "measure": "weighted_civil_filings_per_judgeship",
            "fiscal_year": 2023,
            "courts": ["CIR-05"],
        },
    )
    courts = {row["court"] for row in r.structured_content["data"]["rows"]}
    assert courts == {
        "LA-E",
        "LA-M",
        "LA-W",
        "MS-N",
        "MS-S",
        "TX-N",
        "TX-E",
        "TX-S",
        "TX-W",
    }


async def test_legacy_client_calls_a_data_tool(
    server_data: None, legacy_client: Client
) -> None:
    r = await legacy_client.call_tool(
        "get_official_figure",
        {"measure": "weighted_civil_filings_per_judgeship", "fiscal_year": 2020},
    )
    assert r.structured_content["data"]["value"] == 322
