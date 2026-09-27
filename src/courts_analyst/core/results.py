"""Result envelopes: data + provenance + warnings + next steps.

Every core entry point returns a :class:`Result`. Its ``status`` is ``ok``, or
``needs_clarification`` when the question is ambiguous in a way that changes
the answer; then ``data`` is empty and ``clarification`` lists the choices.
Adapters (MCP tools, REST) pass the envelope through unchanged, so every
client sees the same provenance and warnings.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from courts_analyst.core.provenance import Provenance

T = TypeVar("T", bound=BaseModel)

WarningCode = Literal[
    "small_cell",
    "suppressed",
    "data_break",
    "revised_figure",
    "period_mismatch",
    "inferred_not_official",
    "inexact_match",
    "out_of_scope",
    "mixed_editions",
    "partial_year",
    "truncated",
]


class Caveat(BaseModel):
    """Something the reader must know to use the result correctly."""

    code: WarningCode
    message: str
    severity: Literal["info", "caution", "block"] = "caution"

    model_config = {"title": "Warning"}


class Choice(BaseModel):
    value: str
    label: str
    description: str | None = None


class Clarification(BaseModel):
    """A question the server needs answered before it can give one figure.

    Clients that support elicitation show it as a form; others get it in the
    result. Either way, calling again with ``parameter`` set to a choice's
    ``value`` answers it.
    """

    parameter: str = Field(description="The argument to set when calling again.")
    question: str
    choices: list[Choice]
    default: str | None = Field(
        default=None, description="What the server would pick if it had to."
    )


class Result(BaseModel, Generic[T]):
    """Envelope every core entry point returns."""

    status: Literal["ok", "needs_clarification"] = "ok"
    data: T | None = None
    clarification: Clarification | None = None
    provenance: list[Provenance] = Field(default_factory=list)
    warnings: list[Caveat] = Field(default_factory=list)
    suggested_next: list[str] = Field(
        default_factory=list, description="Hints for a follow-up call."
    )


def ok(
    data: T,
    provenance: list[Provenance],
    warnings: list[Caveat] | None = None,
    suggested_next: list[str] | None = None,
) -> Result[T]:
    """Build an ``ok`` result. Every result must carry provenance."""
    if not provenance:
        raise ValueError("a result without provenance is not allowed")
    model: type[Result[T]] = Result[type(data)]  # type: ignore[misc, assignment]
    return model(
        data=data,
        provenance=provenance,
        warnings=warnings or [],
        suggested_next=suggested_next or [],
    )


def clarify(clarification: Clarification, data_type: type[T]) -> Result[T]:
    """A ``needs_clarification`` result for a tool whose data type is ``data_type``."""
    model: type[Result[T]] = Result[data_type]  # type: ignore[valid-type]
    return model(status="needs_clarification", clarification=clarification)
