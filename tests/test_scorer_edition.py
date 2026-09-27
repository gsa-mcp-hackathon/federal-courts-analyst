"""Edition correctness: the right number with the wrong edition is wrong."""

from __future__ import annotations

from courts_analyst.evaluation.bank import load_bank
from courts_analyst.evaluation.records import AnswerRecord, ReportedFigure
from courts_analyst.evaluation.scoring import score_item

ITEMS = {i.id: i for i in load_bank()}
FY2020 = ITEMS["fy2020-weighted-civil-national"]  # expects 322 (JFF) and 554 (JB)
ONE = ITEMS["adv-one-number-please"]  # expects 322 (JFF), any mode, revision flagged


def rec(text: str, *cited: tuple[float, str | None]) -> AnswerRecord:
    return AnswerRecord(
        question_id="q",
        answerer="test",
        final_text=text,
        cited_figures=[ReportedFigure(value=v, edition=e) for v, e in cited],
    )


def test_322_attributed_to_jb2020_is_wrong() -> None:
    s = score_item(ONE, rec("It was 322 (JB-2020), later revised.", (322, "JB-2020")))
    assert s.checks["numeric"] is True
    assert s.checks["edition"] is False
    assert not s.correct


def test_322_attributed_to_jff2023_is_right() -> None:
    s = score_item(ONE, rec("It is 322 (JFF-2023); the figure was revised."))
    assert s.checks["edition"] is True
    assert s.correct


def test_any_later_jff_edition_printing_322_is_right() -> None:
    s = score_item(
        ONE, rec("322 per Judicial Facts and Figures 2025, a revised figure.")
    )
    assert s.correct


def test_giving_both_editions_is_right_when_ambiguous() -> None:
    text = (
        "The current official figure is 322 (JFF-2023), revised from 554 as "
        "first published in JB-2020."
    )
    s = score_item(FY2020, rec(text))
    assert s.checks == {
        "behavior": True,
        "numeric": True,
        "edition": True,
        "revision": True,
        "tools": False,
    }
    assert s.correct  # tools is diagnostic outside the tool_selection suite


def test_only_one_of_two_required_figures_is_wrong() -> None:
    s = score_item(FY2020, rec("The figure is 322 (JFF-2023), revised."))
    assert s.checks["numeric"] is False
    assert not s.correct
    assert any("554" in n for n in s.notes)


def test_swapped_editions_are_wrong() -> None:
    s = score_item(FY2020, rec("554 (JFF-2023) and 322 (JB-2020); revised."))
    assert s.checks["numeric"] is True
    assert s.checks["edition"] is False


def test_missing_edition_is_wrong() -> None:
    s = score_item(ONE, rec("It is 322, revised."))
    assert s.checks["edition"] is False


def test_revision_must_be_mentioned() -> None:
    s = score_item(FY2020, rec("322 (JFF-2023) and 554 (JB-2020)."))
    assert s.checks["revision"] is False
    assert not s.correct


def test_engine_items_accept_any_edition() -> None:
    item = ITEMS["engine-us-filed-fy2020"]
    value = item.expected.figures[0].value
    s = score_item(item, rec(f"{value * 1.002:.0f}"))
    assert s.correct
    s = score_item(item, rec(f"{value * 1.02:.0f}"))
    assert not s.correct
