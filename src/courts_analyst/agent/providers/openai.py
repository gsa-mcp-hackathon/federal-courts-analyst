"""An OpenAI model through the Responses API, streamed, for the multi-model
eval. Turns are chained with ``previous_response_id``, so only the newest
messages are sent each time (the same approach as the eval answerer)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import openai

from courts_analyst.agent.providers.base import (
    AssistantTurn,
    Done,
    Message,
    ProviderError,
    ProviderEvent,
    StopReason,
    TextChunk,
    TokenUsage,
    ToolResults,
    ToolSpec,
    ToolUse,
    ToolUseRequested,
    UserText,
)


def pending_input(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """(previous response id, the input items after it)."""
    previous: str | None = None
    start = 0
    for i, m in enumerate(messages):
        if isinstance(m, AssistantTurn) and isinstance(m.raw, str):
            previous, start = m.raw, i + 1
    items: list[dict[str, Any]] = []
    for m in messages[start:]:
        if isinstance(m, UserText):
            items.append({"role": "user", "content": m.text})
        elif isinstance(m, ToolResults):
            items.extend(
                {
                    "type": "function_call_output",
                    "call_id": r.tool_use_id,
                    "output": r.content,
                }
                for r in m.results
            )
    return previous, items


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = "gpt-5.6-sol", client: Any | None = None) -> None:
        self.model = model
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from courts_analyst.config import settings

            key = settings.openai_api_key
            if key is None:
                raise ProviderError(
                    "model_not_configured",
                    "OPENAI_API_KEY is not set; the agent can't run.",
                )
            self._client = openai.AsyncOpenAI(
                api_key=key.get_secret_value() if key else None, max_retries=3
            )
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client (it belongs to the event loop that made it)."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        previous, items = pending_input(messages)
        api_tools = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
                "strict": False,
            }
            for t in tools
        ]
        final: Any = None
        try:
            stream = await self.client.responses.create(
                model=self.model,
                instructions=system,
                input=items,
                tools=api_tools,
                max_output_tokens=max_tokens,
                prompt_cache_key="courts-analyst-agent",
                previous_response_id=previous,
                stream=True,
            )
            async for event in stream:
                if event.type == "response.output_text.delta" and event.delta:
                    yield TextChunk(event.delta)
                elif event.type in ("response.completed", "response.incomplete"):
                    final = event.response
        except openai.RateLimitError as exc:
            raise ProviderError("rate_limited", str(exc)) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(
                "model_api_error", f"API error {exc.status_code}: {exc.message}"[:300]
            ) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("model_unreachable", "API connection error") from exc
        if final is None:
            raise ProviderError("model_api_error", "stream ended without a response")

        uses = []
        for o in final.output:
            if o.type != "function_call":
                continue
            try:
                args = json.loads(o.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            uses.append(
                ToolUse(o.call_id, o.name, args if isinstance(args, dict) else {})
            )
        for u in uses:
            yield ToolUseRequested(u)
        usage = final.usage
        prompt = usage.input_tokens if usage else 0
        cached = usage.input_tokens_details.cached_tokens if usage else 0
        incomplete = getattr(final, "incomplete_details", None)
        stop: StopReason = (
            "tool_use"
            if uses
            else "max_tokens"
            if incomplete is not None
            and getattr(incomplete, "reason", "") == "max_output_tokens"
            else "end_turn"
        )
        yield Done(
            stop_reason=stop,
            usage=TokenUsage(
                input_tokens=prompt - cached,
                output_tokens=usage.output_tokens if usage else 0,
                cache_read_tokens=cached,
            ),
            turn=AssistantTurn(
                text=final.output_text or "", tool_uses=uses, raw=final.id
            ),
        )
