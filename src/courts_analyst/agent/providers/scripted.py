"""A provider that plays back a script: for tests, and for running the web
app and demos without a model key.

Each step is one model response: some text and zero or more tool calls. A
step can be a callable that receives the conversation so far (to answer
with values taken from a tool result, or to check what the model saw).
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from courts_analyst.agent.providers.base import (
    AssistantTurn,
    Done,
    Message,
    ProviderEvent,
    TextChunk,
    TokenUsage,
    ToolSpec,
    ToolUse,
    ToolUseRequested,
)


@dataclass
class Step:
    text: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    stop_reason: str | None = None


ScriptStep = Step | Callable[[list[Message]], Step]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, steps: Sequence[ScriptStep], model: str = "scripted") -> None:
        self.model = model
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []
        self._ids = itertools.count(1)

    async def aclose(self) -> None:
        return None

    async def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(
            {"system": system, "messages": list(messages), "tools": list(tools)}
        )
        if not self.steps:
            step = Step("")
        else:
            nxt = self.steps.pop(0)
            step = nxt(list(messages)) if callable(nxt) else nxt
        # Stream in a few pieces, as a real model would.
        words = step.text.split(" ")
        for i, w in enumerate(words):
            piece = w if i == len(words) - 1 else w + " "
            if piece:
                yield TextChunk(piece)
        uses = [
            ToolUse(f"call_{next(self._ids)}", name, args)
            for name, args in step.tool_calls
        ]
        for u in uses:
            yield ToolUseRequested(u)
        stop = step.stop_reason or ("tool_use" if uses else "end_turn")
        yield Done(
            stop_reason=stop,  # type: ignore[arg-type]
            usage=TokenUsage(input_tokens=100, output_tokens=len(words)),
            turn=AssistantTurn(text=step.text, tool_uses=uses),
        )
