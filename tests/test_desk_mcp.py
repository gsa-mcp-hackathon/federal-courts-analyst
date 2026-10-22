"""The request desk over MCP (ADR 0013): annotations, confirmation (by
elicitation, or a preview and a second call), the gate, and staff tools that
exist only in staff mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from courts_analyst.app import mcp
from courts_analyst.tools import register_tools

W = "weighted_civil_filings_per_judgeship"
QUESTION = "Why did FY2020 national weighted civil filings per judgeship change?"
ANSWER = (
    "FY2020 national weighted civil filings per judgeship are 322 (JFF-2024), "
    "first published as 554 (JB-2020); FY2021 is 318."
)
CITES = [
    {"measure": W, "fiscal_year": 2020, "edition": "JFF-2024", "value": 322},
    {"measure": W, "fiscal_year": 2020, "edition": "JB-2020", "value": 554},
    {"measure": W, "fiscal_year": 2021, "edition": "JFF-2024", "value": 318},
]


@pytest.fixture
def desk_path(server_data: None, tmp_path: Path, monkeypatch: Any) -> Path:
    from courts_analyst.config import settings

    path = tmp_path / "desk.sqlite"
    monkeypatch.setattr(settings, "desk_store_path", path)
    return path


def _yes(seen: list[str]) -> Any:
    async def handler(message: str, response_type: Any, params: Any, ctx: Any) -> Any:
        seen.append(message)
        try:
            return response_type(choice="yes")
        except TypeError:
            return {"value": "yes"}

    return handler


async def test_staff_tools_only_in_staff_mode() -> None:
    public = {t.name for t in await mcp.list_tools()}
    assert "record_official_response" not in public
    assert "publish_answer" not in public
    staff = FastMCP("staff")
    register_tools(staff, staff=True)
    names = {t.name for t in await staff.list_tools()}
    assert {"record_official_response", "publish_answer"} <= names
    for t in await staff.list_tools():
        if t.name in {"record_official_response", "publish_answer"}:
            assert t.annotations.read_only_hint is False
            assert t.annotations.destructive_hint is False


async def test_without_elicitation_a_write_is_previewed_first(desk_path: Path) -> None:
    async with Client(mcp) as c:
        preview = await c.call_tool(
            "open_request", {"option": "ask_office", "question": QUESTION}
        )
        data = preview.structured_content["data"]
        assert data["preview"] and not data["written"]
        done = await c.call_tool(
            "open_request",
            {"option": "ask_office", "question": QUESTION, "confirm": True},
        )
    out = done.structured_content["data"]
    assert out["written"] and out["request"]["status"] == "received"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_elicitation_confirms_the_write(desk_path: Path, mode: str) -> None:
    seen: list[str] = []
    async with Client(mcp, mode=mode, elicitation_handler=_yes(seen)) as c:
        r = await c.call_tool(
            "open_request", {"option": "verified_copy", "question": QUESTION}
        )
    assert seen and "sandbox request desk" in seen[0]
    assert r.structured_content["data"]["written"]


async def test_full_public_flow_over_mcp(desk_path: Path) -> None:
    async with Client(mcp) as c:
        opened = await c.call_tool(
            "open_request",
            {"option": "ask_office", "question": QUESTION, "confirm": True},
        )
        rid = opened.structured_content["data"]["request"]["id"]
        mixed = await c.call_tool(
            "save_verified_answer",
            {
                "request_id": rid,
                "text": "It was 554 in FY2020 and 318 in FY2021.",
                "citations": [CITES[1], CITES[2]],
                "confirm": True,
            },
        )
        gate = mixed.structured_content["data"]["gate"]
        assert not mixed.structured_content["data"]["written"]
        assert [p["code"] for p in gate["problems"]] == ["mixed_editions"]
        saved = await c.call_tool(
            "save_verified_answer",
            {"request_id": rid, "text": ANSWER, "citations": CITES, "confirm": True},
        )
        assert saved.structured_content["data"]["request"]["status"] == "verified"
        inquiry = await c.call_tool(
            "file_revision_inquiry",
            {"request_id": rid, "measure": W, "fiscal_year": 2020, "confirm": True},
        )
        data = inquiry.structured_content["data"]
        assert data["inquiry"]["route"] == "ao_statistics"
        assert data["request"]["status"] == "waiting_for_office"
        lib = await c.call_tool("find_published_answers", {"query": "weighted"})
        assert lib.structured_content["data"]["entries"] == []
    assert desk_path.exists()


async def test_someone_elses_request_is_refused(desk_path: Path) -> None:
    async with Client(mcp) as c:
        opened = await c.call_tool(
            "open_request",
            {
                "option": "notify",
                "question": QUESTION,
                "asker_name": "Priya",
                "confirm": True,
            },
        )
        rid = opened.structured_content["data"]["request"]["id"]
        r = await c.call_tool(
            "save_verified_answer",
            {
                "request_id": rid,
                "text": ANSWER,
                "citations": CITES,
                "asker_name": "Sam",
                "confirm": True,
            },
            raise_on_error=False,
        )
    assert r.is_error and "[forbidden]" in r.content[0].text


async def test_staff_mode_records_and_publishes(desk_path: Path) -> None:
    staff = FastMCP("staff")
    register_tools(staff, staff=True)
    async with Client(mcp) as c:
        rid = (
            await c.call_tool(
                "open_request",
                {"option": "ask_office", "question": QUESTION, "confirm": True},
            )
        ).structured_content["data"]["request"]["id"]
        await c.call_tool(
            "save_verified_answer",
            {"request_id": rid, "text": ANSWER, "citations": CITES, "confirm": True},
        )
        iid = (
            await c.call_tool(
                "file_revision_inquiry",
                {"request_id": rid, "measure": W, "fiscal_year": 2020, "confirm": True},
            )
        ).structured_content["data"]["inquiry"]["id"]
    async with Client(staff) as s:
        r = await s.call_tool(
            "record_official_response",
            {
                "inquiry_id": iid,
                "outcome": "confirmed",
                "text": "Explained.",
                "confirm": True,
            },
        )
        assert r.structured_content["data"]["inquiry"]["status"] == "office_responded"
        p = await s.call_tool("publish_answer", {"request_id": rid, "confirm": True})
        assert p.structured_content["data"]["request"]["status"] == "published"
    async with Client(mcp) as c:
        fig = await c.call_tool(
            "get_official_figure", {"measure": W, "fiscal_year": 2020}
        )
        notes = fig.structured_content["data"]["revision_notes"]
        assert any(n["basis"] == "office_response" for n in notes)
        lib = await c.call_tool("find_published_answers", {"query": "weighted"})
        assert len(lib.structured_content["data"]["entries"]) == 1
