"""Behaviour inference and the decline/clarify/answer confusion matrix."""

from __future__ import annotations

import pytest

from courts_analyst.evaluation.records import AnswerRecord, ItemScore, ToolCall
from courts_analyst.evaluation.scoring.behavior import infer_behavior
from courts_analyst.evaluation.scoring.summary import summarize, summary_markdown


def rec(text: str = "", **kw: object) -> AnswerRecord:
    return AnswerRecord.model_validate(
        {"question_id": "q", "answerer": "t", "final_text": text, **kw}
    )


@pytest.mark.parametrize(
    ("text", "behavior"),
    [
        ("FY2020 was 322 (JFF-2023).", "answer"),
        (
            "I can't rank individual judges; the data has no judge identifiers.",
            "decline",
        ),
        ("This server does not rank judges.", "decline"),
        ("FY2030 is outside the scope of the published tables.", "decline"),
        ("There are too few cases to report a median.", "decline"),
        ("Do you mean weighted or unweighted filings?", "clarify"),
        ("Could you clarify which edition you want?", "clarify"),
        ("Which figure would you like: raw or weighted?", "clarify"),
        ("", "answer"),
        # Seen in Phase 5 transcripts (Claude Sonnet):
        ("This tool set has no party-level data — it can't provide names of "
         "litigants.", "decline"),
        ("This isn't something I can answer — FY2030 hasn't happened yet.", "decline"),
        ("I don't have data for FY2012. Would you like FY2016 instead?", "decline"),
        ("Weighted civil filings per judgeship isn't published for FY1992. Would "
         "you like the FY1990 or FY1995 figure instead?", "decline"),
        ("There were 0 cases, so the sample is too small to report a median.",
         "decline"),
        ("That data isn't in scope for these tools. Could you clarify what you "
         "need?", "decline"),
        ('"Filings" is ambiguous here—did you mean civil or criminal? Also let me '
         "know the court.", "clarify"),
        ("I need to clarify which measure you mean — could you confirm which one: "
         "1. count 2. per judgeship.", "clarify"),
        ("There's no published national figure for FY1992 — Table 6.2 reports "
         "1990 and 1995.", "decline"),
        ("There were zero cases — too few (fewer than 10, in fact none) to compute "
         "a median.", "decline"),
        ("This tool covers district courts, not bankruptcy courts: a separate "
         "system this data doesn't include. If you meant appeals, I can look.",
         "decline"),
        # Seen in the Phase 5 smoke runs (GPT-5.6 Sol, Claude Sonnet 5):
        ("I can\u2019t rank individual S.D.N.Y. judges with the available "
         "statistics.", "decline"),
        ("No reportable share can be calculated: there are no matching FOIA "
         "filings, so there is no denominator.", "decline"),
        ("There were zero cases, so there's nothing to compute a rate on; the "
         "result is undefined rather than 0%.", "decline"),
        ("E.D. Tex. had 894 weighted filings per judgeship. " + "Detail. " * 90
         + "The server doesn't provide vacancy data.", "answer"),
    ],
)  # fmt: skip
def test_text_inference(text: str, behavior: str) -> None:
    assert infer_behavior(rec(text)) == behavior


def test_expected_figures_mean_answered() -> None:
    text = "900 is not correct. I won't confirm it. The figure is 322 (JFF-2025)."
    assert infer_behavior(rec(text)) == "decline"
    assert infer_behavior(rec(text), answered_expected=True) == "answer"


def test_declared_behaviour_wins() -> None:
    assert infer_behavior(rec("I can't", behavior="answer")) == "answer"


def test_structured_signals() -> None:
    ask = ToolCall(name="get_official_figure", output={"status": "needs_clarification"})
    assert infer_behavior(rec("", tool_calls=[ask])) == "clarify"
    assert infer_behavior(rec("Do you mean X or Y?", tool_calls=[ask])) == "clarify"
    no = ToolCall(name="compare_courts", output={"status": "declined"})
    assert infer_behavior(rec("", tool_calls=[no])) == "decline"
    assert infer_behavior(rec("Here is some context.", tool_calls=[no])) == "decline"


def _score(expected: str, actual: str, correct: bool | None = None) -> ItemScore:
    return ItemScore(
        question_id=f"{expected}-{actual}",
        suite="adversarial",
        split="dev",
        correct=expected == actual if correct is None else correct,
        expected_behavior=expected,  # type: ignore[arg-type]
        actual_behavior=actual,  # type: ignore[arg-type]
        checks={"behavior": expected == actual},
        latency_s=1.0,
    )


def test_confusion_matrix_math() -> None:
    scores = [
        _score("decline", "decline"),
        _score("decline", "decline"),
        _score("decline", "answer"),
        _score("answer", "decline"),
        _score("answer", "answer"),
        _score("clarify", "clarify"),
        _score("clarify", "answer"),
    ]
    s = summarize(scores)
    assert s.behavior_confusion["decline"] == {"answer": 1, "clarify": 0, "decline": 2}
    d = s.behavior_metrics["decline"]
    assert d.precision == pytest.approx(2 / 3)
    assert d.recall == pytest.approx(2 / 3)
    assert d.support == 3
    c = s.behavior_metrics["clarify"]
    assert c.precision == 1.0 and c.recall == 0.5
    a = s.behavior_metrics["answer"]
    assert a.precision == pytest.approx(1 / 3) and a.recall == 0.5
    assert s.accuracy == pytest.approx(4 / 7)


def test_empty_classes_have_no_precision() -> None:
    s = summarize([_score("answer", "answer")])
    assert s.behavior_metrics["decline"].precision is None
    assert s.behavior_metrics["decline"].recall is None
    assert s.latency_p50_s == 1.0 and s.latency_p95_s == 1.0


def test_markdown_summary() -> None:
    s = summarize([_score("decline", "decline"), _score("answer", "decline")])
    md = summary_markdown(s, "demo")
    assert "**1/2 correct (50.0%)**" in md
    assert "| decline | 50.0% | 100.0% | 1 |" in md
    empty = summarize([])
    assert empty.accuracy is None and "—" in summary_markdown(empty, "none")
