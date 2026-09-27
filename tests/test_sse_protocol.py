"""The SSE event protocol over real HTTP.

Every stream starts with ``turn_start`` and ends with exactly one
``turn_end``; ``seq`` and the SSE ``id`` count up from 0; every event
validates against its Pydantic model and against the JSON Schema exported
to the web app.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest

from courts_analyst.agent.events import EVENT_ADAPTER, EVENT_TYPES, TextDelta
from courts_analyst.agent.loop import Agent
from courts_analyst.agent.providers.scripted import ScriptedProvider, Step
from courts_analyst.api import sse

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "web/src/api/schemas/agent-event.schema.json"
    ).read_text()
)


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":") or ":" not in line:
                continue
            k, _, v = line.partition(":")
            fields[k] = v.removeprefix(" ")
        if "data" in fields:
            events.append(
                {"id": fields.get("id"), "event": fields.get("event"),
                 "data": json.loads(fields["data"])}
            )  # fmt: skip
    return events


def storyline_agent() -> Agent:
    return Agent(
        ScriptedProvider(
            [
                Step(
                    "Checking the tables.",
                    [
                        (
                            "get_official_figure",
                            {
                                "measure": "weighted_civil_filings_per_judgeship",
                                "fiscal_year": 2020,
                            },
                        ),
                        (
                            "explain_change",
                            {
                                "measure": "civil_cases_filed",
                                "court": "US",
                                "period_from": 2019,
                                "period_to": 2020,
                            },
                        ),
                    ],
                ),
                Step("Weighted filings were 322 (JFF-2025)."),
            ]
        ),
        courtlistener="fixture",
    )


def test_event_order_and_schemas(live_api: Any) -> None:
    live_api.use_agent(storyline_agent)
    with httpx.stream(
        "POST",
        f"{live_api.base}/api/ask",
        json={"question": "Why did FY2020 civil filings change?"},
        timeout=30,
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        body = r.read().decode()
    events = parse_sse(body)
    types = [e["event"] for e in events]
    assert types[0] == "turn_start" and types[-1] == "turn_end"
    assert types.count("turn_start") == 1 and types.count("turn_end") == 1
    assert [int(e["id"]) for e in events] == list(range(len(events)))
    assert [e["data"]["seq"] for e in events] == list(range(len(events)))
    for e in events:
        assert e["event"] == e["data"]["type"] and e["event"] in EVENT_TYPES
        EVENT_ADAPTER.validate_python(e["data"])
        jsonschema.validate(e["data"], SCHEMA)
    # The storyline: tool calls, results, a chart, a citation, streamed text.
    assert {"tool_call", "tool_result", "chart", "citation", "text_delta"} <= set(types)
    assert types.index("tool_call") < types.index("tool_result")
    assert types.index("citation") > max(
        i for i, t in enumerate(types) if t == "tool_result"
    )


def test_decline_stream(live_api: Any) -> None:
    live_api.use_agent(storyline_agent)
    r = httpx.post(
        f"{live_api.base}/api/ask",
        json={"question": "Rank the judges in S.D.N.Y. by speed"},
        timeout=30,
    )
    types = [e["event"] for e in parse_sse(r.text)]
    assert types == ["turn_start", "warning", "text_delta", "turn_end"]
    end = parse_sse(r.text)[-1]["data"]
    assert end["stop_reason"] == "declined" and end["usage"]["model_requests"] == 0


def test_schema_covers_every_event_type() -> None:
    names = {
        v["properties"]["type"]["const"] for v in SCHEMA["$defs"].values()
        if "type" in v.get("properties", {})
    }  # fmt: skip
    assert set(EVENT_TYPES) <= names


async def test_keepalive_while_waiting() -> None:
    async def slow() -> AsyncIterator[Any]:
        await asyncio.sleep(0.25)
        yield TextDelta(text="hi")

    chunks = [c async for c in sse.stream(slow(), keepalive_s=0.05)]
    assert chunks[0] == ": keep-alive\n\n"
    assert chunks[-1].startswith("id: 0\nevent: text_delta\n")


async def test_closing_the_stream_cancels_the_turn(server_data: None) -> None:
    """A client that goes away mid-turn stops the agent (no orphan work)."""
    from courts_analyst.agent.loop import TURNS

    started = asyncio.Event()

    class Hanging(ScriptedProvider):
        async def stream(self, *a: Any, **k: Any) -> AsyncIterator[Any]:
            started.set()
            await asyncio.sleep(30)
            yield  # pragma: no cover

    agent = Agent(Hanging([]), courtlistener="off")
    gen = sse.stream(agent.run("What data?"))
    first = await gen.__anext__()
    assert "turn_start" in first
    await started.wait()
    await gen.aclose()
    assert not TURNS


@pytest.mark.parametrize("question", ["", " " * 3])
def test_blank_questions_rejected(live_api: Any, question: str) -> None:
    r = httpx.post(f"{live_api.base}/api/ask", json={"question": question})
    assert r.status_code == 422
