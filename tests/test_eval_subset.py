"""Tests for the --agent-tools subset feature.

Covers:
- within_tools pure function (keeps/excludes correctly, no-tool items always kept)
- 'wxo' preset imports WXO_AGENT_TOOLS; custom comma-separated list works
- Unknown tool names in custom lists are fine (items with no expected_tools still pass)
- cli.main with --answerer gold --agent-tools wxo --tag smoke --split dev:
  prints the subset line, shows the new title in Markdown, writes subset meta to JSON
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from courts_analyst.evaluation.bank import load_bank, select, within_tools
from courts_analyst.evaluation.cli import main
from courts_analyst.evaluation.schema import QuestionItem
from courts_analyst.evaluation.wxo_agent import WXO_AGENT_TOOLS

ITEMS = load_bank()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    qid: str,
    expected_tools: list[str],
    suite: str = "e2e",
) -> QuestionItem:
    """Build a minimal QuestionItem for within_tools tests."""

    base: dict = {
        "id": qid,
        "suite": suite,
        "question": f"Synthetic question for {qid}?",
        "expected_tools": expected_tools,
    }
    if suite == "e2e":
        # e2e items need figures or ranking or claims
        base["expected"] = {
            "figures": [
                {
                    "value": 100.0,
                    "edition": "JB-2020",
                    "ref": {
                        "measure": "civil_cases_filed",
                        "court": "US",
                        "fiscal_year": 2020,
                        "edition": "JB-2020",
                    },
                }
            ]
        }
    return QuestionItem.model_validate(base)


# ---------------------------------------------------------------------------
# within_tools unit tests
# ---------------------------------------------------------------------------


class TestWithinTools:
    def test_item_with_all_tools_present_is_kept(self) -> None:
        tools: frozenset[str] = frozenset({"get_official_figure", "explain_change"})
        items = [_item("e2e-keep-01", ["get_official_figure"])]
        assert within_tools(items, tools) == items

    def test_item_with_missing_tool_is_excluded(self) -> None:
        tools: frozenset[str] = frozenset({"get_official_figure"})
        items = [_item("e2e-drop-01", ["find_cases"])]
        assert within_tools(items, tools) == []

    def test_item_with_no_expected_tools_is_always_kept(self) -> None:
        tools: frozenset[str] = frozenset()  # empty set
        items = [_item("e2e-no-tools-01", [])]
        assert within_tools(items, tools) == items

    def test_item_with_subset_of_tools_is_kept(self) -> None:
        tools: frozenset[str] = frozenset({"a", "b", "c"})
        items = [_item("e2e-subset-01", ["a", "b"])]
        assert within_tools(items, tools) == items

    def test_item_with_one_missing_tool_is_excluded(self) -> None:
        tools: frozenset[str] = frozenset({"a", "b"})
        items = [_item("e2e-onemiss-01", ["a", "b", "c"])]
        assert within_tools(items, tools) == []

    def test_mixed_list(self) -> None:
        tools: frozenset[str] = frozenset({"get_official_figure", "explain_change"})
        keep = _item("e2e-mixed-keep", ["get_official_figure"])
        drop = _item("e2e-mixed-drop", ["find_cases"])
        no_tools = _item("e2e-mixed-none", [])
        result = within_tools([keep, drop, no_tools], tools)
        assert keep in result
        assert drop not in result
        assert no_tools in result

    def test_empty_items_returns_empty(self) -> None:
        assert within_tools([], frozenset({"get_official_figure"})) == []


# ---------------------------------------------------------------------------
# Preset vs custom list
# ---------------------------------------------------------------------------


class TestPresetAndCustom:
    def test_wxo_preset_has_8_tools(self) -> None:
        assert len(WXO_AGENT_TOOLS) == 8

    def test_wxo_preset_contains_expected_names(self) -> None:
        expected = {
            "get_official_figure",
            "explain_change",
            "compare_courts",
            "judgeship_context",
            "explain_term",
            "check_inquiry_eligibility",
            "keep_answer",
            "my_requests",
        }
        assert expected == WXO_AGENT_TOOLS

    def test_within_tools_with_wxo_preset(self) -> None:
        smoke_dev = select(ITEMS, split="dev", tags=["smoke"])
        subset = within_tools(smoke_dev, WXO_AGENT_TOOLS)
        # Known result from the bank: 20 of 25 smoke-dev items have all tools on wxo
        assert len(smoke_dev) == 25
        assert len(subset) == 20

    def test_wxo_idb_preset_adds_the_case_tools(self) -> None:
        from courts_analyst.evaluation.wxo_agent import WXO_PRESETS

        assert WXO_PRESETS["wxo"] == WXO_AGENT_TOOLS
        assert WXO_PRESETS["wxo-idb"] - WXO_AGENT_TOOLS == {
            "find_cases",
            "analyze_cohort",
            "sample_dockets",
            "reconcile",
        }

    def test_unknown_tool_names_are_fine(self) -> None:
        """Custom list with tool names not in the bank is not an error."""
        custom: frozenset[str] = frozenset({"totally_unknown_tool", "another_fake"})
        items_no_tools = [i for i in ITEMS if not i.expected_tools]
        result = within_tools(items_no_tools, custom)
        # No-tool items always pass through
        assert result == items_no_tools

    def test_custom_list_strips_spaces_and_ignores_empty_entries(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """'a, b,' is parsed as {'a', 'b'} — spaces stripped, trailing comma ignored."""
        args = [
            "run",
            "--answerer",
            "gold",
            "--agent-tools",
            "get_official_figure, explain_change,",  # trailing comma + spaces
            "--tag",
            "smoke",
            "--split",
            "dev",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        rc = main(args)
        assert rc == 0
        # Items requiring only get_official_figure or explain_change (or none)
        # should be in the subset; verify the run completed without error.
        summary_file = next(tmp_path.glob("*.summary.json"))
        data = json.loads(summary_file.read_text())
        # Tools stored sorted; spaces stripped, empty entry dropped
        assert data["subset"]["tools"] == ["explain_change", "get_official_figure"]


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLISubset:
    def test_subset_line_printed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--agent-tools",
            "wxo",
            "--tag",
            "smoke",
            "--split",
            "dev",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        rc = main(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "subset: 20 of 25 items have all expected tools on the agent" in out

    def test_markdown_title_shows_subset(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--agent-tools",
            "wxo",
            "--tag",
            "smoke",
            "--split",
            "dev",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        main(args)
        out = capsys.readouterr().out
        # Title line uses the new format: X/N on the wxo subset (N of M items in the slice)
        assert "on the wxo subset" in out
        assert "20 of 25 items in the slice" in out

    def test_summary_json_has_subset_meta(self, tmp_path: Path) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--agent-tools",
            "wxo",
            "--tag",
            "smoke",
            "--split",
            "dev",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        main(args)
        summary_file = next(tmp_path.glob("*.summary.json"))
        data = json.loads(summary_file.read_text())
        assert "subset" in data
        subset = data["subset"]
        assert subset["n_slice"] == 25
        assert subset["n_subset"] == 20
        assert subset["preset"] == "wxo"
        assert "get_official_figure" in subset["tools"]

    def test_label_has_subset_suffix(self, tmp_path: Path) -> None:
        args = [
            "run",
            "--answerer",
            "gold",
            "--agent-tools",
            "wxo",
            "--tag",
            "smoke",
            "--split",
            "dev",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        main(args)
        summary_file = next(tmp_path.glob("*.summary.json"))
        data = json.loads(summary_file.read_text())
        assert data["label"].endswith("-subset")

    def test_subset_title_with_repeats_uses_item_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With --repeats 3, the title denominator is the item count (20), not
        the total attempt count (60), and the numerator is mean correct/run."""
        args = [
            "run",
            "--answerer",
            "gold",
            "--agent-tools",
            "wxo",
            "--tag",
            "smoke",
            "--split",
            "dev",
            "--repeats",
            "3",
            "--results-dir",
            str(tmp_path),
            "--quiet",
        ]
        main(args)
        out = capsys.readouterr().out
        # Gold is always correct: mean = 20.0 / 1 attempt = 20.0 items correct per run
        # Denominator must be 20 (items), not 60 (attempts)
        assert "/20 on the wxo subset" in out
        assert "20 of 25 items in the slice" in out
