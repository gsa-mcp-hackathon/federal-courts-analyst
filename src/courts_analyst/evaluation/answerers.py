"""The ``Answerer`` protocol and the two harness self-checks.

Every system under test (our agent, a web-search baseline, Genie) implements
:class:`Answerer`. :class:`GoldAnswerer` builds the answer the scorer expects
from the item itself and must score 100%; :class:`NullAnswerer` says nothing
and must score 0%. Together they check the harness, not a system.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from courts_analyst.core.courts import COURTS
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure, ToolCall
from courts_analyst.evaluation.schema import Claim, QuestionItem


@runtime_checkable
class Answerer(Protocol):
    """Anything that can answer a benchmark question."""

    name: str

    def answer(self, item: QuestionItem) -> AnswerRecord:
        """Answer ``item.question``. Implementations other than the gold
        answerer must read only ``item.question`` (and ``item.id``)."""
        ...


def _nested(path: str, value: Any) -> dict[str, Any]:
    """Build the smallest structure where ``path`` resolves to ``value``."""
    parts = path.split(".")
    node: Any = value
    for part in reversed(parts):
        if part.endswith("[]"):
            key = part[:-2]
            node = {key: [node]} if key else [node]
        else:
            node = {part: node}
    assert isinstance(node, dict)
    return node


def _satisfying_value(claim: Claim) -> Any:
    if claim.op == "in":
        return claim.value[0]
    if claim.op == "exists":
        return True
    return claim.value


class GoldAnswerer:
    """Answers from the expected answer. Must score 100%."""

    name = "gold"

    def answer(self, item: QuestionItem) -> AnswerRecord:
        exp = item.expected
        parts: list[str] = []
        cited: list[ReportedFigure] = []
        if exp.behavior == "answer":
            for f in exp.figures:
                ed = f.editions[0] if f.editions else None
                parts.append(f"{f.value:g}" + (f" ({ed})" if ed else ""))
                cited.append(ReportedFigure(value=f.value, edition=ed))
            if exp.ranking:
                parts.append(
                    "; ".join(
                        f"{i}. {COURTS[c].citation or COURTS[c].name}"
                        for i, c in enumerate(exp.ranking, 1)
                    )
                )
            if exp.must_mention_revision:
                parts.append("This figure was revised in a later edition.")
        outputs: list[dict[str, Any]] = []
        calls = [ToolCall(name=t) for t in item.expected_tools]
        for claim in item.claims:
            if claim.kind == "mentions":
                parts.extend(claim.all or [])
                if claim.any:
                    parts.append(claim.any[0])
            elif claim.kind == "field":
                assert claim.path is not None
                outputs.append(_nested(claim.path, _satisfying_value(claim)))
            elif claim.kind == "tool_called" and claim.tool not in item.expected_tools:
                calls.append(ToolCall(name=str(claim.tool)))
        return AnswerRecord(
            question_id=item.id,
            answerer=self.name,
            final_text=" ".join(parts),
            tool_calls=calls,
            extra_outputs=outputs,
            cited_figures=cited,
            behavior=exp.behavior,
            latency_s=0.0,
        )


class NullAnswerer:
    """Says nothing and calls nothing. Must score 0%."""

    name = "null"

    def answer(self, item: QuestionItem) -> AnswerRecord:
        return AnswerRecord(question_id=item.id, answerer=self.name, latency_s=0.0)


def _engine() -> Answerer:
    from courts_analyst.evaluation.engine import EngineAnswerer

    return EngineAnswerer()


def _claude_code(model: str) -> Callable[[], Answerer]:
    def make() -> Answerer:
        from courts_analyst.evaluation.claude_code import ClaudeCodeAnswerer

        return ClaudeCodeAnswerer(model)

    return make


def _paid(module: str, cls: str, model: str) -> Callable[[], Answerer]:
    def make() -> Answerer:
        import importlib

        answerer: Answerer = getattr(importlib.import_module(module), cls)(model)
        return answerer

    return make


ANSWERERS: dict[str, Callable[[], Answerer]] = {
    "gold": GoldAnswerer,
    "null": NullAnswerer,
    "engine": _engine,
    "claude-code": _claude_code("sonnet"),
    "claude-code-haiku": _claude_code("haiku"),
    # Paid API answerers (`uv sync --group eval`; keys in .env). The CLI runs
    # them on the smoke set only, under --budget-usd, unless told otherwise.
    "claude-api": _paid(
        "courts_analyst.evaluation.anthropic_agent",
        "AnthropicAnswerer",
        "claude-sonnet-5",
    ),
    "claude-api-opus": _paid(
        "courts_analyst.evaluation.anthropic_agent",
        "AnthropicAnswerer",
        "claude-opus-5",
    ),
    "openai-api": _paid(
        "courts_analyst.evaluation.openai_agent", "OpenAIAnswerer", "gpt-5.6-sol"
    ),
    # The Phase 7 agent (the web app's answerer): same tools plus the
    # CourtListener fixture, the guardrail screen and the citation line.
    "agent": _paid(
        "courts_analyst.agent.transcript",
        "AgentAnswerer",
        "anthropic:claude-sonnet-5",
    ),
    "agent-openai": _paid(
        "courts_analyst.agent.transcript", "AgentAnswerer", "openai:gpt-5.6-sol"
    ),
}
PAID = frozenset(
    {"claude-api", "claude-api-opus", "openai-api", "agent", "agent-openai"}
)
"""Answerers that spend money on every question."""
"""Answerers the CLI can build by name. Later phases register more."""
