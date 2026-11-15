"""keep_answer's preview check (ADR 0013, core/desk/previews.py): a
confirm=true call must pass the preview_id of a confirm=false call for the
same answer, option, asker and citations, and each id works once. So an agent
that resends restated text after a refused save can't skip the user's new
"Shall I go ahead?"."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from courts_analyst.app import mcp
from courts_analyst.core.desk import previews
from courts_analyst.core.desk.accounts import resolve
from courts_analyst.core.desk.models import CitationIn
from courts_analyst.core.desk.store import DeskStore

W = "weighted_civil_filings_per_judgeship"
QUESTION = "What were national weighted civil filings per judgeship in FY2020-21?"
ANSWER = (
    "FY2020 national weighted civil filings per judgeship are 322 (JFF-2024), "
    "first published as 554 (JB-2020); FY2021 is 318."
)
CITES = [
    {"measure": W, "fiscal_year": 2020, "edition": "JFF-2024", "value": 322},
    {"measure": W, "fiscal_year": 2020, "edition": "JB-2020", "value": 554},
    {"measure": W, "fiscal_year": 2021, "edition": "JFF-2024", "value": 318},
]
MIXED = "It was 554 in FY2020 and 318 in FY2021."
MIXED_CITES = [CITES[1], CITES[2]]


@pytest.fixture
def desk_path(server_data: None, tmp_path: Path, monkeypatch: Any) -> Path:
    from courts_analyst.config import settings

    path = tmp_path / "desk.sqlite"
    monkeypatch.setattr(settings, "desk_store_path", path)
    return path


def _args(**extra: Any) -> dict[str, Any]:
    return {
        "option": "verified_copy",
        "question": QUESTION,
        "answer_text": ANSWER,
        "citations": CITES,
        "asker_name": "Priya",
        **extra,
    }


async def _call(c: Client[Any], **extra: Any) -> dict[str, Any]:
    r = await c.call_tool("keep_answer", _args(**extra))
    data: dict[str, Any] = r.structured_content["data"]
    return data


async def _requests(c: Client[Any]) -> list[Any]:
    mine = await c.call_tool("my_requests", {"asker_name": "Priya"})
    out: list[Any] = mine.structured_content["data"]["requests"]
    return out


async def test_preview_then_confirm_with_its_id_saves(desk_path: Path) -> None:
    async with Client(mcp) as c:
        preview = await _call(c)
        assert preview["preview"] and not preview["written"]
        pid = preview["preview_id"]
        assert pid and pid in preview["message"]
        assert "Shall I go ahead?" in preview["message"]
        assert await _requests(c) == []
        saved = await _call(c, confirm=True, preview_id=pid)
        assert saved["written"], saved
        assert len(await _requests(c)) == 1


async def test_confirm_without_a_preview_id_is_refused(desk_path: Path) -> None:
    async with Client(mcp) as c:
        out = await _call(c, confirm=True)
        assert not out["written"] and not out["preview"]
        assert out["message"] == previews.PREVIEW_REQUIRED
        assert "Shall I go ahead?" in out["message"]
        assert await _requests(c) == []


@pytest.mark.parametrize(
    "change",
    [
        {"answer_text": ANSWER.replace("318", "319")},
        {"citations": CITES[:2]},
        {"option": "notify"},
        {"asker_name": "Sam"},
        {"preview_id": "pv_0000000000"},
    ],
    ids=["text", "citations", "option", "asker", "unknown-id"],
)
async def test_a_preview_for_something_else_is_refused(
    desk_path: Path, change: dict[str, Any]
) -> None:
    async with Client(mcp) as c:
        pid = (await _call(c))["preview_id"]
        out = await _call(c, **{"confirm": True, "preview_id": pid, **change})
        assert not out["written"]
        assert out["message"] == previews.PREVIEW_REQUIRED
        assert await _requests(c) == []


async def test_whitespace_and_citation_order_dont_matter(desk_path: Path) -> None:
    async with Client(mcp) as c:
        pid = (await _call(c))["preview_id"]
        out = await _call(
            c,
            answer_text="  " + ANSWER.replace(" ", "  ") + "\n",
            citations=list(reversed(CITES)),
            confirm=True,
            preview_id=pid,
        )
        assert out["written"], out


async def test_a_retry_after_a_refused_save_needs_a_new_preview(
    desk_path: Path,
) -> None:
    """The desk transcripts' failure: the gate refuses the first save, the
    user restates the text, and the agent confirms again without asking."""
    async with Client(mcp) as c:
        pid = (await _call(c, answer_text=MIXED, citations=MIXED_CITES))["preview_id"]
        refused = await _call(
            c, answer_text=MIXED, citations=MIXED_CITES, confirm=True, preview_id=pid
        )
        assert not refused["written"]
        assert [p["code"] for p in refused["gate"]["problems"]] == ["mixed_editions"]

        # The restated answer with the old id, and the old answer again: both
        # refused, because the id was used up by the refused save.
        restated = await _call(c, confirm=True, preview_id=pid)
        assert not restated["written"]
        assert restated["message"] == previews.PREVIEW_REQUIRED
        again = await _call(
            c, answer_text=MIXED, citations=MIXED_CITES, confirm=True, preview_id=pid
        )
        assert again["message"] == previews.PREVIEW_REQUIRED
        assert await _requests(c) == []

        new_pid = (await _call(c))["preview_id"]
        assert new_pid != pid
        saved = await _call(c, confirm=True, preview_id=new_pid)
        assert saved["written"], saved


async def test_a_preview_id_works_once(desk_path: Path) -> None:
    async with Client(mcp) as c:
        pid = (await _call(c))["preview_id"]
        assert (await _call(c, confirm=True, preview_id=pid))["written"]
        twice = await _call(c, confirm=True, preview_id=pid)
        assert not twice["written"]
        assert len(await _requests(c)) == 1


async def test_an_idempotent_retry_replays_without_a_new_preview(
    desk_path: Path,
) -> None:
    async with Client(mcp) as c:
        pid = (await _call(c))["preview_id"]
        first = await _call(c, confirm=True, preview_id=pid, idempotency_key="k1")
        retry = await _call(c, confirm=True, preview_id=pid, idempotency_key="k1")
        assert first["written"] and retry["written"]
        assert retry["message"].startswith("Already done")
        assert len(await _requests(c)) == 1


async def test_elicitation_needs_no_preview_id(desk_path: Path) -> None:
    async def yes(message: str, response_type: Any, params: Any, ctx: Any) -> Any:
        try:
            return response_type(choice="yes")
        except TypeError:
            return {"value": "yes"}

    async with Client(mcp, elicitation_handler=yes) as c:
        out = await _call(c)
    assert out["written"], out


def test_previews_survive_a_server_restart(tmp_path: Path) -> None:
    """wxO may start the stdio server afresh between calls; the desk file
    keeps the preview."""
    path = tmp_path / "desk.sqlite"
    actor = resolve("Priya")
    cites = [CitationIn.model_validate(c) for c in CITES]
    first = DeskStore(path)
    pid = previews.issue(first, actor, "verified_copy", ANSWER, cites, None)
    first.close()
    second = DeskStore(path)
    assert previews.redeem(second, actor, pid, "verified_copy", ANSWER, cites, None)
    assert not previews.redeem(second, actor, pid, "verified_copy", ANSWER, cites, None)
    second.close()


def test_reset_clears_previews(tmp_path: Path) -> None:
    store = DeskStore(tmp_path / "desk.sqlite")
    actor = resolve("Priya")
    pid = previews.issue(store, actor, "notify", ANSWER, [], None)
    store.reset()
    assert not previews.redeem(store, actor, pid, "notify", ANSWER, [], None)
    store.close()
