"""Unit tests for the LLM-judge comparison (llm_judge.py). No model calls:
the judge is a stub."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from courts_analyst.evaluation import llm_judge as J
from courts_analyst.evaluation.bank import load_bank
from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.schema import QuestionItem
from courts_analyst.evaluation.scoring.score import score_item

REVISED = "fy2020-weighted-civil-national"
GOOD = (
    "* 322 weighted filings per judgeship (JFF‑2025), the current official figure.\n"
    "* 554 weighted filings per judgeship (JB‑2020), as first published; later revised."
)


@pytest.fixture(scope="module")
def items() -> dict[str, QuestionItem]:
    return {i.id: i for i in load_bank()}


def test_good_reply_passes_the_scorer(items: dict[str, QuestionItem]) -> None:
    rec = AnswerRecord(question_id=REVISED, answerer="t", final_text=GOOD)
    assert score_item(items[REVISED], rec).correct


def test_reference_lists_editions_and_revision(items: dict[str, QuestionItem]) -> None:
    ref = J.reference_answer(items[REVISED])
    assert "322 (JFF-2023" in ref
    assert "554 (JB-2020" in ref
    assert "revised" in ref


def test_prompts_differ_only_by_rules(items: dict[str, QuestionItem]) -> None:
    g = J.judge_prompt(items[REVISED], GOOD, "generic")
    i = J.judge_prompt(items[REVISED], GOOD, "informed")
    assert i.startswith(g)
    assert "edition" in i[len(g) :]


def test_swap_trades_values(items: dict[str, QuestionItem]) -> None:
    out = J.mutate_swap(items[REVISED], GOOD)
    assert out is not None
    assert "554 weighted filings per judgeship (JFF‑2025)" in out
    assert "322 weighted filings per judgeship (JB‑2020)" in out


def test_no_edition_removes_every_edition(items: dict[str, QuestionItem]) -> None:
    out = J.mutate_no_edition(items[REVISED], GOOD)
    assert out is not None
    assert "JFF" not in out and "JB" not in out and "()" not in out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("filed 4,221 cases (JB-2019)", "filed 4,223 cases (JB-2019)"),
        ("filed 4 221 cases (JB-2019)", "filed 4,223 cases (JB-2019)"),
        ("filed 4221 cases (JB-2019)", "filed 4,223 cases (JB-2019)"),
        ("filed 14,221 cases", None),
    ],
)
def test_nudge_matches_any_thousands_separator(
    items: dict[str, QuestionItem], text: str, expected: str | None
) -> None:
    item = items["t2-civil-cases-filed-ca-e-fy2019"]
    assert J.mutate_nudge(item, text) == expected


def test_every_mutant_is_wrong_for_the_scorer(items: dict[str, QuestionItem]) -> None:
    item = items[REVISED]
    for mutate in J.MUTATORS.values():
        text = mutate(item, GOOD)
        assert text is not None
        rec = AnswerRecord(question_id=REVISED, answerer="t", final_text=text)
        assert not score_item(item, rec).correct, mutate.__name__


def test_kappa() -> None:
    assert J.cohen_kappa([(True, True), (False, False)]) == pytest.approx(1.0)
    assert J.cohen_kappa([(True, False), (False, True)]) == pytest.approx(-1.0)
    assert J.cohen_kappa([(True, True), (True, True)]) is None


def _write_run(path: Path, item: QuestionItem, texts: list[str]) -> None:
    lines = []
    for n, text in enumerate(texts):
        rec = AnswerRecord(question_id=item.id, answerer="t", final_text=text)
        score = score_item(item, rec).model_dump()
        lines.append(
            json.dumps({"repeat": n, "record": rec.model_dump(), "score": score})
        )
    path.write_text("\n".join(lines) + "\n")


def test_run_summarise_and_resume(
    tmp_path: Path, items: dict[str, QuestionItem]
) -> None:
    item = items[REVISED]
    run = tmp_path / "run.jsonl"
    _write_run(run, item, [GOOD, "I can't help with that."])
    cases = J.load_cases([run], items, mutants=True)
    kinds = sorted(c.kind for c in cases)
    assert kinds == ["no_edition", "nudge", "original", "original", "swap"]

    calls: list[str] = []

    def lenient(prompt: str) -> J.Verdict:  # passes everything with a number
        calls.append(prompt)
        return J.Verdict(
            "correct" if "322" in prompt.split("[Response]")[1] else "incorrect"
        )

    out = tmp_path / "judge.jsonl"
    graded = J.run_judge(
        cases, items, lenient, variants=["generic"], workers=2, out=out
    )
    assert len(graded) == len(cases)
    s = J.summarise(graded)
    agree = s["agreement"]["generic"]
    assert agree.n == 2 and agree.rate == 1.0
    swap = s["mutants"][("swap", "generic")]
    assert swap["scorer_caught"] == 1 and swap["judge_caught"] == 0

    # A second call reuses every saved verdict.
    calls.clear()
    J.run_judge(cases, items, lenient, variants=["generic"], workers=2, out=out)
    assert calls == []
    md = J.report_markdown(graded, "stub", ["run.jsonl"])
    assert "| swap | generic | 1 |" in md
