"""Tests for the repeats (pass^K) feature.

Covers:
- Wilson CI against known values
- pass@k / pass^k with a scripted answerer correct on only some attempts
- --repeats through cli.main with gold answerer (pass^K = 100%)
- rescore of a repeated run
- Old summaries without repeats fields still load (defaults)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from courts_analyst.evaluation.answerers import GoldAnswerer
from courts_analyst.evaluation.bank import load_bank, select
from courts_analyst.evaluation.cli import main
from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.runner import rescore, run
from courts_analyst.evaluation.schema import QuestionItem
from courts_analyst.evaluation.scoring.summary import (
    RunSummary,
    WilsonCI,
    wilson_ci95,
)

ITEMS = load_bank()
E2E_DEV = select(ITEMS, suite="e2e", split="dev")[:3]


# ---------------------------------------------------------------------------
# Wilson CI
# ---------------------------------------------------------------------------


class TestWilsonCI:
    def test_8_of_10(self) -> None:
        ci = wilson_ci95(8, 10)
        # Well-known result: approximately [0.49, 0.94]
        assert isinstance(ci, WilsonCI)
        assert pytest.approx(ci.low, abs=0.01) == 0.490
        assert pytest.approx(ci.high, abs=0.01) == 0.943

    def test_0_of_10(self) -> None:
        ci = wilson_ci95(0, 10)
        assert ci.low == pytest.approx(0.0, abs=1e-9)
        # Upper bound for 0/10 ≈ 0.308
        assert 0.25 < ci.high < 0.40

    def test_10_of_10(self) -> None:
        ci = wilson_ci95(10, 10)
        assert ci.high == pytest.approx(1.0, abs=1e-9)
        # Lower bound for 10/10 ≈ 0.692
        assert 0.65 < ci.low < 0.80

    def test_zero_trials(self) -> None:
        ci = wilson_ci95(0, 0)
        assert ci.low == 0.0 and ci.high == 1.0

    def test_bounds_in_unit_interval(self) -> None:
        for k, n in [(0, 1), (1, 1), (5, 100), (99, 100), (50, 50)]:
            ci = wilson_ci95(k, n)
            assert 0.0 <= ci.low <= ci.high <= 1.0

    def test_low_lt_high_for_interior(self) -> None:
        ci = wilson_ci95(5, 10)
        assert ci.low < ci.high


# ---------------------------------------------------------------------------
# Scripted answerer: correct on first attempt only
# ---------------------------------------------------------------------------


class _AlternatingAnswerer:
    """Correct on repeat index 0, wrong (null text) on subsequent repeats.

    We detect which attempt this is by counting calls per question_id.
    """

    name = "alternating"

    def __init__(self, correct_on: set[int]) -> None:
        self._correct_on = correct_on
        self._calls: dict[str, int] = {}
        self._gold = GoldAnswerer()

    def answer(self, item: QuestionItem) -> AnswerRecord:
        n = self._calls.get(item.id, 0)
        self._calls[item.id] = n + 1
        if n in self._correct_on:
            return self._gold.answer(item)
        # Return an empty record — will score wrong
        return AnswerRecord(question_id=item.id, answerer=self.name)


class TestPassAtK:
    """pass@k / pass^k semantics with a scripted answerer."""

    def test_correct_on_first_attempt_only(self, tmp_path: Path) -> None:
        # Only attempt 0 is correct → pass@K=1.0, pass^K=0.0 (for K=2)
        items = E2E_DEV[:2]
        answerer = _AlternatingAnswerer(correct_on={0})
        result = run(answerer, items, results_dir=tmp_path, repeats=2)
        s = result.summary
        assert s.repeats == 2
        assert s.pass_at_k == pytest.approx(1.0)
        assert s.pass_hat_k == pytest.approx(0.0)

    def test_correct_on_all_attempts(self, tmp_path: Path) -> None:
        # Gold answerer is always correct → pass@K = pass^K = 1.0
        items = E2E_DEV[:2]
        result = run(GoldAnswerer(), items, results_dir=tmp_path, repeats=2)
        s = result.summary
        assert s.pass_at_k == pytest.approx(1.0)
        assert s.pass_hat_k == pytest.approx(1.0)

    def test_correct_on_no_attempts(self, tmp_path: Path) -> None:
        # No attempt is correct → pass@K = pass^K = 0.0
        from courts_analyst.evaluation.answerers import NullAnswerer

        items = E2E_DEV[:2]
        result = run(NullAnswerer(), items, results_dir=tmp_path, repeats=2)
        s = result.summary
        assert s.pass_at_k == pytest.approx(0.0)
        assert s.pass_hat_k == pytest.approx(0.0)

    def test_mixed_items(self, tmp_path: Path) -> None:
        # Two items: one always correct (gold), one always wrong (null).
        # pass@K = 0.5, pass^K = 0.5
        items = E2E_DEV[:2]

        class _Mixed:
            name = "mixed"

            def __init__(self) -> None:
                self._gold = GoldAnswerer()
                self._calls: dict[str, int] = {}

            def answer(self, item: QuestionItem) -> AnswerRecord:
                # First item always gold, second always null
                if item.id == items[0].id:
                    return self._gold.answer(item)
                return AnswerRecord(question_id=item.id, answerer=self.name)

        result = run(_Mixed(), items, results_dir=tmp_path, repeats=3)
        s = result.summary
        assert s.pass_at_k == pytest.approx(0.5)
        assert s.pass_hat_k == pytest.approx(0.5)

    def test_accuracy_is_mean_over_all_attempts(self, tmp_path: Path) -> None:
        # With 2 items × 2 repeats, first attempt correct for both,
        # second attempt wrong for both → 2/4 = 0.5
        items = E2E_DEV[:2]
        answerer = _AlternatingAnswerer(correct_on={0})
        result = run(answerer, items, results_dir=tmp_path, repeats=2)
        # 2 correct out of 4 total attempts
        assert result.summary.accuracy == pytest.approx(0.5)
        assert result.summary.n == 4

    def test_per_item_counts(self, tmp_path: Path) -> None:
        items = E2E_DEV[:2]
        answerer = _AlternatingAnswerer(correct_on={0})
        result = run(answerer, items, results_dir=tmp_path, repeats=3)
        s = result.summary
        # Each item correct on attempt 0 only → 1/3
        assert all(v == 1 for v in s.per_item.values())

    def test_repeat_field_in_jsonl(self, tmp_path: Path) -> None:
        items = E2E_DEV[:2]
        result = run(GoldAnswerer(), items, results_dir=tmp_path, repeats=3)
        lines = result.paths["jsonl"].read_text().splitlines()
        assert len(lines) == 6  # 2 items × 3 repeats
        repeat_indices = [json.loads(ln)["repeat"] for ln in lines]
        # Output order: repeat 0 for all items, then repeat 1, then repeat 2
        assert repeat_indices == [0, 0, 1, 1, 2, 2]

    def test_ci95_present(self, tmp_path: Path) -> None:
        items = E2E_DEV[:2]
        result = run(GoldAnswerer(), items, results_dir=tmp_path, repeats=2)
        ci = result.summary.accuracy_ci95
        assert ci is not None
        assert 0.0 <= ci.low <= ci.high <= 1.0

    def test_single_repeat_no_pass_at_k(self, tmp_path: Path) -> None:
        # With repeats=1 the repeats fields are absent / None
        items = E2E_DEV[:2]
        result = run(GoldAnswerer(), items, results_dir=tmp_path, repeats=1)
        s = result.summary
        assert s.repeats is None
        assert s.pass_at_k is None
        assert s.pass_hat_k is None
        assert s.per_item == {}


# ---------------------------------------------------------------------------
# CLI --repeats with gold answerer
# ---------------------------------------------------------------------------


class TestCLIRepeats:
    def test_gold_pass_hat_k_is_100(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--suite",
            "e2e",
            "--split",
            "dev",
            "--limit",
            "2",
            "--repeats",
            "3",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        rc = main(args)
        assert rc == 0
        out = capsys.readouterr().out
        # Markdown summary should contain the Repeats block
        assert "Repeats" in out
        assert "pass@K" in out
        assert "pass^K" in out
        # Gold is always correct → pass^K = 100%
        assert "100.0%" in out

    def test_repeats_jsonl_has_repeat_field(self, tmp_path: Path) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--suite",
            "e2e",
            "--split",
            "dev",
            "--limit",
            "2",
            "--repeats",
            "2",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        main(args)
        jsonl = next(tmp_path.glob("*.jsonl"))
        lines = jsonl.read_text().splitlines()
        assert len(lines) == 4  # 2 items × 2 repeats
        assert all("repeat" in json.loads(ln) for ln in lines)

    def test_summary_json_has_repeats_meta(self, tmp_path: Path) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--suite",
            "e2e",
            "--split",
            "dev",
            "--limit",
            "2",
            "--repeats",
            "2",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        main(args)
        summary_file = next(tmp_path.glob("*.summary.json"))
        data = json.loads(summary_file.read_text())
        assert data["repeats"] == 2
        assert data["summary"]["repeats"] == 2


# ---------------------------------------------------------------------------
# Rescore of a repeated run
# ---------------------------------------------------------------------------


class TestRescoreRepeated:
    def test_rescore_preserves_repeat_count(self, tmp_path: Path) -> None:
        items = E2E_DEV[:2]
        result = run(
            GoldAnswerer(),
            items,
            results_dir=tmp_path,
            run_id="orig",
            repeats=3,
        )
        rescored = rescore(result.paths["jsonl"], ITEMS, tmp_path, run_id="rs")
        assert rescored.summary.repeats == 3
        assert len(rescored.records) == 6  # 2 items × 3 repeats

    def test_rescore_old_jsonl_no_repeat_field(self, tmp_path: Path) -> None:
        """A JSONL without a 'repeat' field (old format) rescores as K=1."""
        items = E2E_DEV[:1]
        # Write an old-style JSONL without the repeat field
        from courts_analyst.evaluation.scoring import score_item

        item = items[0]
        record = GoldAnswerer().answer(item)
        score = score_item(item, record)
        old_jsonl = tmp_path / "old.jsonl"
        old_jsonl.write_text(
            json.dumps(
                {
                    "question": item.question,
                    "record": record.model_dump(mode="json"),
                    "score": score.model_dump(mode="json"),
                }
            )
            + "\n"
        )
        rescored = rescore(old_jsonl, ITEMS, tmp_path, run_id="old-rs")
        # Inferred repeats = max(0) + 1 = 1 → stored as None in summary
        assert rescored.summary.repeats is None

    def test_rescore_scores_correctly(self, tmp_path: Path) -> None:
        items = E2E_DEV[:2]
        result = run(
            GoldAnswerer(),
            items,
            results_dir=tmp_path,
            run_id="orig2",
            repeats=2,
        )
        rescored = rescore(result.paths["jsonl"], ITEMS, tmp_path, run_id="rs2")
        # Gold answers should still score 100%
        assert rescored.summary.accuracy == pytest.approx(1.0)
        assert rescored.summary.pass_hat_k == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Old summaries without repeats fields still load (backward compat)
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_old_summary_loads_with_defaults(self) -> None:
        # A summary JSON as written before the repeats feature
        old = {
            "n": 5,
            "correct": 4,
            "accuracy": 0.8,
            "by_suite": {},
            "by_split": {},
            "by_check": {},
            "behavior_confusion": {},
            "behavior_metrics": {},
            "error_categories": {},
        }
        summary = RunSummary.model_validate(old)
        assert summary.repeats is None
        assert summary.accuracy_ci95 is None
        assert summary.pass_at_k is None
        assert summary.pass_hat_k is None
        assert summary.per_item == {}

    def test_markdown_no_repeats_block_for_k1(self, tmp_path: Path) -> None:
        from courts_analyst.evaluation.scoring.summary import summary_markdown

        old = RunSummary(
            n=2,
            correct=2,
            accuracy=1.0,
            behavior_confusion={},
            behavior_metrics={},
        )
        md = summary_markdown(old, "test")
        assert "Repeats" not in md
