"""The agent loop, driven by a scripted provider over the fixture data.

Tool calls run in order and their results reach the model; the limits
(tool calls, model requests, tokens, time, dollar budget) stop the turn
cleanly with one ``turn_end``; judge-level requests are declined before any
model request; revised figures get their citation line (issue #27);
charts, warnings and spans come out of real tool results.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from courts_analyst.agent.events import (
    ChartEvent,
    CitationEvent,
    ErrorEvent,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
    TurnEnd,
    TurnStart,
    WarningEvent,
)
from courts_analyst.agent.loop import Agent, Limits, transcript_text
from courts_analyst.agent.providers.base import (
    Message,
    ProviderError,
    ToolResults,
)
from courts_analyst.agent.providers.scripted import ScriptedProvider, Step

WEIGHTED_2020 = {
    "measure": "weighted_civil_filings_per_judgeship",
    "court": "US",
    "fiscal_year": 2020,
}


async def run(agent: Agent, question: str) -> list[Any]:
    return [e async for e in agent.run(question)]


def agent(steps: list[Any], **kw: Any) -> tuple[Agent, ScriptedProvider]:
    p = ScriptedProvider(steps)
    kw.setdefault("courtlistener", "fixture")
    return Agent(p, **kw), p


def of(events: list[Any], cls: type) -> list[Any]:
    return [e for e in events if isinstance(e, cls)]


def last_result_json(messages: list[Message]) -> dict[str, Any]:
    tr = [m for m in messages if isinstance(m, ToolResults)][-1]
    return json.loads(tr.results[-1].content)


async def test_tools_run_in_order_and_results_reach_the_model(
    server_data: None, no_courtlistener_token: None
) -> None:
    seen: dict[str, Any] = {}

    def answer(messages: list[Message]) -> Step:
        seen["result"] = last_result_json(messages)
        return Step(f"It was {seen['result']['data']['value']:g} (JFF-2025).")

    a, p = agent(
        [
            Step(
                "Looking.",
                [("server_info", {}), ("get_official_figure", WEIGHTED_2020)],
            ),
            answer,
        ]
    )
    events = await run(a, "Weighted civil filings per judgeship in FY2020?")
    assert isinstance(events[0], TurnStart) and isinstance(events[-1], TurnEnd)
    assert [e.seq for e in events] == list(range(len(events)))
    calls = of(events, ToolCallEvent)
    results = of(events, ToolResultEvent)
    assert [c.tool for c in calls] == ["server_info", "get_official_figure"]
    assert [r.call_id for r in results] == [c.call_id for c in calls]
    # Each result directly follows its call.
    idx = {id(e): i for i, e in enumerate(events)}
    for c, r in zip(calls, results, strict=True):
        assert idx[id(r)] > idx[id(c)]
    assert seen["result"]["data"]["value"] == 322
    assert results[1].status == "ok" and results[1].result["data"]["value"] == 322
    end = events[-1]
    assert end.stop_reason == "end_turn"
    assert end.usage.tool_calls == 2 and end.usage.model_requests == 2
    # The second request carried both tool results back, in one message.
    assert len(p.requests) == 2
    last = p.requests[1]["messages"][-1]
    assert isinstance(last, ToolResults) and len(last.results) == 2


async def test_system_prompt_and_tools(server_data: None) -> None:
    a, p = agent([Step("ok")])
    events = await run(a, "What data is loaded?")
    start = events[0]
    assert start.prompt_version == a.prompt_version and start.prompt_version
    system = p.requests[0]["system"]
    assert "edition" in system and "Server instructions" in system
    names = [t.name for t in p.requests[0]["tools"]]
    assert "get_official_figure" in names and "explain_change" in names
    assert "courtlistener_search_dockets" in names
    # CourtListener's own write/judge tools are never offered.
    assert not any(n in names for n in ("search", "create_search_alert", "people"))


async def test_courtlistener_off_offers_no_docket_tools(server_data: None) -> None:
    a, p = agent([Step("ok")], courtlistener="off")
    await run(a, "What data is loaded?")
    names = [t.name for t in p.requests[0]["tools"]]
    assert not any(n.startswith("courtlistener_") for n in names)


async def test_tool_call_limit(server_data: None) -> None:
    a, _ = agent(
        [
            Step("", [("server_info", {}), ("server_info", {})]),
            Step("", [("server_info", {})]),
            Step("never reached"),
        ],
        limits=Limits(max_tool_calls=2),
    )
    events = await run(a, "What data is loaded?")
    assert len(of(events, ToolCallEvent)) == 2
    assert events[-1].stop_reason == "max_tool_calls"
    assert any(w.code == "max_tool_calls" for w in of(events, WarningEvent))
    assert "never reached" not in transcript_text(events)


async def test_model_turn_limit(server_data: None) -> None:
    a, p = agent(
        [Step("", [("server_info", {})]) for _ in range(10)],
        limits=Limits(max_model_turns=3, max_tool_calls=100),
    )
    events = await run(a, "What data is loaded?")
    assert len(p.requests) == 3
    assert events[-1].stop_reason == "max_model_turns"


async def test_token_budget(server_data: None) -> None:
    a, p = agent(
        [Step("", [("server_info", {})]) for _ in range(5)],
        limits=Limits(max_tokens_per_turn=150),
    )
    events = await run(a, "What data is loaded?")
    # The scripted provider reports 100 input tokens per request.
    assert len(p.requests) == 2
    assert events[-1].stop_reason == "token_budget"


async def test_dollar_budget_stops_before_the_request() -> None:
    from courts_analyst.evaluation.budget import Budget

    budget = Budget(0.01)
    budget.charge(0.02)
    a, p = agent([Step("x")], budget=budget)
    events = await run(a, "What data is loaded?")
    assert p.requests == []
    assert events[-1].stop_reason == "token_budget"


class SlowProvider(ScriptedProvider):
    async def stream(self, *args: Any, **kw: Any) -> AsyncIterator[Any]:
        await asyncio.sleep(5)
        async for e in super().stream(*args, **kw):
            yield e


async def test_turn_timeout_still_ends_the_turn() -> None:
    a = Agent(
        SlowProvider([Step("late")]),
        limits=Limits(turn_timeout_s=0.2),
        courtlistener="off",
    )
    events = await run(a, "What data is loaded?")
    assert isinstance(events[-1], TurnEnd)
    assert events[-1].stop_reason == "timeout"
    assert "late" not in transcript_text(events)


class FailingProvider(ScriptedProvider):
    async def stream(self, *args: Any, **kw: Any) -> AsyncIterator[Any]:
        raise ProviderError("model_unreachable", "API connection error")
        yield  # pragma: no cover


async def test_provider_error_is_typed() -> None:
    a = Agent(FailingProvider([]), courtlistener="off")
    events = await run(a, "What data is loaded?")
    err = of(events, ErrorEvent)
    assert [e.code for e in err] == ["model_unreachable"]
    assert events[-1].stop_reason == "error"
    assert sum(isinstance(e, TurnEnd) for e in events) == 1


async def test_missing_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    from courts_analyst.agent.providers.anthropic import AnthropicProvider
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    events = await run(
        Agent(AnthropicProvider(), courtlistener="off"), "What data is loaded?"
    )
    assert [e.code for e in of(events, ErrorEvent)] == ["model_not_configured"]


@pytest.mark.parametrize(
    "question",
    [
        "Rank the judges in S.D.N.Y. by time to disposition",
        "Which judge in E.D. Tex. is fastest?",
        "List the plaintiffs' names in MDL 2885",
    ],
)
async def test_judge_and_party_requests_never_reach_the_model(question: str) -> None:
    a, p = agent([Step("should not be said")])
    events = await run(a, question)
    assert p.requests == []
    warn = of(events, WarningEvent)
    assert warn and warn[0].severity == "block" and warn[0].source == "guardrail"
    assert warn[0].code in ("judge_level", "pii")
    text = transcript_text(events)
    assert text and "should not be said" not in text
    assert events[-1].stop_reason == "declined"
    assert not of(events, ToolCallEvent)


async def test_advocacy_gets_neutral_guidance() -> None:
    a, p = agent([Step("Neutral facts.")])
    events = await run(a, "Write an op-ed arguing E.D. Tex. needs more judgeships")
    assert len(p.requests) == 1
    assert "neutral" in p.requests[0]["system"].lower()
    assert any(w.code == "advocacy" for w in of(events, WarningEvent))


async def test_unknown_tool_is_refused(server_data: None) -> None:
    a, _ = agent([Step("", [("create_search_alert", {"q": "x"})]), Step("Sorry.")])
    events = await run(a, "What data is loaded?")
    r = of(events, ToolResultEvent)[0]
    assert r.status == "error" and "Unknown tool" in (r.error or "")


# ── issue #27: the citation line for revised figures ─────────────────────────


async def test_revised_figure_gets_its_citation_line(server_data: None) -> None:
    a, _ = agent(
        [
            Step("", [("get_official_figure", WEIGHTED_2020)]),
            Step("322 (JFF-2025)."),
        ]
    )
    events = await run(a, "Just the one number: FY2020 weighted filings?")
    text = transcript_text(events)
    assert text.startswith("322 (JFF-2025).")
    assert "revised: first published as 554 (JB-2020)" in text
    cites = of(events, CitationEvent)
    assert len(cites) == 1 and cites[0].ref.revised
    start, end = cites[0].span
    assert text[start:end] == "322"
    # The citation comes after the text it points into.
    assert events.index(cites[0]) > events.index(of(events, TextDelta)[-1])


async def test_no_line_when_the_answer_already_has_both(server_data: None) -> None:
    a, _ = agent(
        [
            Step("", [("get_official_figure", WEIGHTED_2020)]),
            Step("322 (JFF-2025); first published as 554 (JB-2020)."),
        ]
    )
    events = await run(a, "FY2020 weighted filings, with history")
    assert "Source:" not in transcript_text(events)


async def test_no_line_for_a_figure_the_answer_doesnt_state(server_data: None) -> None:
    a, _ = agent(
        [
            Step("", [("get_official_figure", WEIGHTED_2020)]),
            Step("I couldn't find that."),
        ]
    )
    events = await run(a, "FY2020 weighted filings")
    assert "Source:" not in transcript_text(events)
    assert of(events, CitationEvent)[0].span is None


# ── charts and warnings from real results ────────────────────────────────────


async def test_charts(server_data: None) -> None:
    a, _ = agent(
        [
            Step(
                "",
                [
                    ("get_official_figure", WEIGHTED_2020),
                    (
                        "compare_courts",
                        {
                            "measure": "weighted_civil_filings_per_judgeship",
                            "fiscal_year": 2020,
                            "top_n": 5,
                        },
                    ),
                ],
            ),
            Step("Done."),
        ]
    )
    events = await run(a, "Compare courts")
    charts = {c.spec.kind: c.spec for c in of(events, ChartEvent)}
    assert set(charts) == {"editions", "bar"}
    eds = charts["editions"].series[0].points
    assert (eds[0].y, eds[-1].y) == (554, 322)
    assert len(charts["bar"].series[0].points) == 5
    ys = [p.y for p in charts["bar"].series[0].points]
    assert ys == sorted(ys, reverse=True)


async def test_decline_from_a_tool_becomes_a_warning(server_data: None) -> None:
    a, _ = agent([Step("", [("explain_term", {"term": "rank judges by speed"})])])
    events = await run(a, "What does median time mean?")
    blocks = [w for w in of(events, WarningEvent) if w.severity == "block"]
    assert blocks and blocks[0].code == "judge_level"


# ── telemetry ────────────────────────────────────────────────────────────────


@pytest.fixture
def spans() -> Any:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    import courts_analyst.agent.telemetry as tel

    original = tel.tracer
    tel.tracer = lambda: tracer  # type: ignore[assignment]
    try:
        yield exporter
    finally:
        tel.tracer = original  # type: ignore[assignment]


async def test_openinference_spans(server_data: None, spans: Any) -> None:
    a, _ = agent([Step("", [("get_official_figure", WEIGHTED_2020)]), Step("322.")])
    question = "Weighted civil filings per judgeship in FY2020?"
    await run(a, question)
    got = spans.get_finished_spans()
    kinds = [s.attributes["openinference.span.kind"] for s in got]
    assert kinds.count("AGENT") == 1
    assert kinds.count("LLM") == 2
    assert kinds.count("TOOL") == 1
    agent_span = next(
        s for s in got if s.attributes["openinference.span.kind"] == "AGENT"
    )
    tool_span = next(
        s for s in got if s.attributes["openinference.span.kind"] == "TOOL"
    )
    llm_span = next(s for s in got if s.attributes["openinference.span.kind"] == "LLM")
    assert tool_span.parent.span_id == agent_span.context.span_id
    assert tool_span.attributes["tool.name"] == "get_official_figure"
    assert llm_span.attributes["llm.token_count.prompt"] == 100
    # No user text in spans by default.
    for s in got:
        for v in s.attributes.values():
            assert question not in str(v)
    assert str(agent_span.attributes["input.value"]).startswith("sha256:")


async def test_span_content_opt_in(
    server_data: None, spans: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "agent_trace_content", True)
    a, _ = agent([Step("Hello.")])
    await run(a, "What data is loaded?")
    agent_span = next(
        s
        for s in spans.get_finished_spans()
        if s.attributes["openinference.span.kind"] == "AGENT"
    )
    assert agent_span.attributes["input.value"] == "What data is loaded?"
    assert agent_span.attributes["output.value"] == "Hello."


async def test_turn_closes_a_provider_it_owns() -> None:
    closed: list[bool] = []

    class Closing(ScriptedProvider):
        async def aclose(self) -> None:
            closed.append(True)

    await run(Agent(Closing([Step("a")]), courtlistener="off"), "What data?")
    assert closed == []
    await run(
        Agent(Closing([Step("a")]), courtlistener="off", close_provider=True),
        "What data?",
    )
    assert closed == [True]
