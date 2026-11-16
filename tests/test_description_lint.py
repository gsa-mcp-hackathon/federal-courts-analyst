"""Every tool description answers, in order: what question it answers
("Use this when…"), when to use a neighbour instead ("Not for…"), what it
returns ("Returns…"), and one example ("Example:")."""

from __future__ import annotations

import pytest

from courts_analyst.app import mcp

MAX_CHARS = 1200
PARTS = ("Use this", "Not for", "Returns", "Example:")


async def _tools() -> list:  # type: ignore[type-arg]
    return list(await mcp.list_tools())


@pytest.mark.parametrize(
    "name",
    [
        "explain_change",
        "get_official_figure",
        "compare_courts",
        "find_cases",
        "analyze_cohort",
        "reconcile",
        "judgeship_context",
        "explain_term",
        "sample_dockets",
        "find_published_answers",
        "check_inquiry_eligibility",
        "keep_answer",
        "my_requests",
        "open_request",
        "save_verified_answer",
        "file_revision_inquiry",
    ],
)
async def test_description_has_four_parts_in_order(name: str) -> None:
    tool = next(t for t in await _tools() if t.name == name)
    text = tool.description or ""
    positions = [text.find(p) for p in PARTS]
    assert all(p >= 0 for p in positions), (
        name,
        dict(zip(PARTS, positions, strict=True)),
    )
    assert positions == sorted(positions), name
    assert len(text) <= MAX_CHARS, (name, len(text))


async def test_neighbours_are_named() -> None:
    names = {t.name for t in await _tools()}
    for tool in await _tools():
        if tool.name == "server_info":
            continue
        neighbours = tool.description.split("Not for", 1)[1].split("Returns", 1)[0]
        assert (
            any(n in neighbours for n in names - {tool.name})
            or "party names" in neighbours
        ), tool.name
