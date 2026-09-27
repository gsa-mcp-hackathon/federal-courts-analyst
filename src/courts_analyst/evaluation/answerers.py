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


ANSWERERS: dict[str, Callable[[], Answerer]] = {
    "gold": GoldAnswerer,
    "null": NullAnswerer,
    "engine": _engine,
}
"""Answerers the CLI can build by name. Later phases register more."""
