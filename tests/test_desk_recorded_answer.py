"""The verification gate on a real agent answer (web/public/demo): the
recorded FY2020 storyline cites two figures, quotes several more that its
tools computed, and includes docket numbers, dates and links. Re-running the
turn's tools on the server backs the computed numbers; nothing else is
trusted from the request."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

RECORDING = Path(__file__).resolve().parents[1] / "web/public/demo/fy2020-storyline.sse"


def _turn() -> dict[str, Any]:
    events = [
        json.loads(line[6:])
        for line in RECORDING.read_text().splitlines()
        if line.startswith("data: ")
    ]
    return {
        "text": "".join(e["text"] for e in events if e["type"] == "text_delta"),
        "citations": [
            {
                k: e["ref"][k]
                for k in ("measure", "court", "fiscal_year", "edition", "value")
            }
            for e in events
            if e["type"] == "citation"
        ],
        "tool_calls": [
            {"tool": e["tool"], "arguments": e["arguments"]}
            for e in events
            if e["type"] == "tool_call"
        ],
    }


@pytest.fixture
def desk_api(api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from courts_analyst.api.routes import desk
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "desk_store_path", tmp_path / "desk.sqlite")
    monkeypatch.setattr(desk, "_limiter", None)
    return api


def _submit(api: Any, turn: dict[str, Any], **extra: Any) -> Any:
    return api.post(
        "/api/desk/requests",
        headers={"x-desk-account": "priya"},
        json={
            "option": "ask_office",
            "question": "Why did weighted civil filings per judgeship change in FY2020?",
            "answer_text": turn["text"],
            "citations": turn["citations"],
            "inquiry": {
                "measure": "weighted_civil_filings_per_judgeship",
                "fiscal_year": 2020,
            },
            **extra,
        },
    ).json()["data"]


def test_without_the_tool_calls_the_computed_numbers_are_refused(
    desk_api: Any,
) -> None:
    out = _submit(desk_api, _turn())
    assert not out["written"]
    refused = {p["number"] for p in out["gate"]["problems"]}
    assert {"206", "201,017"} <= refused
    # Docket numbers, dates and link targets are never treated as statistics.
    assert not refused & {"8", "7", "13", "22", "07", "06"}


def test_rerunning_the_turns_tools_backs_the_computed_numbers(desk_api: Any) -> None:
    turn = _turn()
    out = _submit(desk_api, turn, tool_calls=turn["tool_calls"])
    computed = {c["number"]: c["source"] for c in out["gate"]["computed"]}
    # Official figures and points the tools computed, matched by re-running.
    assert {"206", "211", "322", "332", "232"} <= set(computed)
    assert computed["206"] == "explain_change"
    # The recording was made on the full IDB; the fixture holds a sample, so
    # the re-run's case counts differ and those two stay refused, as they
    # should when the server's own data doesn't reproduce a number.
    refused = {p["number"] for p in out["gate"]["problems"]}
    assert refused == {"201,017", "202,463"}


def test_values_in_the_request_are_never_trusted(desk_api: Any) -> None:
    turn = _turn()
    calls = [
        {"tool": "open_request", "arguments": {"option": "notify", "question": "x"}}
    ]
    out = _submit(desk_api, turn, tool_calls=calls)
    assert not out["written"]  # desk tools are not re-runnable
