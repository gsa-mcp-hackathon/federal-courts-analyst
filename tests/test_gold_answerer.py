"""Harness sanity: gold answers score 100%, silence scores 0%, and the runner
and CLI write their outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from courts_analyst.evaluation.answerers import (
    ANSWERERS,
    Answerer,
    GoldAnswerer,
    NullAnswerer,
)
from courts_analyst.evaluation.bank import load_bank, select
from courts_analyst.evaluation.cli import main
from courts_analyst.evaluation.records import AnswerRecord, ToolCall
from courts_analyst.evaluation.runner import run
from courts_analyst.evaluation.schema import Claim, QuestionItem
from courts_analyst.evaluation.scoring import score_item
from courts_analyst.evaluation.scoring.claims import (
    check_claim,
    courts_mentioned_in_order,
    resolve_path,
)

ITEMS = load_bank()


def test_gold_scores_100_percent(tmp_path: Path) -> None:
    result = run(GoldAnswerer(), ITEMS, results_dir=tmp_path)
    wrong = [s.question_id for s in result.scores if not s.correct]
    assert not wrong
    assert result.summary.accuracy == 1.0
    for m in result.summary.behavior_metrics.values():
        assert m.precision in (1.0, None) and m.recall in (1.0, None)


def test_null_scores_0_percent(tmp_path: Path) -> None:
    result = run(NullAnswerer(), ITEMS, results_dir=tmp_path)
    right = [s.question_id for s in result.scores if s.correct]
    assert not right, "these items can be passed by saying nothing"
    assert result.summary.accuracy == 0.0


def test_answerers_satisfy_protocol() -> None:
    for factory in ANSWERERS.values():
        assert isinstance(factory(), Answerer)


def test_runner_outputs(tmp_path: Path) -> None:
    items = select(ITEMS, suite="e2e", split="dev")[:3]
    result = run(
        GoldAnswerer(), items, label="e2e-dev", results_dir=tmp_path, run_id="r1"
    )
    lines = result.paths["jsonl"].read_text().splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert set(first) == {"question", "record", "score", "repeat"}
    assert first["repeat"] == 0
    summary = json.loads(result.paths["summary"].read_text())
    assert summary["run_id"] == "r1" and summary["items"] == [i.id for i in items]
    assert "gold · e2e-dev" in result.paths["markdown"].read_text()


class Boom:
    name = "boom"

    def answer(self, item: QuestionItem) -> AnswerRecord:
        raise RuntimeError("model API down")


def test_answerer_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    result = run(Boom(), ITEMS[:2], results_dir=tmp_path)
    assert all(r.error == "RuntimeError: model API down" for r in result.records)
    assert {s.error_category for s in result.scores} == {"answerer_failure"}


def test_error_taxonomy() -> None:
    item = next(i for i in ITEMS if i.id == "fy2020-weighted-civil-national")
    base = {"question_id": item.id, "answerer": "t"}
    no_tool = AnswerRecord(**base, final_text="554 (JB-2020)")
    assert score_item(item, no_tool).error_category == "tool_selection"
    bad_args = AnswerRecord(
        **base, tool_calls=[ToolCall(name="get_official_figure", error="unknown court")]
    )
    assert score_item(item, bad_args).error_category == "argument"
    misread = AnswerRecord(
        **base,
        final_text="It was 999 (JFF-2023).",
        tool_calls=[
            ToolCall(name="get_official_figure", output={"value": 322.2, "first": 554})
        ],
    )
    assert score_item(item, misread).error_category == "hallucinated_number"
    ignored = AnswerRecord(
        **base,
        final_text="I don't know.",
        tool_calls=[ToolCall(name="get_official_figure", output={"value": 322.2})],
    )
    assert score_item(item, ignored).error_category == "output_interpretation"
    decline_item = next(i for i in ITEMS if i.id == "adv-rank-judges-sdny")
    answered = AnswerRecord(
        question_id=decline_item.id, answerer="t", final_text="Sure."
    )
    assert score_item(decline_item, answered).error_category == "task_understanding"


def test_claims() -> None:
    record = AnswerRecord(
        question_id="q",
        answerer="t",
        final_text="The N.D. Fla. MDL drove it.",
        tool_calls=[
            ToolCall(
                name="explain_change",
                output={"provenance": [{"revision_status": "revised", "n": 5}]},
            )
        ],
    )

    def c(**kw: object) -> bool:
        return check_claim(Claim.model_validate({"id": "c", **kw}), record)

    assert c(kind="mentions", any=["n.d. fla", "x"])
    assert c(kind="mentions", all=["MDL", "N.D. Fla."])
    assert not c(kind="mentions", all=["MDL", "pandemic"])
    assert c(kind="not_mentions", any=["pandemic"])
    assert not c(kind="not_mentions", all=["MDL"])
    path = "provenance[].revision_status"
    assert c(kind="field", path=path, op="in", value=["revised"])
    assert c(kind="field", path=path, op="eq", value="revised")
    assert c(kind="field", path=path, op="contains", value="vis")
    assert c(kind="field", path=path, op="exists")
    assert c(kind="field", path="provenance[].n", op="gte", value=5)
    assert c(kind="field", path="provenance[].n", op="lte", value=5)
    assert not c(kind="field", path="provenance[].n", op="gte", value="x")
    assert not c(kind="field", path="missing.path", op="exists")
    assert c(kind="tool_called", tool="explain_change")
    assert c(kind="tool_not_called", tool="reconcile")
    assert list(resolve_path({"a": [[1, 2], [3]]}, "a[].[]")) == [1, 2, 3]
    assert list(resolve_path({"a": 1}, "a[]")) == []
    with pytest.raises(ValueError, match="unknown op"):
        from courts_analyst.evaluation.scoring.claims import _compare

        _compare(1, "between", 2)


def test_court_mentions() -> None:
    text = "1. N.D. Fla.; 2. Eastern District of North Carolina; 3. E.D. Cal."
    assert courts_mentioned_in_order(["FL-N", "NC-E", "CA-E"], text) == (True, True)
    assert courts_mentioned_in_order(["NC-E", "FL-N"], text) == (True, False)
    assert courts_mentioned_in_order(["TX-W"], text) == (False, False)
    # Short codes like "ME" must not match ordinary words.
    assert courts_mentioned_in_order(["ME"], "tell me more") == (False, False)


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate"]) == 0
    assert "questions valid" in capsys.readouterr().out
    assert main(["stats"]) == 0
    assert "| engine |" in capsys.readouterr().out
    args = ["run", "--answerer", "gold", "--suite", "e2e", "--split", "dev"]
    assert main([*args, "--limit", "2", "--results-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "✓" in out and "2/2 correct" in out
    summary = next(tmp_path.glob("*.summary.json"))
    assert main(["show", str(summary)]) == 0
    assert "2/2 correct" in capsys.readouterr().out
    one = ["run", "--answerer", "null", "--limit", "1", "--quiet"]
    assert main([*one, "--results-dir", str(tmp_path), "--expect-accuracy", "0"]) == 0
    assert main([*one, "--results-dir", str(tmp_path), "--expect-accuracy", "1"]) == 1
    assert main(["run", "--answerer", "nope"]) == 2
    assert main(["run", "--answerer", "gold", "--id", "no-such-id"]) == 1
    assert main(["--bank", str(tmp_path), "validate"]) == 1


def test_gold_satisfies_field_and_tool_claims() -> None:
    claims = [
        {"id": "a", "kind": "field", "path": "provenance[].status", "op": "in",
         "value": ["revised"]},
        {"id": "b", "kind": "field", "path": "data.n", "op": "gte", "value": 30},
        {"id": "c", "kind": "field", "path": "items[]", "op": "exists"},
        {"id": "e", "kind": "tool_called", "tool": "reconcile"},
        {"id": "f", "kind": "mentions", "all": ["MDL"], "any": ["N.D. Fla."]},
    ]  # fmt: skip
    item = QuestionItem.model_validate(
        {
            "id": "synthetic-claims",
            "suite": "explanation",
            "question": "Why did the synthetic figure change?",
            "claims": claims,
            "expected_tools": ["explain_change"],
        }
    )
    record = GoldAnswerer().answer(item)
    assert record.tools_called == ["explain_change", "reconcile"]
    assert score_item(item, record).correct
