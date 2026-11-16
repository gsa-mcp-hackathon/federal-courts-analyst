"""What an answerer returns, and what the scorer writes back."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from courts_analyst.evaluation.schema import Behavior, Split, Suite


class ToolCall(BaseModel):
    """One tool call the answerer made, with its structured result."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = Field(
        default=None, description="The tool's structuredContent, if any."
    )
    error: str | None = None
    latency_s: float | None = None


class ReportedFigure(BaseModel):
    """A number the answer states, with the edition it attributes it to."""

    value: float
    edition: str | None = None
    measure: str | None = None
    court: str | None = None


class AnswerRecord(BaseModel):
    """Everything an answerer produced for one question."""

    question_id: str
    answerer: str
    final_text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    extra_outputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured outputs not tied to a tool call (engine answers).",
    )
    cited_figures: list[ReportedFigure] = Field(
        default_factory=list,
        description="Figures the answerer declares explicitly (preferred over text).",
    )
    behavior: Behavior | None = Field(
        default=None,
        description="Declared behaviour; inferred from the answer when unset.",
    )
    latency_s: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = Field(
        default=None, description="What the model calls for this answer cost."
    )
    model_requests: int | None = None
    error: str | None = Field(
        default=None, description="Set when the answerer itself failed."
    )

    @property
    def structured_outputs(self) -> list[dict[str, Any]]:
        outs = [c.output for c in self.tool_calls if c.output is not None]
        return [*outs, *self.extra_outputs]

    @property
    def tools_called(self) -> list[str]:
        return [c.name for c in self.tool_calls]


ErrorCategory = str
"""MCP-Atlas style: ``tool_selection``, ``argument``, ``task_understanding``,
``output_interpretation``, ``hallucinated_number``, ``answerer_failure``."""


class ItemScore(BaseModel):
    """The deterministic score for one question."""

    question_id: str
    suite: Suite
    split: Split
    tags: list[str] = Field(default_factory=list)
    correct: bool
    checks: dict[str, bool] = Field(
        default_factory=dict,
        description="Each check that applied: numeric, edition, ranking, "
        "revision, behavior, tools, claim:<id>.",
    )
    expected_behavior: Behavior
    actual_behavior: Behavior
    error_category: ErrorCategory | None = None
    infra_error: bool = False
    notes: list[str] = Field(default_factory=list)
    latency_s: float | None = None
    cost_usd: float | None = None
