"""Score one answer against one question, deterministically.

Which checks apply depends on the item, not only its suite:

========================  ==================================================
check                     applies when
========================  ==================================================
``behavior``              always (answer / clarify / decline must match)
``numeric``, ``edition``  the item lists expected figures and should be answered
``ranking``               the item lists a ranking
``revision``              ``must_mention_revision``
``claim:<id>``            each claim
``tools``                 ``tool_selection`` items (and any item whose record has
                          tool calls and lists ``expected_tools``, reported only)
========================  ==================================================

An item is correct when every applicable check passes, except that ``tools``
counts toward correctness only in the tool_selection suite; elsewhere it's a
diagnostic. Failures get one MCP-Atlas style error category.
"""

from __future__ import annotations

from courts_analyst.core.numbers import round_half_up
from courts_analyst.evaluation.records import AnswerRecord, ItemScore
from courts_analyst.evaluation.schema import QuestionItem
from courts_analyst.evaluation.scoring.behavior import infer_behavior
from courts_analyst.evaluation.scoring.claims import (
    check_claim,
    courts_mentioned_in_order,
    mentions_revision,
)
from courts_analyst.evaluation.scoring.figures import figures_in_text, reported_figures
from courts_analyst.evaluation.scoring.numeric import (
    check_figures,
    printed_decimals,
)


def _numeric_leaves(obj: object) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numeric_leaves(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_numeric_leaves(v))
    return out


def tools_ok(item: QuestionItem, record: AnswerRecord) -> bool:
    called = set(record.tools_called)
    return set(item.expected_tools) <= called


def _hallucinated(record: AnswerRecord) -> bool:
    """The answer attributes a number to an edition that no tool output holds."""
    if not record.tool_calls:
        return False
    leaves = _numeric_leaves(record.structured_outputs)
    for fig in figures_in_text(record.final_text):
        if fig.edition is None:
            continue
        d = printed_decimals(fig.value)
        if all(round_half_up(v, d) != fig.value for v in leaves):
            return True
    return False


def _category(item: QuestionItem, record: AnswerRecord, checks: dict[str, bool]) -> str:
    if record.error:
        return "answerer_failure"
    if item.expected_tools and not tools_ok(item, record):
        return "tool_selection"
    if any(c.error for c in record.tool_calls) and not record.structured_outputs:
        return "argument"
    if checks.get("behavior") is False:
        return "task_understanding"
    if _hallucinated(record):
        return "hallucinated_number"
    if record.structured_outputs:
        return "output_interpretation"
    return "task_understanding"


def score_item(item: QuestionItem, record: AnswerRecord) -> ItemScore:
    exp = item.expected
    notes: list[str] = []
    answering = exp.behavior == "answer"
    res = (
        check_figures(exp.figures, exp.figures_mode, reported_figures(record))
        if exp.figures and answering
        else None
    )
    actual = (
        "answer"
        if record.error
        else infer_behavior(record, answered_expected=bool(res and res.numeric_ok))
    )
    checks: dict[str, bool] = {"behavior": actual == exp.behavior}

    if res is not None:
        checks["numeric"] = res.numeric_ok
        if res.needs_edition:
            checks["edition"] = res.edition_ok
        for c in res.checks:
            if c.value_found and not c.ok:
                notes.append(
                    f"{c.expected.value:g}: edition {c.editions_seen} "
                    f"not in {c.expected.editions}"
                )
            elif not c.value_found:
                notes.append(f"{c.expected.value:g} {c.expected.editions} not found")
    if exp.ranking and answering:
        named, ordered = courts_mentioned_in_order(exp.ranking, record.final_text)
        checks["ranking"] = named and ordered
        if named and not ordered:
            notes.append("ranking: right courts, wrong order")
    if exp.must_mention_revision and answering:
        checks["revision"] = mentions_revision(record)
    for claim in item.claims:
        checks[f"claim:{claim.id}"] = check_claim(claim, record)

    graded = dict(checks)
    if item.expected_tools:
        checks["tools"] = tools_ok(item, record)
        if item.suite == "tool_selection":
            graded["tools"] = checks["tools"]
    correct = not record.error and all(graded.values())
    return ItemScore(
        question_id=item.id,
        suite=item.suite,
        split=item.resolved_split,
        tags=item.tags,
        correct=correct,
        checks=checks,
        expected_behavior=exp.behavior,
        actual_behavior=actual,
        error_category=None if correct else _category(item, record, checks),
        notes=notes,
        latency_s=record.latency_s,
    )
