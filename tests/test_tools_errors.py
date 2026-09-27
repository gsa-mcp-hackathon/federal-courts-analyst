"""Bad input gets a helpful, typed error, never a stack trace."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.mark.parametrize(
    ("tool", "args", "expect"),
    [
        ("get_official_figure", {"measure": "civil_cases_filed", "fiscal_year": 2020,
                                 "court": "SDNY"}, "unknown court"),
        ("get_official_figure", {"measure": "civil_cases_filed", "fiscal_year": 1850},
         "greater than or equal"),
        ("get_official_figure", {"measure": "weighted_civil_filings_per_judgeship",
                                 "fiscal_year": 2012, "court": "AZ"}, "[out_of_scope]"),
        ("get_official_figure", {"measure": "weighted_civil_filings_per_judgeship",
                                 "fiscal_year": 2024, "court": "GU"}, "territorial"),
        ("get_official_figure", {"measure": "weighted_civil_filings_per_judgeship",
                                 "fiscal_year": 2020, "edition": "JB-2019"},
         "Editions that do"),
        ("analyze_cohort", {"handle": "coh_000000000000", "metric": "count"},
         "[unknown_handle]"),
        ("analyze_cohort", {"handle": "../etc/passwd", "metric": "count"}, "pattern"),
        ("sample_dockets", {"handle": "coh_000000000000"}, "find_cases"),
        ("sample_dockets", {"handle": "coh_000000000000", "n": 50}, "less than"),
        ("find_cases", {"fy_from": 2021, "fy_to": 2020}, "[invalid_cohort]"),
        ("find_cases", {"fy_from": 2020, "fy_to": 2020, "nos_codes": ["999"]},
         "unknown nature-of-suit"),
        ("explain_change", {"measure": "civil_median_months_to_disposition",
                            "period_from": 2019, "period_to": 2020}, "decompose"),
        ("explain_change", {"measure": "civil_cases_filed", "period_from": 2020,
                            "period_to": 2019}, "earlier"),
        ("reconcile", {"court": "US"}, "Give either handle"),
        ("judgeship_context", {"court": "CIR-05"}, "one district"),
    ],
)  # fmt: skip
async def test_errors_are_helpful(
    tools: Client, tool: str, args: dict[str, Any], expect: str
) -> None:
    with pytest.raises(ToolError) as err:
        await tools.call_tool(tool, args)
    text = str(err.value)
    assert expect in text
    assert "Traceback" not in text


async def test_missing_data_says_how_to_build(
    client: Client,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "duckdb_path", tmp_path / "none.duckdb")
    with pytest.raises(ToolError, match=r"\[data_unavailable\].*make data-tables"):
        await client.call_tool(
            "get_official_figure", {"measure": "civil_cases_filed", "fiscal_year": 2020}
        )


async def test_idb_tools_without_idb(
    client: Client,
    catalog,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "duckdb_path", catalog.db)
    monkeypatch.setattr(settings, "idb_duckdb_path", tmp_path / "none.duckdb")
    with pytest.raises(ToolError, match="make data-idb"):
        await client.call_tool("find_cases", {"fy_from": 2020, "fy_to": 2020})
    ok = await client.call_tool(
        "get_official_figure", {"measure": "civil_cases_filed", "fiscal_year": 2020}
    )
    assert ok.structured_content["data"]["value"] == 470581
