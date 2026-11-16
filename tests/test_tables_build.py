"""Catalog build: reproducible, cross-checked, documented, and runnable from the CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pytest

from courts_analyst.pipeline.tables import __main__ as cli
from courts_analyst.pipeline.tables.build import build
from courts_analyst.pipeline.tables.load import load_measures
from courts_analyst.pipeline.tables.manifest import load_manifest

from .conftest import FIXTURE_RAW, MANIFEST_PATH, Catalog


def test_catalog_counts(catalog: Catalog, con: duckdb.DuckDBPyConnection) -> None:
    c = catalog.result.counts
    assert c["edition"] == 20
    assert c["observation"] > 30_000
    assert c["revision_log"] > 1_000
    assert catalog.result.errors == []
    assert catalog.result.warnings == []
    # every manifest table edition produced observations
    assert con.execute(
        "SELECT COUNT(DISTINCT file_id) FROM observation"
    ).fetchone() == (60,)


def test_format_cross_check_agrees(catalog: Catalog) -> None:
    """Where fixtures hold both xlsx and PDF, every printed value matches."""
    assert catalog.result.format_compared > 1_000
    assert catalog.result.format_mismatches == 0


def test_build_is_reproducible(catalog: Catalog, tmp_path: Path) -> None:
    again = build(load_manifest(MANIFEST_PATH), FIXTURE_RAW, tmp_path / "c.duckdb")
    assert again.checksum == catalog.result.checksum
    assert again.counts == {**catalog.result.counts}


def test_parquet_written(catalog: Catalog) -> None:
    pq = catalog.db.parent / "parquet"
    for t in ("observation", "source_file", "edition", "footnote", "revision_log"):
        assert (pq / f"{t}.parquet").stat().st_size > 0
    n = duckdb.sql(f"SELECT COUNT(*) FROM '{pq / 'observation.parquet'}'").fetchone()
    assert n == (catalog.result.counts["observation"],)


def test_revision_doc_tells_the_story(catalog: Catalog) -> None:
    doc = catalog.revision_doc.read_text()
    assert doc.startswith("# Revision log")
    assert "| 2020 | 554 (JB-2020) | 322 (JFF-2025) | -232 |" in doc
    assert "Do not edit by hand" in doc
    assert "## District and circuit figures" in doc


def test_every_measure_is_defined(con: duckdb.DuckDBPyConnection) -> None:
    used = {
        r[0]
        for r in con.execute("SELECT DISTINCT measure_id FROM observation").fetchall()
    }
    measures = load_measures()
    assert used <= set(measures)
    for mid, m in measures.items():
        assert m["label"] and m["definition"] and m["unit"], mid


def test_missing_primary_file_fails(tmp_path: Path) -> None:
    m = load_manifest(MANIFEST_PATH)
    m.tables = m.tables[:1]
    with pytest.raises(RuntimeError, match="raw file missing"):
        build(m, tmp_path, tmp_path / "c.duckdb")


def test_cli_build_reports_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only JB-2020 is present: the other X-1A editions fail loudly, exit 1."""
    shutil.copytree(FIXTURE_RAW / "JB-2020", tmp_path / "raw" / "tables" / "JB-2020")
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli.settings, "duckdb_path", None)
    rc = cli.main(
        ["build", "--families", "jb_x1a", "--revision-doc", str(tmp_path / "r.md")]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "JB-2016:X-1A:pdf: raw file missing" in err
    assert not (tmp_path / "build" / "courts.duckdb").exists()


def test_cli_build_one_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import yaml

    full = yaml.safe_load(MANIFEST_PATH.read_text())
    full["tables"] = [
        t
        for t in full["tables"]
        if t["edition"] == "JB-2020" and t["table_code"] == "X-1A"
    ]
    manifest = tmp_path / "m.yaml"
    manifest.write_text(yaml.safe_dump(full))
    raw = tmp_path / "raw" / "tables"
    shutil.copytree(FIXTURE_RAW / "JB-2020", raw / "JB-2020")
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli.settings, "duckdb_path", None)
    doc = tmp_path / "rev.md"
    assert (
        cli.main(["build", "--manifest", str(manifest), "--revision-doc", str(doc)])
        == 0
    )
    out = capsys.readouterr().out
    assert "build: 2 files, 1 editions, 828 observations" in out
    assert "0 mismatches" in out
    report = json.loads((tmp_path / "build" / "tables-report.json").read_text())
    assert report["counts"]["observation"] == 828
    assert (tmp_path / "build" / "courts.duckdb").is_file()
    assert doc.read_text().startswith("# Revision log")
