"""Clarification over HTTP: an ambiguous measure makes the tool ask, the
stream carries a ``clarify`` event and waits, the choice is POSTed, and the
same stream resumes with the chosen measure."""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx

from courts_analyst.agent.loop import Agent, Limits
from courts_analyst.agent.providers.base import Message, ToolResults
from courts_analyst.agent.providers.scripted import ScriptedProvider, Step

AMBIGUOUS = {"measure": "filings_per_judgeship", "fiscal_year": 2020}


def _answer(messages: list[Message]) -> Step:
    result = json.loads(
        [m for m in messages if isinstance(m, ToolResults)][-1].results[0].content
    )
    if result["status"] != "ok":
        return Step(f"Status {result['status']}.")
    d = result["data"]
    return Step(f"{d['measure_label']}: {d['value']:g} ({d['edition']}).")


def _agent(**limits: Any) -> Agent:
    return Agent(
        ScriptedProvider([Step("", [("get_official_figure", AMBIGUOUS)]), _answer]),
        Limits(**limits),
        courtlistener="off",
    )


def _stream_until_clarify(
    base: str, question: str, on_clarify: Any
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with httpx.stream(
        "POST", f"{base}/api/ask", json={"question": question}, timeout=30
    ) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                data = next(
                    (ln[6:] for ln in block.splitlines() if ln.startswith("data: ")),
                    None,
                )
                if data is None:
                    continue
                ev = json.loads(data)
                events.append(ev)
                if ev["type"] == "clarify":
                    # Answer from another connection while this one stays open.
                    threading.Thread(target=on_clarify, args=(ev,)).start()
    return events


def test_choice_resumes_the_same_stream(live_api: Any) -> None:
    live_api.use_agent(_agent)
    posted: list[int] = []

    def answer(ev: dict[str, Any]) -> None:
        r = httpx.post(
            f"{live_api.base}/api/ask/{ev['turn_id']}/clarify",
            json={
                "clarify_id": ev["clarify_id"],
                "choice": "civil_filings_per_judgeship",
            },
        )
        posted.append(r.status_code)
        # A second answer to the same question is refused.
        again = httpx.post(
            f"{live_api.base}/api/ask/{ev['turn_id']}/clarify",
            json={
                "clarify_id": ev["clarify_id"],
                "choice": "civil_filings_per_judgeship",
            },
        )
        posted.append(again.status_code)

    events = _stream_until_clarify(
        live_api.base, "Filings per judgeship in FY2020?", answer
    )
    types = [e["type"] for e in events]
    assert "clarify" in types
    clar = next(e for e in events if e["type"] == "clarify")
    assert clar["clarification"]["parameter"] == "measure"
    assert len(clar["clarification"]["choices"]) == 4
    assert posted == [202, 409]
    # The tool result arrives after the clarify event, with the chosen measure.
    result = next(e for e in events if e["type"] == "tool_result")
    assert types.index("clarify") < types.index("tool_result")
    assert result["status"] == "ok"
    assert result["result"]["data"]["measure"] == "civil_filings_per_judgeship"
    assert result["result"]["data"]["value"] == 675
    text = "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert "675 (JFF-2025)" in text
    assert types[-1] == "turn_end" and events[-1]["stop_reason"] == "end_turn"


def test_declining_returns_the_choices_to_the_model(live_api: Any) -> None:
    live_api.use_agent(_agent)

    def decline(ev: dict[str, Any]) -> None:
        httpx.post(
            f"{live_api.base}/api/ask/{ev['turn_id']}/clarify",
            json={"clarify_id": ev["clarify_id"], "choice": None},
        )

    events = _stream_until_clarify(live_api.base, "Filings per judgeship?", decline)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "needs_clarification"
    assert "Status needs_clarification" in "".join(
        e["text"] for e in events if e["type"] == "text_delta"
    )


def test_unknown_choice_is_treated_as_declined(live_api: Any) -> None:
    live_api.use_agent(_agent)

    def bogus(ev: dict[str, Any]) -> None:
        httpx.post(
            f"{live_api.base}/api/ask/{ev['turn_id']}/clarify",
            json={"clarify_id": ev["clarify_id"], "choice": "drop_tables"},
        )

    events = _stream_until_clarify(live_api.base, "Filings per judgeship?", bogus)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "needs_clarification"


def test_no_answer_times_out(live_api: Any) -> None:
    live_api.use_agent(lambda: _agent(clarify_timeout_s=0.2))
    events = _stream_until_clarify(
        live_api.base, "Filings per judgeship?", lambda ev: None
    )
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["status"] == "needs_clarification"
    assert events[-1]["type"] == "turn_end"
