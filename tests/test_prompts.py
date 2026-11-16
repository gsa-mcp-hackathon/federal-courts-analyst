"""Prompts render with their arguments and carry the reporting rules."""

from __future__ import annotations

import pytest
from fastmcp import Client

PROMPTS = {
    "district_caseload_profile": {"court": "FL-N", "fiscal_year": "2024"},
    "what_changed_and_why": {"measure": "civil_filings", "period_from": "2019",
                             "period_to": "2020"},
    "judgeship_briefing": {"court": "TX-E"},
    "compare_editions": {"measure": "weighted_civil_filings_per_judgeship",
                         "fiscal_year": "2020"},
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(PROMPTS))
async def test_prompt_renders(client: Client, name: str) -> None:
    result = await client.get_prompt(name, PROMPTS[name])
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert "never rank or profile individual judges" in text
    assert "edition" in text
    for value in PROMPTS[name].values():
        assert value in text or value.upper() in text


async def test_prompt_names_court(client: Client) -> None:
    r = await client.get_prompt("judgeship_briefing", {"court": "TX-E"})
    text = r.messages[0].content.text  # type: ignore[union-attr]
    assert "E.D. Tex. (TX-E)" in text and "no recommendation" not in text.lower()
