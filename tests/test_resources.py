"""Resources list, templates resolve, edition tables are marked immutable."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError


async def test_static_resources(tools: Client) -> None:
    cat = json.loads((await tools.read_resource("courts://catalog"))[0].text)
    assert len(cat["editions"]) == 20 and len(cat["tables"]) == 60
    assert cat["revised_figures"] == 1340 and cat["idb"]["fy_from"] == "2015"
    revs = json.loads((await tools.read_resource("courts://revisions"))[0].text)
    fy2020 = next(
        r
        for r in revs
        if r["measure"] == "weighted_civil_filings_per_judgeship"
        and r["court"] == "US"
        and r["fiscal_year"] == 2020
    )
    assert (fy2020["first_value"], fy2020["latest_value"]) == (554, 322)
    gloss = json.loads((await tools.read_resource("courts://glossary"))[0].text)
    assert any(g["term"] == "weighted filings" for g in gloss)


async def test_edition_table(tools: Client) -> None:
    table = json.loads(
        (await tools.read_resource("courts://editions/JB-2020/X-1A"))[0].text
    )
    assert table["series"].startswith("Judicial Business")
    row = next(
        r
        for r in table["rows"]
        if r["court"] == "US" and r["measure"] == "weighted_civil_filings_per_judgeship"
    )
    assert row["value"] == 554 and row["cell_ref"]
    with pytest.raises(MCPError, match="Tables in JB-2020"):
        await tools.read_resource("courts://editions/JB-2020/6.2")


async def test_edition_template_is_immutable(tools: Client) -> None:
    templates = {t.uri_template: t for t in await tools.list_resource_templates()}
    ed = templates["courts://editions/{edition}/{table}"]
    assert ed.meta and ed.meta["immutable"] is True
    for t in templates.values():
        assert t.annotations is not None and t.annotations.audience


async def test_codebook_and_methodology(tools: Client) -> None:
    origin = json.loads((await tools.read_resource("courts://codebook/origin"))[0].text)
    assert any(c["code"] == "13" and c["valid_from"] for c in origin["codes"])
    note = (await tools.read_resource("courts://methodology/weighted-filings"))[0].text
    assert "430" in note and "554" in note
    with pytest.raises(MCPError, match="Unknown codebook field"):
        await tools.read_resource("courts://codebook/judge")
    with pytest.raises(MCPError, match="Unknown topic"):
        await tools.read_resource("courts://methodology/secrets")
