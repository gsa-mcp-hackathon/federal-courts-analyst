"""The provider interface: one streamed model request, in our own types.

The loop owns the conversation as a list of :data:`Message` values; each
provider turns it into its API's format, streams one response, and yields
:data:`ProviderEvent` values: text deltas as they arrive, then every tool
use, then exactly one :class:`Done`. Providers never run tools.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the model sees it (``name`` is what the model calls)."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    arguments: dict[str, Any]


# ── conversation ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserText:
    text: str


@dataclass(frozen=True)
class AssistantTurn:
    """What the model said. ``raw`` is the provider's own record of the turn
    (Anthropic content blocks, an OpenAI response id), replayed verbatim."""

    text: str
    tool_uses: list[ToolUse]
    raw: Any = None


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolResults:
    results: list[ToolResult]


Message = UserText | AssistantTurn | ToolResults


# ── stream events ────────────────────────────────────────────────────────────

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    """Uncached input tokens."""
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass(frozen=True)
class TextChunk:
    text: str


@dataclass(frozen=True)
class ToolUseRequested:
    tool_use: ToolUse


@dataclass(frozen=True)
class Done:
    stop_reason: StopReason
    usage: TokenUsage
    turn: AssistantTurn
    details: dict[str, Any] = field(default_factory=dict)


ProviderEvent = TextChunk | ToolUseRequested | Done


class ProviderError(RuntimeError):
    """The model API failed; ``code`` is stable, the message is for logs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Provider(Protocol):
    name: str
    model: str

    def stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream one model response."""
        ...

    async def aclose(self) -> None:
        """Release the HTTP client; the next request makes a new one."""
        ...
