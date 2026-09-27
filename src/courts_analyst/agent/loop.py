"""The agent loop: one question in, a stream of typed events out.

1. The question is screened (``core.guardrails.intent.screen``). Judge-level
   and party-name requests are declined here, with a ``warning`` and the
   decline as the answer text, without calling the model. Advocacy
   requests go ahead with the neutral-framing guidance added to the system
   prompt.
2. The model is streamed; its text goes out as ``text_delta`` events.
3. Each tool call runs in turn (``tool_call`` then ``tool_result``), with
   the charts, docket cards and warnings derived from its result. A tool
   that needs the user to choose (elicitation) produces a ``clarify``
   event and waits for :meth:`Turn.answer` (the web UI POSTs the choice);
   no answer within ``clarify_timeout_s`` is treated as declined, and the
   tool returns its choices to the model instead.
4. Repeat until the model stops calling tools or a limit is hit: tool calls
   per turn, model requests per turn, tokens per turn, wall-clock time per
   turn, and (for eval runs) a shared dollar budget.
5. ``citation`` events for every official figure used, the revision line
   for revised figures the answer left incomplete (issue #27), then
   exactly one ``turn_end``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from courts_analyst.agent import derive, telemetry
from courts_analyst.agent.events import (
    AgentEvent,
    ChartEvent,
    CitationEvent,
    CitationRef,
    ClarifyEvent,
    DocketEvent,
    ErrorEvent,
    StopReason,
    TextDelta,
    Thinking,
    ToolCallEvent,
    ToolResultEvent,
    TurnEnd,
    TurnStart,
    Usage,
    WarningEvent,
)
from courts_analyst.agent.mcp_clients import ToolHost
from courts_analyst.agent.providers.base import (
    Done,
    Message,
    Provider,
    ProviderError,
    TextChunk,
    ToolResult,
    ToolResults,
    ToolUse,
    ToolUseRequested,
    UserText,
)
from courts_analyst.core.guardrails.intent import screen
from courts_analyst.core.results import Clarification

logger = logging.getLogger("courts_analyst.agent")

PROMPT_PATH = Path(__file__).with_name("system_prompt.md")


def load_system_prompt() -> tuple[str, str]:
    """(prompt text, version), with the server's own instructions appended."""
    from courts_analyst.app import INSTRUCTIONS

    raw = PROMPT_PATH.read_text()
    first, _, body = raw.partition("\n")
    version = first.split("prompt_version:", 1)[-1].split("—")[0].strip(" -!>")
    text = body.strip() + "\n\nServer instructions (courts-analyst):\n" + INSTRUCTIONS
    return text, version


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 12
    max_model_turns: int = 8
    max_tokens_per_turn: int = 250_000
    """Input plus output tokens across every model request in the turn."""
    max_output_tokens: int = 4096
    """Per model response."""
    turn_timeout_s: float = 180.0
    clarify_timeout_s: float = 300.0


class _Stop(Exception):
    def __init__(self, reason: StopReason, message: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass
class Turn:
    """A running turn: what the API needs to route a clarification answer."""

    turn_id: str
    pending: dict[str, asyncio.Future[str | None]] = field(default_factory=dict)

    def answer(self, clarify_id: str, choice: str | None) -> bool:
        fut = self.pending.get(clarify_id)
        if fut is None or fut.done():
            return False
        fut.get_loop().call_soon_threadsafe(_resolve, fut, choice)
        return True


def _resolve(fut: asyncio.Future[str | None], value: str | None) -> None:
    if not fut.done():
        fut.set_result(value)


TURNS: dict[str, Turn] = {}
"""Turns in progress in this process (the API routes clarify answers here)."""


class Agent:
    def __init__(
        self,
        provider: Provider,
        limits: Limits | None = None,
        courtlistener: bool | str = "auto",
        budget: Any | None = None,
        system_prompt: tuple[str, str] | None = None,
        host_factory: Callable[..., ToolHost] = ToolHost,
        close_provider: bool = False,
    ) -> None:
        self.provider = provider
        self.limits = limits or Limits()
        self.courtlistener = courtlistener
        self.budget = budget
        self.system_prompt, self.prompt_version = system_prompt or load_system_prompt()
        self.host_factory = host_factory
        # Set when the agent made its provider for this one turn (API, eval):
        # its HTTP client is closed when the turn ends.
        self.close_provider = close_provider

    async def run(
        self, question: str, turn_id: str | None = None
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn. Events are produced by a background task, so a
        clarification can wait for the user while the stream stays open;
        closing the stream early cancels the turn."""
        turn = Turn(turn_id or uuid.uuid4().hex[:16])
        TURNS[turn.turn_id] = turn
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        seq = 0

        def emit(event: AgentEvent) -> None:
            nonlocal seq
            event.seq = seq
            seq += 1
            queue.put_nowait(event)

        async def produce() -> None:
            try:
                await self._run(question, turn, emit)
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(produce())
        try:
            while (event := await queue.get()) is not None:
                yield event
            await task
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            TURNS.pop(turn.turn_id, None)
            if self.close_provider:
                await self.provider.aclose()

    # ── internals ────────────────────────────────────────────────────────────

    async def _run(
        self, question: str, turn: Turn, emit: Callable[[AgentEvent], None]
    ) -> None:
        start = time.perf_counter()
        usage = Usage()
        emit(
            TurnStart(
                turn_id=turn.turn_id,
                model=self.provider.model,
                provider=self.provider.name,
                prompt_version=self.prompt_version,
            )
        )
        stop: StopReason = "end_turn"
        with telemetry.span(
            "agent.turn",
            "AGENT",
            **{
                "session.id": turn.turn_id,
                "input.value": telemetry.content(question),
                "llm.model_name": self.provider.model,
                "agent.prompt_version": self.prompt_version,
            },
        ) as agent_span:
            s = screen(question)
            if s.decline is not None:
                d = s.decline
                emit(
                    WarningEvent(
                        code=d.reason,
                        message=d.message,
                        severity="block",
                        source="guardrail",
                    )
                )
                text = d.message + (f" {d.alternative}" if d.alternative else "")
                emit(TextDelta(text=text))
                agent_span.set_attribute("output.value", telemetry.content(text))
                emit(
                    TurnEnd(
                        usage=usage,
                        latency_ms=(time.perf_counter() - start) * 1000,
                        stop_reason="declined",
                    )
                )
                return
            system = self.system_prompt
            if s.intent == "advocacy" and s.guidance:
                system += "\n\nThis request asks for advocacy. " + s.guidance
                emit(
                    WarningEvent(
                        code="advocacy",
                        message="Answered with neutral, sourced facts; whether to "
                        "act is a policy decision for Congress.",
                        severity="info",
                        source="guardrail",
                    )
                )
            answer: list[str] = []
            refs: list[tuple[CitationRef, str]] = []
            try:
                async with asyncio.timeout(self.limits.turn_timeout_s):
                    stop = await self._loop(
                        question, turn, system, emit, usage, answer, refs
                    )
            except TimeoutError:
                stop = "timeout"
                emit(
                    WarningEvent(
                        code="timeout",
                        message=f"Stopped after {self.limits.turn_timeout_s:.0f} s.",
                        source="agent",
                    )
                )
            except _Stop as exc:
                stop = exc.reason
                emit(WarningEvent(code=exc.reason, message=exc.message, source="agent"))
            except ProviderError as exc:
                stop = "error"
                emit(ErrorEvent(code=exc.code, message=str(exc)))
            except Exception as exc:  # the turn must still end with turn_end
                logger.exception("agent turn failed")
                stop = "error"
                emit(ErrorEvent(code="internal_error", message=type(exc).__name__))

            text = "".join(answer)
            footer = derive.revision_footer(text, [r for r, _ in refs])
            if footer and stop not in ("error",):
                emit(TextDelta(text=footer))
                text += footer
            seen: set[str] = set()
            for ref, call_id in refs:
                if ref.citation in seen:
                    continue
                seen.add(ref.citation)
                emit(
                    CitationEvent(
                        ref=ref, span=derive.find_span(text, ref.value), call_id=call_id
                    )
                )
            agent_span.set_attribute("output.value", telemetry.content(text))
            agent_span.set_attribute("agent.stop_reason", stop)
        emit(
            TurnEnd(
                usage=usage,
                latency_ms=(time.perf_counter() - start) * 1000,
                stop_reason=stop,
            )
        )

    async def _loop(
        self,
        question: str,
        turn: Turn,
        system: str,
        emit: Callable[[AgentEvent], None],
        usage: Usage,
        answer: list[str],
        refs: list[tuple[CitationRef, str]],
    ) -> StopReason:
        lim = self.limits

        async def on_elicit(c: Clarification) -> str | None:
            clarify_id = uuid.uuid4().hex[:12]
            fut: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
            turn.pending[clarify_id] = fut
            emit(
                ClarifyEvent(
                    turn_id=turn.turn_id, clarify_id=clarify_id, clarification=c
                )
            )
            try:
                choice = await asyncio.wait_for(fut, lim.clarify_timeout_s)
            except TimeoutError:
                choice = None
            finally:
                turn.pending.pop(clarify_id, None)
            if choice is not None and choice not in {ch.value for ch in c.choices}:
                choice = None
            return choice

        messages: list[Message] = [UserText(question)]
        async with self.host_factory(
            on_elicit=on_elicit, courtlistener=self.courtlistener
        ) as host:
            tools = host.tools
            emit(Thinking(text="Reading the question…"))
            for _ in range(lim.max_model_turns):
                if usage.input_tokens + usage.output_tokens >= lim.max_tokens_per_turn:
                    raise _Stop("token_budget", "Token budget for this turn used up.")
                if self.budget is not None:
                    try:
                        self.budget.check()
                    except Exception as exc:
                        raise _Stop("token_budget", str(exc)) from exc
                done = await self._model_request(system, messages, tools, emit, answer)
                self._charge(done, usage)
                messages.append(done.turn)
                if done.stop_reason == "refusal":
                    return "refusal"
                uses = done.turn.tool_uses
                if not uses:
                    return "end_turn"
                if usage.tool_calls + len(uses) > lim.max_tool_calls:
                    raise _Stop(
                        "max_tool_calls",
                        f"Stopped at the limit of {lim.max_tool_calls} tool calls.",
                    )
                results = []
                for use in uses:
                    results.append(await self._tool(host, use, emit, usage, refs))
                messages.append(ToolResults(results))
                if answer and not answer[-1].endswith(("\n", " ")):
                    # Keep text from separate model responses apart.
                    answer.append("\n\n")
                    emit(TextDelta(text="\n\n"))
            raise _Stop(
                "max_model_turns",
                f"Stopped after {lim.max_model_turns} model requests.",
            )

    async def _model_request(
        self,
        system: str,
        messages: list[Message],
        tools: list[Any],
        emit: Callable[[AgentEvent], None],
        answer: list[str],
    ) -> Done:
        done: Done | None = None
        with telemetry.span(
            "llm.request",
            "LLM",
            **{
                "llm.model_name": self.provider.model,
                "llm.provider": self.provider.name,
            },
        ) as s:
            async for ev in self.provider.stream(
                system, messages, tools, self.limits.max_output_tokens
            ):
                if isinstance(ev, TextChunk):
                    answer.append(ev.text)
                    emit(TextDelta(text=ev.text))
                elif isinstance(ev, ToolUseRequested):
                    pass  # read from the final turn, in order
                elif isinstance(ev, Done):
                    done = ev
            if done is None:
                raise ProviderError("model_api_error", "stream ended without Done")
            u = done.usage
            s.set_attribute("llm.token_count.prompt", u.total_input)
            s.set_attribute("llm.token_count.completion", u.output_tokens)
            s.set_attribute("llm.token_count.total", u.total_input + u.output_tokens)
            s.set_attribute(
                "llm.token_count.prompt_details.cache_read", u.cache_read_tokens
            )
            s.set_attribute("llm.stop_reason", done.stop_reason)
        return done

    def _charge(self, done: Done, usage: Usage) -> None:
        u = done.usage
        usage.input_tokens += u.total_input
        usage.output_tokens += u.output_tokens
        usage.model_requests += 1
        from courts_analyst.evaluation.budget import PRICES, cost_usd

        if self.provider.model in PRICES:
            spent = cost_usd(
                self.provider.model,
                u.input_tokens,
                u.output_tokens,
                u.cache_read_tokens,
                u.cache_write_tokens,
            )
            usage.cost_usd += spent
            if self.budget is not None:
                self.budget.charge(spent)

    async def _tool(
        self,
        host: ToolHost,
        use: ToolUse,
        emit: Callable[[AgentEvent], None],
        usage: Usage,
        refs: list[tuple[CitationRef, str]],
    ) -> ToolResult:
        server = host.server_for(use.name) or "courts-analyst"
        emit(
            ToolCallEvent(
                call_id=use.id,
                server=server,
                tool=use.name,
                arguments=use.arguments,
            )
        )
        usage.tool_calls += 1
        with telemetry.span(
            "tool." + use.name,
            "TOOL",
            **{
                "tool.name": use.name,
                "tool.server": server,
                "tool.parameters": telemetry.content(use.arguments),
            },
        ) as s:
            out = await host.call(use.name, use.arguments)
            status = (
                "error"
                if out.error
                else str((out.structured or {}).get("status", "ok"))
                if out.server != "courtlistener"
                else "ok"
            )
            s.set_attribute("tool.status", status)
        emit(
            ToolResultEvent(
                call_id=use.id,
                server=server,
                tool=use.name,
                status=status,
                result=out.structured,
                error=out.error,
                latency_ms=round(out.latency_ms, 1),
            )
        )
        seen = set()
        for w in derive.warnings_from(out.structured):
            if w["message"] in seen:
                continue
            seen.add(w["message"])
            emit(
                WarningEvent(
                    code=w["code"],
                    message=w["message"],
                    severity=w["severity"],
                    source="guardrail" if w["severity"] == "block" else "tool",
                )
            )
        if chart := derive.chart_for(use.name, out.structured, use.id):
            emit(ChartEvent(spec=chart))
        for card in derive.docket_cards(use.name, out.structured):
            emit(DocketEvent(card=card, call_id=use.id))
        refs.extend((r, use.id) for r in derive.figure_refs(use.name, out.structured))
        return ToolResult(use.id, out.text, is_error=out.error is not None)


def transcript_text(events: list[AgentEvent]) -> str:
    """The answer text of a finished turn."""
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def dumps(event: AgentEvent) -> str:
    return json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
