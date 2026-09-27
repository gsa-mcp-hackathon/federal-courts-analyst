"""The agent's SSE event protocol.

Every event is a Pydantic model with a literal ``type``; :data:`AgentEvent`
is their discriminated union. ``make schemas`` exports it to
``web/src/api/schemas/agent-event.schema.json`` so the web app (Phase 8)
types the stream from the same source. A turn always starts with
``turn_start`` and ends with exactly one ``turn_end``; ``error`` comes just
before ``turn_end`` when the turn fails.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from courts_analyst.core.results import Clarification

ServerName = Literal["courts-analyst", "courtlistener"]
StopReason = Literal[
    "end_turn",
    "declined",
    "max_tool_calls",
    "max_model_turns",
    "timeout",
    "token_budget",
    "refusal",
    "error",
]


class _Event(BaseModel):
    seq: int = Field(default=0, description="Position in the turn, from 0.")


class TurnStart(_Event):
    type: Literal["turn_start"] = "turn_start"
    turn_id: str
    model: str
    provider: str
    prompt_version: str = Field(description="Version of agent/system_prompt.md.")


class Thinking(_Event):
    """A short status line for the UI, not model reasoning."""

    type: Literal["thinking"] = "thinking"
    text: str


class ToolCallEvent(_Event):
    type: Literal["tool_call"] = "tool_call"
    call_id: str
    server: ServerName
    tool: str
    arguments: dict[str, Any]


class ToolResultEvent(_Event):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    server: ServerName
    tool: str
    status: str = Field(
        description="The envelope's status ('ok', 'needs_clarification', "
        "'declined'), or 'error'."
    )
    result: dict[str, Any] | None = Field(
        default=None, description="The structured result (a `Result` envelope)."
    )
    error: str | None = None
    latency_ms: float


class ClarifyEvent(_Event):
    """The server asked the user to choose. POST the choice to
    ``/api/ask/{turn_id}/clarify`` and the same stream resumes."""

    type: Literal["clarify"] = "clarify"
    turn_id: str
    clarify_id: str
    clarification: Clarification


class TextDelta(_Event):
    type: Literal["text_delta"] = "text_delta"
    text: str


class CitationRef(BaseModel):
    """An official figure the answer relies on."""

    citation: str = Field(description="The server's one-line citation.")
    value: float
    measure: str
    court: str
    fiscal_year: int
    edition: str
    table_code: str
    url: str | None = None
    revised: bool
    first_published_value: float | None = None
    first_published_edition: str | None = None


class CitationEvent(_Event):
    type: Literal["citation"] = "citation"
    ref: CitationRef
    span: tuple[int, int] | None = Field(
        default=None,
        description="Character offsets [start, end) of the value in the answer "
        "text, when it appears there.",
    )
    call_id: str


class ChartPoint(BaseModel):
    x: str
    y: float
    label: str | None = None


class ChartSeries(BaseModel):
    name: str
    points: list[ChartPoint]


class ChartSpec(BaseModel):
    """A chart derived from one tool result (the MCP App uses the same spec)."""

    kind: Literal["bar", "line", "waterfall", "editions"]
    title: str
    x_label: str
    y_label: str
    unit: str
    series: list[ChartSeries]
    source: str = Field(description="Edition, table or dataset the values are from.")
    call_id: str


class ChartEvent(_Event):
    type: Literal["chart"] = "chart"
    spec: ChartSpec


class DocketCard(BaseModel):
    """A docket reference. Text from CourtListener is untrusted: every string
    field is HTML-escaped and length-capped before it gets here."""

    origin: Literal["idb_sample", "courtlistener", "courtlistener_fixture"]
    court: str
    docket_number: str | None = None
    filing_date: date | None = None
    nature_of_suit: str | None = None
    cause: str | None = None
    url: str | None = None
    note: str


class DocketEvent(_Event):
    type: Literal["docket"] = "docket"
    card: DocketCard
    call_id: str


class WarningEvent(_Event):
    type: Literal["warning"] = "warning"
    code: str
    message: str
    severity: Literal["info", "caution", "block"] = "caution"
    source: Literal["guardrail", "tool", "agent"] = "agent"


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model_requests: int = 0
    tool_calls: int = 0


class TurnEnd(_Event):
    type: Literal["turn_end"] = "turn_end"
    usage: Usage
    latency_ms: float
    stop_reason: StopReason


class ErrorEvent(_Event):
    type: Literal["error"] = "error"
    code: str
    message: str


AgentEvent = Annotated[
    TurnStart
    | Thinking
    | ToolCallEvent
    | ToolResultEvent
    | ClarifyEvent
    | TextDelta
    | CitationEvent
    | ChartEvent
    | DocketEvent
    | WarningEvent
    | TurnEnd
    | ErrorEvent,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
EVENT_TYPES = (
    "turn_start",
    "thinking",
    "tool_call",
    "tool_result",
    "clarify",
    "text_delta",
    "citation",
    "chart",
    "docket",
    "warning",
    "turn_end",
    "error",
)
