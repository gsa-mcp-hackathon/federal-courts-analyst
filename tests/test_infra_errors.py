"""Tests for infra-error tracking: ItemScore.infra_error and RunSummary infra fields."""

from __future__ import annotations

import pytest

from courts_analyst.evaluation.bank import load_bank, select
from courts_analyst.evaluation.records import AnswerRecord, ItemScore, ToolCall
from courts_analyst.evaluation.scoring import score_item, summarize
from courts_analyst.evaluation.scoring.summary import WilsonCI

_ITEMS = load_bank()
_E2E_DEV = select(_ITEMS, suite="e2e", split="dev")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_score(
    *,
    correct: bool = True,
    infra_error: bool = False,
    question_id: str = "q1",
) -> ItemScore:
    return ItemScore(
        question_id=question_id,
        suite="e2e",
        split="dev",
        correct=correct,
        checks={},
        expected_behavior="answer",
        actual_behavior="answer",
        infra_error=infra_error,
    )


# ---------------------------------------------------------------------------
# ItemScore.infra_error flag set by scorer
# ---------------------------------------------------------------------------


class TestItemScoreInfraFlag:
    def test_infra_error_set_when_tool_error_starts_with_infra(self) -> None:
        """score_item sets infra_error=True when any tool call has error starting with 'infra:'."""
        item = _E2E_DEV[0]
        record = AnswerRecord(
            question_id=item.id,
            answerer="test",
            tool_calls=[
                ToolCall(
                    name="get_official_figure",
                    arguments={},
                    error="infra: wxO tool runtime error",
                ),
            ],
        )
        score = score_item(item, record)
        assert score.infra_error is True

    def test_infra_error_false_for_clean_tool_call(self) -> None:
        item = _E2E_DEV[0]
        record = AnswerRecord(
            question_id=item.id,
            answerer="test",
            tool_calls=[
                ToolCall(name="get_official_figure", arguments={}, error=None),
            ],
        )
        score = score_item(item, record)
        assert score.infra_error is False

    def test_infra_error_false_for_non_infra_tool_error(self) -> None:
        """An error that does not start with 'infra:' does not set the flag."""
        item = _E2E_DEV[0]
        record = AnswerRecord(
            question_id=item.id,
            answerer="test",
            tool_calls=[
                ToolCall(
                    name="get_official_figure",
                    arguments={},
                    error="argument: missing fiscal_year",
                ),
            ],
        )
        score = score_item(item, record)
        assert score.infra_error is False

    def test_infra_error_false_when_no_tool_calls(self) -> None:
        item = _E2E_DEV[0]
        record = AnswerRecord(question_id=item.id, answerer="test")
        score = score_item(item, record)
        assert score.infra_error is False

    def test_infra_error_set_via_tool_output(self) -> None:
        """infra_error is detected from tool output text, not only tc.error.

        This covers older wxO records rescored after the fact, where the
        infra-error phrase landed in the structured output dict rather than
        in ToolCall.error (which was None at extraction time).
        """
        item = _E2E_DEV[0]
        record = AnswerRecord(
            question_id=item.id,
            answerer="test",
            tool_calls=[
                ToolCall(
                    name="get_official_figure",
                    arguments={},
                    error=None,
                    output={"message": "Failed to execute function: timeout"},
                ),
            ],
        )
        score = score_item(item, record)
        assert score.infra_error is True

    def test_infra_error_output_clean_output_is_false(self) -> None:
        """A tool output with a normal JSON response does not trigger the flag."""
        item = _E2E_DEV[0]
        record = AnswerRecord(
            question_id=item.id,
            answerer="test",
            tool_calls=[
                ToolCall(
                    name="get_official_figure",
                    arguments={},
                    error=None,
                    output={"status": "ok", "data": {"value": 322}},
                ),
            ],
        )
        score = score_item(item, record)
        assert score.infra_error is False


# ---------------------------------------------------------------------------
# RunSummary infra fields
# ---------------------------------------------------------------------------


class TestRunSummaryInfraFields:
    def test_no_infra_errors_fields_are_zero_and_none(self) -> None:
        scores = [
            _make_score(correct=True, infra_error=False, question_id=f"q{i}")
            for i in range(3)
        ]
        summary = summarize(scores)
        assert summary.infra_error_attempts == 0
        assert summary.accuracy_excl_infra is None
        assert summary.ci95_excl_infra is None

    def test_infra_error_attempts_counted(self) -> None:
        scores = [
            _make_score(correct=True, infra_error=False, question_id="q1"),
            _make_score(correct=False, infra_error=True, question_id="q2"),
            _make_score(correct=True, infra_error=False, question_id="q3"),
        ]
        summary = summarize(scores)
        assert summary.infra_error_attempts == 1

    def test_accuracy_excl_infra_computed(self) -> None:
        # 1 clean correct, 1 clean wrong, 1 infra error (wrong)
        # excl infra: 1/2 = 50%
        scores = [
            _make_score(correct=True, infra_error=False, question_id="q1"),
            _make_score(correct=False, infra_error=False, question_id="q2"),
            _make_score(correct=False, infra_error=True, question_id="q3"),
        ]
        summary = summarize(scores)
        assert summary.accuracy_excl_infra == pytest.approx(0.5)

    def test_ci95_excl_infra_is_wilsonci(self) -> None:
        scores = [
            _make_score(correct=True, infra_error=False, question_id="q1"),
            _make_score(correct=False, infra_error=True, question_id="q2"),
        ]
        summary = summarize(scores)
        assert summary.ci95_excl_infra is not None
        assert isinstance(summary.ci95_excl_infra, WilsonCI)
        assert 0.0 <= summary.ci95_excl_infra.low <= summary.ci95_excl_infra.high <= 1.0

    def test_headline_accuracy_includes_infra_attempts(self) -> None:
        """The main accuracy is computed over ALL attempts including infra errors."""
        scores = [
            _make_score(correct=True, infra_error=False, question_id="q1"),
            _make_score(correct=False, infra_error=True, question_id="q2"),
        ]
        summary = summarize(scores)
        # 1 correct out of 2 total = 0.5
        assert summary.accuracy == pytest.approx(0.5)
        assert summary.n == 2


# ---------------------------------------------------------------------------
# summary_markdown infra line
# ---------------------------------------------------------------------------


class TestSummaryMarkdownInfraLine:
    def test_infra_line_present_when_errors_exist(self) -> None:
        from courts_analyst.evaluation.scoring.summary import summary_markdown

        scores = [
            _make_score(correct=True, infra_error=False, question_id="q1"),
            _make_score(correct=False, infra_error=True, question_id="q2"),
        ]
        summary = summarize(scores)
        md = summary_markdown(summary, "test run")
        assert "Infra (wxO tool-runtime errors):" in md
        assert "1 of 2 attempts" in md
        assert "excluding them:" in md

    def test_infra_line_absent_when_no_errors(self) -> None:
        from courts_analyst.evaluation.scoring.summary import summary_markdown

        scores = [
            _make_score(correct=True, infra_error=False, question_id=f"q{i}")
            for i in range(3)
        ]
        summary = summarize(scores)
        md = summary_markdown(summary, "test run")
        assert "Infra" not in md

    def test_infra_line_includes_ci(self) -> None:
        from courts_analyst.evaluation.scoring.summary import summary_markdown

        # 2 clean + 1 infra
        scores = [
            _make_score(correct=True, infra_error=False, question_id="q1"),
            _make_score(correct=True, infra_error=False, question_id="q2"),
            _make_score(correct=False, infra_error=True, question_id="q3"),
        ]
        summary = summarize(scores)
        md = summary_markdown(summary, "test run")
        assert "95% CI" in md
