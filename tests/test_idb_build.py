"""The IDB build end to end on the committed sample: tables, reproducibility, CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pytest

from courts_analyst.pipeline.idb import __main__ as cli
from courts_analyst.pipeline.idb.load import write_report
from courts_analyst.pipeline.idb.manifest import dump_manifest, load_manifest
from courts_analyst.pipeline.idb.profile import write_profile
from tests.conftest import (
    IDB_MANIFEST_PATH,
    IDB_SAMPLE_ZIP,
    IdbBuild,
    build_idb_from_zip,
)

EXPECTED_TABLES = {
    "idb_release",
    "idb_civil_raw",
    "idb_civil_record",
    "idb_civil",
    "idb_civil_terminations",
    "code_validity",
    "data_breaks",
    "idb_unknown_code",
    "code_nos",
    "code_origin",
    "code_district",
}


def test_tables_and_views(idb_con: duckdb.DuckDBPyConnection) -> None:
    names = {
        r[0]
        for r in idb_con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert names >= EXPECTED_TABLES
    views = {
        r[0]
        for r in idb_con.execute(
            "SELECT view_name FROM duckdb_views() WHERE NOT internal"
        ).fetchall()
    }
    assert views == {"idb_civil", "idb_civil_terminations"}


def test_release_row_records_provenance(idb_con: duckdb.DuckDBPyConnection) -> None:
    rel = idb_con.execute(
        "SELECT url, sha256, schema, fy_from, fy_to, codebook_url FROM idb_release"
    ).fetchone()
    manifest = load_manifest(IDB_MANIFEST_PATH)
    assert rel == (
        manifest.data.url,
        manifest.data.sha256,
        "civil-1988-on",
        2015,
        2025,
        manifest.codebook.url,
    )


def test_raw_has_no_judge_or_unused_columns(idb_con: duckdb.DuckDBPyConnection) -> None:
    cols = {r[0] for r in idb_con.execute("DESCRIBE idb_civil_raw").fetchall()}
    assert not cols & {
        "filejudg",
        "filemag",
        "termjudg",
        "termmag",
        "djoined",
        "plt",
        "def",
    }
    assert {"record_id", "case_key", "record_seq", "fdateuse", "tapeyear"} <= cols


def test_no_unknown_codes_or_warnings_in_sample(idb: IdbBuild) -> None:
    assert idb.result.unknown_codes == {}
    assert idb.result.warnings == []


def test_rebuild_is_reproducible(idb: IdbBuild, tmp_path: Path) -> None:
    again = build_idb_from_zip(IDB_SAMPLE_ZIP, tmp_path)
    assert again.result.checksum == idb.result.checksum
    assert again.result.counts == idb.result.counts


def test_report_and_profile(idb: IdbBuild, tmp_path: Path) -> None:
    write_report(idb.result, tmp_path / "r.json", {"timing_seconds": {"total": 1}})
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["record_checksum"] == idb.result.checksum
    assert data["counts"]["idb_civil_record"] > 0
    write_profile(idb.db, tmp_path / "profile.md")
    text = (tmp_path / "profile.md").read_text()
    for heading in (
        "## Release",
        "## By fiscal year",
        "## By district",
        "## Null rates",
        "## Codes not in the codebook",
        "### NOS",
        "## Data breaks",
    ):
        assert heading in text
    assert "| FY2020 |" in text and "FY2026 (partial)" in text
    assert "Florida, Northern" in text


def test_profile_lists_unknown_codes(tmp_path: Path) -> None:
    from tests.idb_rows import row, write_zip

    b = build_idb_from_zip(write_zip(tmp_path / "in.zip", [row(NOS="999")]), tmp_path)
    write_profile(b.db, tmp_path / "p.md")
    text = (tmp_path / "p.md").read_text()
    assert "| NOS | 999 | 1 |" in text


def test_manifest_roundtrip(tmp_path: Path) -> None:
    m = load_manifest(IDB_MANIFEST_PATH)
    dump_manifest(m, tmp_path / "idb.yaml")
    assert load_manifest(tmp_path / "idb.yaml") == m
    (tmp_path / "bad.yaml").write_text("version: 99\n")
    with pytest.raises(ValueError, match="unsupported"):
        load_manifest(tmp_path / "bad.yaml")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(cli.settings, "idb_duckdb_path", None)
    return tmp_path / "data"


def test_cli_build_from_zip(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = tmp_path / "profile.md"
    rc = cli.main(["build", "--zip", str(IDB_SAMPLE_ZIP), "--profile-doc", str(doc)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "build:" in out and "record checksum:" in out
    assert (data_dir / "build" / "idb.duckdb").is_file()
    assert (data_dir / "private" / "idb_parties.parquet").is_file()
    assert not (data_dir / "build" / "idb-normalized.tsv").exists()
    report = json.loads((data_dir / "build" / "idb-report.json").read_text())
    assert report["normalize"]["rows"] > 0 and report["timing_seconds"]["total"] >= 0
    assert doc.is_file()


def test_cli_sample(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_zip = tmp_path / "s.zip"
    rc = cli.main(
        ["sample", "--zip", str(IDB_SAMPLE_ZIP), "--sample-out", str(out_zip)]
    )
    assert rc == 0 and out_zip.is_file()
    assert "sample:" in capsys.readouterr().out


def test_cli_build_without_download(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["build"]) == 1
    assert "not found" in capsys.readouterr().err


def test_cli_fetch_uses_pins(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With the pinned files already on disk, fetch sends nothing and keeps pins."""
    from courts_analyst.pipeline.idb import fetch as fetch_mod

    manifest = load_manifest(IDB_MANIFEST_PATH)
    mpath = tmp_path / "idb.yaml"
    shutil.copy(IDB_MANIFEST_PATH, mpath)
    raw = data_dir / "raw" / "idb"
    raw.mkdir(parents=True)
    (raw / "cv88on.zip").write_bytes(b"zip")
    (raw / "codebook.pdf").write_bytes(b"pdf")

    calls: list[str] = []

    def fake(
        self: object,
        url: str,
        dest: Path,
        pin: fetch_mod.Pin | None = None,
        *,
        accept_new: bool = False,
    ) -> fetch_mod.DownloadResult:
        calls.append(url)
        return fetch_mod.DownloadResult(
            url, dest, pin.sha256 or "", 3, "cached", None, None, 0
        )  # type: ignore[union-attr]

    monkeypatch.setattr(fetch_mod.Downloader, "download", fake)
    assert cli.main(["fetch", "--manifest", str(mpath)]) == 0
    assert calls == [manifest.data.url, manifest.codebook.url]
    assert load_manifest(mpath) == manifest
    assert "cached" in capsys.readouterr().out


def test_cli_fetch_reports_release_change(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from courts_analyst.pipeline.idb import fetch as fetch_mod

    def boom(*a: object, **k: object) -> None:
        raise fetch_mod.ReleaseChangedError("u", "a" * 64, "b" * 64)

    monkeypatch.setattr(fetch_mod.Downloader, "download", boom)
    mpath = tmp_path / "idb.yaml"
    shutil.copy(IDB_MANIFEST_PATH, mpath)
    assert cli.main(["fetch", "--manifest", str(mpath)]) == 1
    assert "--accept-new-release" in capsys.readouterr().err
