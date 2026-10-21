"""ADR 0013: the agent stays read-only. A plain question writes nothing, the
model is never offered a request desk tool, and a model that tries one
anyway is refused."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from courts_analyst.agent.events import ToolResultEvent
from courts_analyst.agent.loop import Agent
from courts_analyst.agent.providers.scripted import ScriptedProvider, Step
from courts_analyst.tools import DESK_TOOLS

FIGURE = {
    "measure": "weighted_civil_filings_per_judgeship",
    "court": "US",
    "fiscal_year": 2020,
}


@pytest.fixture
def desk(server_data: None, tmp_path: Path, monkeypatch: Any) -> Any:
    from courts_analyst.config import settings
    from courts_analyst.tools._common import get_desk

    monkeypatch.setattr(settings, "desk_store_path", tmp_path / "desk.sqlite")
    return get_desk()


async def _run(steps: list[Step]) -> tuple[list[Any], ScriptedProvider]:
    p = ScriptedProvider(steps)
    a = Agent(p, courtlistener="off")
    return [e async for e in a.run("What was FY2020's figure?")], p


def _writes(desk: Any) -> int:
    return int(desk.one("SELECT count(*) FROM audit_event")[0])


async def test_desk_tools_are_never_offered(desk: Any) -> None:
    _, p = await _run([Step("ok")])
    names = {t.name for t in p.requests[0]["tools"]}
    assert "get_official_figure" in names
    assert not names & DESK_TOOLS


async def test_a_plain_question_writes_nothing(desk: Any) -> None:
    await _run(
        [
            Step("", [("get_official_figure", FIGURE)]),
            Step("322 (JFF-2025); first published as 554 (JB-2020)."),
        ]
    )
    assert _writes(desk) == 0


@pytest.mark.parametrize("tool", sorted(DESK_TOOLS))
async def test_a_model_calling_a_desk_tool_is_refused(desk: Any, tool: str) -> None:
    events, _ = await _run(
        [Step("", [(tool, {"option": "notify", "question": "x", "confirm": True})]),
         Step("Sorry.")]
    )
    r = [e for e in events if isinstance(e, ToolResultEvent)][0]
    assert r.status == "error" and "Unknown tool" in (r.error or "")
    assert _writes(desk) == 0
