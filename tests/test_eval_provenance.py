"""Tests for the --provenance feature in runner.run and summary_markdown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from courts_analyst.evaluation.answerers import GoldAnswerer
from courts_analyst.evaluation.bank import load_bank, select
from courts_analyst.evaluation.cli import main
from courts_analyst.evaluation.runner import run
from courts_analyst.evaluation.scoring.summary import summary_markdown

_ITEMS = load_bank()
_E2E_DEV = select(_ITEMS, suite="e2e", split="dev")[:2]


# ---------------------------------------------------------------------------
# runner.run with provenance
# ---------------------------------------------------------------------------


class TestRunnerProvenance:
    def test_provenance_written_to_summary_json(self, tmp_path: Path) -> None:
        prov = {"model": "test-model", "version": "v1"}
        result = run(
            GoldAnswerer(),
            _E2E_DEV,
            results_dir=tmp_path,
            provenance=prov,
        )
        data = json.loads(result.paths["summary"].read_text())
        assert "provenance" in data
        assert data["provenance"]["model"] == "test-model"
        assert data["provenance"]["version"] == "v1"

    def test_provenance_enriched_with_bank_commit(self, tmp_path: Path) -> None:
        prov = {"model": "test-model"}
        result = run(
            GoldAnswerer(),
            _E2E_DEV,
            results_dir=tmp_path,
            provenance=prov,
        )
        data = json.loads(result.paths["summary"].read_text())
        # bank_commit is present (may be a SHA or None)
        assert "bank_commit" in data["provenance"]

    def test_provenance_enriched_with_split(self, tmp_path: Path) -> None:
        prov = {"model": "test-model"}
        result = run(
            GoldAnswerer(),
            _E2E_DEV,
            results_dir=tmp_path,
            provenance=prov,
            split="dev",
        )
        data = json.loads(result.paths["summary"].read_text())
        assert data["provenance"]["split"] == "dev"

    def test_provenance_enriched_with_repeats_and_run_date(
        self, tmp_path: Path
    ) -> None:
        prov = {"model": "test-model"}
        result = run(
            GoldAnswerer(),
            _E2E_DEV,
            results_dir=tmp_path,
            provenance=prov,
            repeats=2,
        )
        data = json.loads(result.paths["summary"].read_text())
        assert data["provenance"]["repeats"] == 2
        assert "run_date" in data["provenance"]

    def test_no_provenance_key_absent_from_summary(self, tmp_path: Path) -> None:
        result = run(
            GoldAnswerer(),
            _E2E_DEV,
            results_dir=tmp_path,
        )
        data = json.loads(result.paths["summary"].read_text())
        assert "provenance" not in data

    def test_provenance_in_markdown(self, tmp_path: Path) -> None:
        prov = {"model": "test-model", "experiment": "exp-01"}
        result = run(
            GoldAnswerer(),
            _E2E_DEV,
            results_dir=tmp_path,
            provenance=prov,
        )
        md = result.paths["markdown"].read_text()
        assert "Provenance" in md
        assert "model" in md
        assert "test-model" in md


# ---------------------------------------------------------------------------
# CLI --provenance flag
# ---------------------------------------------------------------------------


class TestCLIProvenance:
    def test_provenance_flag_reads_json_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        prov_file = tmp_path / "prov.json"
        prov_file.write_text(json.dumps({"model": "my-model", "run": "42"}))

        rc = main(
            [
                "run",
                "--answerer",
                "gold",
                "--suite",
                "e2e",
                "--split",
                "dev",
                "--limit",
                "1",
                "--results-dir",
                str(tmp_path),
                "--quiet",
                "--provenance",
                str(prov_file),
            ]
        )
        assert rc == 0
        summary_file = next(tmp_path.glob("*.summary.json"))
        data = json.loads(summary_file.read_text())
        assert data["provenance"]["model"] == "my-model"
        assert data["provenance"]["run"] == "42"

    def test_provenance_in_cli_markdown_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        prov_file = tmp_path / "prov.json"
        prov_file.write_text(json.dumps({"source": "nightly"}))

        main(
            [
                "run",
                "--answerer",
                "gold",
                "--suite",
                "e2e",
                "--split",
                "dev",
                "--limit",
                "1",
                "--results-dir",
                str(tmp_path),
                "--quiet",
                "--provenance",
                str(prov_file),
            ]
        )
        out = capsys.readouterr().out
        assert "Provenance" in out
        assert "source" in out
        assert "nightly" in out


# ---------------------------------------------------------------------------
# summary_markdown provenance section (unit)
# ---------------------------------------------------------------------------


class TestSummaryMarkdownProvenance:
    def _minimal_summary(self) -> object:
        from courts_analyst.evaluation.scoring.summary import RunSummary

        return RunSummary(
            n=1,
            correct=1,
            accuracy=1.0,
            behavior_confusion={},
            behavior_metrics={},
        )

    def test_provenance_section_present(self) -> None:
        summary = self._minimal_summary()
        prov = {"model": "m1", "bank_commit": "abc123", "split": "dev"}
        md = summary_markdown(summary, "t", provenance=prov)  # type: ignore[arg-type]
        assert "**Provenance**" in md
        for k, v in prov.items():
            assert str(k) in md
            assert str(v) in md

    def test_provenance_section_absent_when_none(self) -> None:
        summary = self._minimal_summary()
        md = summary_markdown(summary, "t")  # type: ignore[arg-type]
        assert "Provenance" not in md
