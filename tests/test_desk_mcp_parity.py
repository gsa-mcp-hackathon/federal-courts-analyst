"""The request desk is complete over MCP (ADR 0013): any MCP client can do
what the web app does, through the same core functions, and one person's
requests are the same records in both.

Uses the recorded FY2020 agent answer (web/public/demo), the way a client
like Claude Desktop would pass it: the answer, its citations, and the read
tools it relied on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from pydantic import SecretStr

from courts_analyst.app import mcp
from courts_analyst.tools import register_tools

W = "weighted_civil_filings_per_judgeship"
RECORDING = Path(__file__).resolve().parents[1] / "web/public/demo/fy2020-storyline.sse"
# The fixture IDB is a sample: these two full-database counts can't be
# reproduced by the re-run, so the walkthrough edits them out.
SAMPLE_ONLY = (
    (": +201,017 filings there per the IDB-derived breakdown", ""),
    (
        "From a cohort of 202,463 directly-filed MDL cases",
        "From the directly filed MDL cases",
    ),
)


def _turn() -> dict[str, Any]:
    events = [
        json.loads(line[6:])
        for line in RECORDING.read_text().splitlines()
        if line.startswith("data: ")
    ]
    text = "".join(e["text"] for e in events if e["type"] == "text_delta")
    for old, new in SAMPLE_ONLY:
        text = text.replace(old, new)
    keys = ("measure", "court", "fiscal_year", "edition", "value")
    return {
        "question": "Why did weighted civil filings per judgeship change in FY2020?",
        "answer_text": text,
        "citations": [
            {k: e["ref"][k] for k in keys} for e in events if e["type"] == "citation"
        ],
        "tool_calls": [
            {"tool": e["tool"], "arguments": e["arguments"]}
            for e in events
            if e["type"] == "tool_call"
        ],
    }


@pytest.fixture
def desk(server_data: None, tmp_path: Path, monkeypatch: Any) -> None:
    from courts_analyst.api.routes import desk as routes
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "desk_store_path", tmp_path / "desk.sqlite")
    monkeypatch.setattr(settings, "desk_staff_token", SecretStr("office-token"))
    monkeypatch.setattr(routes, "_limiter", None)


def _keep(turn: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "option": "ask_office",
        "inquiry": {"measure": W, "fiscal_year": 2020},
        "asker_name": "Priya",
        "confirm": True,
        **turn,
        **extra,
    }


async def test_keep_answer_backs_computed_numbers_like_the_web(desk: None) -> None:
    async with Client(mcp) as c:
        r = await c.call_tool("keep_answer", _keep(_turn()))
    out = r.structured_content["data"]
    assert out["written"], out["gate"]["problems"]
    assert out["request"]["status"] == "waiting_for_office"
    computed = {x["number"] for x in out["gate"]["computed"]}
    assert {"206", "211", "322", "332"} <= computed
    assert (
        "re-computed by re-running explain_change" in out["request"]["answer"]["stamp"]
    )


async def test_without_tool_calls_the_same_answer_is_refused(desk: None) -> None:
    async with Client(mcp) as c:
        r = await c.call_tool("keep_answer", _keep(_turn(), tool_calls=[]))
    out = r.structured_content["data"]
    assert not out["written"]
    assert "206" in {p["number"] for p in out["gate"]["problems"]}


async def test_keep_answer_previews_without_confirmation(desk: None) -> None:
    async with Client(mcp) as c:
        r = await c.call_tool("keep_answer", _keep(_turn(), confirm=False))
    out = r.structured_content["data"]
    assert out["preview"] and not out["written"]


async def test_one_person_one_inbox_across_clients(desk: None, api: Any) -> None:
    """Priya keeps an answer from an MCP client; the web app's My requests
    shows it; the office responds on the web; her MCP client sees it."""
    async with Client(mcp) as c:
        rid = (await c.call_tool("keep_answer", _keep(_turn()))).structured_content[
            "data"
        ]["request"]["id"]
    web = api.get("/api/desk/requests", headers={"x-desk-account": "priya"}).json()
    assert [x["id"] for x in web["data"]["requests"]] == [rid]
    staff = {"x-desk-staff-token": "office-token"}
    iid = api.get("/api/desk/staff/inquiries", headers=staff).json()["data"][
        "inquiries"
    ][0]["id"]
    api.post(
        f"/api/desk/staff/inquiries/{iid}/response",
        headers=staff,
        json={"outcome": "confirmed", "text": "Re-weighted MDL cases."},
    )
    async with Client(mcp) as c:
        mine = await c.call_tool(
            "my_requests",
            {"asker_name": "Priya Shah", "request_id": rid, "mark_read_too": True},
        )
    req = mine.structured_content["data"]["requests"][0]
    assert req["status"] == "office_responded"
    assert req["inquiry"]["response"]["text"] == "Re-weighted MDL cases."
    assert req["unread"] == 0


async def test_save_verified_answer_reruns_tool_calls_too(desk: None) -> None:
    turn = _turn()
    async with Client(mcp) as c:
        rid = (
            await c.call_tool(
                "open_request",
                {
                    "option": "verified_copy",
                    "question": turn["question"],
                    "asker_name": "Rae",
                    "confirm": True,
                },
            )
        ).structured_content["data"]["request"]["id"]
        saved = await c.call_tool(
            "save_verified_answer",
            {
                "request_id": rid,
                "text": turn["answer_text"],
                "citations": turn["citations"],
                "tool_calls": turn["tool_calls"],
                "asker_name": "Rae",
                "confirm": True,
            },
        )
    assert saved.structured_content["data"]["written"]


async def test_eligibility_tool(desk: None) -> None:
    async with Client(mcp) as c:
        yes = await c.call_tool(
            "check_inquiry_eligibility", {"measure": W, "fiscal_year": 2020}
        )
        no = await c.call_tool(
            "check_inquiry_eligibility",
            {"measure": "civil_cases_pending", "fiscal_year": 2023},
        )
    assert yes.structured_content["data"]["eligible"] is True
    assert yes.structured_content["data"]["from_value"] == 554
    assert no.structured_content["data"]["eligible"] is False


async def test_staff_queue_library_resource_and_prompt(desk: None) -> None:
    staff = FastMCP("staff")
    register_tools(staff, staff=True)
    async with Client(mcp) as c:
        rid = (await c.call_tool("keep_answer", _keep(_turn()))).structured_content[
            "data"
        ]["request"]["id"]
    async with Client(staff) as s:
        queue = (await s.call_tool("inquiry_queue", {})).structured_content["data"]
        iid = queue["inquiries"][0]["id"]
        assert queue["inquiries"][0]["waiting_requests"] == 1
        await s.call_tool(
            "record_official_response",
            {
                "inquiry_id": iid,
                "outcome": "confirmed",
                "text": "Explained.",
                "confirm": True,
            },
        )
        await s.call_tool("publish_answer", {"request_id": rid, "confirm": True})
    async with Client(mcp) as c:
        lib = await c.read_resource("desk://library")
        entries = json.loads(lib[0].text)["data"]["entries"]
        assert [e["request_id"] for e in entries] == [rid]
        prompt = await c.get_prompt("keep_this_answer", {"option": "ask_office"})
        text = prompt.messages[0].content.text
        assert "check_inquiry_eligibility" in text and "keep_answer" in text
        assert "tool_calls" in text and "my_requests" in text
