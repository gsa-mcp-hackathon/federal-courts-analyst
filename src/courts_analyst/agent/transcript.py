"""The agent as an eval answerer: one turn's events → an ``AnswerRecord``.

The eval runner scores exactly what the web app streams: the answer text
(including the citation line the agent appends, issue #27), every tool call
with its structured result, and the figures the agent cited. Clarifications
can't be answered in a batch run, so they time out at once and the tool
returns its choices to the model (the same as a client without
elicitation).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from courts_analyst.agent.events import (
    AgentEvent,
    CitationEvent,
    ErrorEvent,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
    TurnEnd,
    TurnStart,
)
from courts_analyst.agent.loop import Agent, Limits
from courts_analyst.agent.providers import Provider, make_provider
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure, ToolCall


def to_record(
    question_id: str, answerer: str, events: list[AgentEvent], latency_s: float
) -> AnswerRecord:
    calls: dict[str, ToolCall] = {}
    started: dict[str, float] = {}
    text: list[str] = []
    cited: list[ReportedFigure] = []
    error: str | None = None
    end: TurnEnd | None = None
    for e in events:
        if isinstance(e, ToolCallEvent):
            calls[e.call_id] = ToolCall(name=e.tool, arguments=e.arguments)
            started[e.call_id] = time.perf_counter()
        elif isinstance(e, ToolResultEvent) and e.call_id in calls:
            c = calls[e.call_id]
            c.output, c.error = e.result, e.error
            c.latency_s = e.latency_ms / 1000
        elif isinstance(e, TextDelta):
            text.append(e.text)
        elif isinstance(e, CitationEvent) and e.span is not None:
            cited.append(
                ReportedFigure(
                    value=e.ref.value,
                    edition=e.ref.edition,
                    measure=e.ref.measure,
                    court=e.ref.court,
                )
            )
        elif isinstance(e, ErrorEvent):
            error = f"{e.code}: {e.message}"
        elif isinstance(e, TurnEnd):
            end = e
    if (
        end is not None
        and error is None
        and end.stop_reason
        in (
            "timeout",
            "max_tool_calls",
            "max_model_turns",
            "token_budget",
        )
    ):
        error = f"stopped: {end.stop_reason}"
    usage = end.usage if end else None
    return AnswerRecord(
        question_id=question_id,
        answerer=answerer,
        final_text="".join(text).strip(),
        tool_calls=list(calls.values()),
        cited_figures=cited,
        latency_s=latency_s,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        cost_usd=usage.cost_usd if usage else None,
        model_requests=usage.model_requests if usage else None,
        error=error,
    )


class AgentAnswerer:
    """The Phase 7 agent (``agent/loop.py``) behind the ``Answerer`` protocol."""

    paid = True

    def __init__(
        self,
        model: str = "anthropic:claude-sonnet-5",
        budget: Any | None = None,
        provider: Provider | None = None,
        courtlistener: bool | str = "fixture",
    ) -> None:
        from courts_analyst.evaluation.budget import Budget

        # A fresh provider per question unless one is given: each question
        # runs in its own event loop (asyncio.run, maybe in a worker thread),
        # and an async SDK client can't be shared across loops.
        self._model = model
        self._provider = provider
        model_id = provider.model if provider else model.partition(":")[2] or model
        self.name = f"agent-{model_id.removeprefix('claude-')}"
        self.budget = budget or Budget(1.00)
        self.courtlistener = courtlistener
        self.prompt_version: str | None = None

    def answer(self, item: Any) -> AnswerRecord:
        return asyncio.run(self.answer_async(item.id, item.question))

    async def answer_async(self, question_id: str, question: str) -> AnswerRecord:
        agent = Agent(
            self._provider or make_provider(self._model),
            # Nobody can answer a clarification in a batch run.
            Limits(clarify_timeout_s=0.01),
            courtlistener=self.courtlistener,
            budget=self.budget,
            close_provider=self._provider is None,
        )
        start = time.perf_counter()
        events = [e async for e in agent.run(question)]
        for e in events:
            if isinstance(e, TurnStart):
                self.prompt_version = e.prompt_version
        return to_record(question_id, self.name, events, time.perf_counter() - start)
