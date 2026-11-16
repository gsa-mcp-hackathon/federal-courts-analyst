"""Claude through the Messages API, streamed.

Text is forwarded as it streams; tool uses are read from the final message
(inputs are small JSON objects, so they're left buffered and validated by
the API rather than streamed eagerly). Assistant turns are replayed with
their original content blocks. Tools and the system prompt are the same on
every request, so top-level automatic caching serves them from the cache.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic

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

_STOP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, UserText):
            out.append({"role": "user", "content": m.text})
        elif isinstance(m, AssistantTurn):
            content = m.raw
            if content is None:
                content = ([{"type": "text", "text": m.text}] if m.text else []) + [
                    {
                        "type": "tool_use",
                        "id": u.id,
                        "name": u.name,
                        "input": u.arguments,
                    }
                    for u in m.tool_uses
                ]
            out.append({"role": "assistant", "content": content})
        elif isinstance(m, ToolResults):
            # All results of one turn go back in a single user message.
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.tool_use_id,
                            "content": r.content,
                            **({"is_error": True} if r.is_error else {}),
                        }
                        for r in m.results
                    ],
                }
            )
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, model: str = "claude-sonnet-5", client: Any | None = None
    ) -> None:
        self.model = model
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from courts_analyst.config import settings

            key = settings.anthropic_api_key
            if key is None:
                raise ProviderError(
                    "model_not_configured",
                    "ANTHROPIC_API_KEY is not set; the agent can't run.",
                )
            self._client = anthropic.AsyncAnthropic(
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
        api_tools: Any = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                tools=api_tools,
                messages=to_api_messages(messages),
                cache_control={"type": "ephemeral"},
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield TextChunk(text)
                final = await stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate_limited", str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                "model_api_error", f"API error {exc.status_code}: {exc.message}"[:300]
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("model_unreachable", "API connection error") from exc

        uses = [
            ToolUse(b.id, b.name, dict(b.input) if isinstance(b.input, dict) else {})
            for b in final.content
            if b.type == "tool_use"
        ]
        for u in uses:
            yield ToolUseRequested(u)
        u = final.usage
        details: dict[str, Any] = {}
        if final.stop_reason == "refusal" and getattr(final, "stop_details", None):
            details["refusal_category"] = getattr(final.stop_details, "category", None)
        yield Done(
            stop_reason=_STOP.get(final.stop_reason or "", "other"),
            usage=TokenUsage(
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_input_tokens or 0,
                cache_write_tokens=u.cache_creation_input_tokens or 0,
            ),
            turn=AssistantTurn(
                text="".join(b.text for b in final.content if b.type == "text"),
                tool_uses=uses,
                raw=final.content,
            ),
            details=details,
        )
