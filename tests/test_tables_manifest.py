"""Manifest discovery (mocked uscourts.gov), round-trip, and fetch_all fallback."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import httpx
import pytest

from courts_analyst.pipeline.tables.build import WAYBACK, fetch_all
from courts_analyst.pipeline.tables.families import FAMILIES
from courts_analyst.pipeline.tables.fetch import Fetcher
from courts_analyst.pipeline.tables.manifest import (
    FileEntry,
    Manifest,
    TableEntry,
    discover,
    dump_manifest,
    landing_files,
    load_manifest,
)
from courts_analyst.pipeline.tables.records import Series

from .conftest import MANIFEST_PATH

LISTING_0 = """
<a href="/data-news/data-tables/2015/09/30/judicial-business/x-1a">old</a>
<a href="/data-news/data-tables/2020/09/30/judicial-business/x-1a">2020</a>
<a href="/data-news/data-tables/2020/06/30/statistical-tables-federal-judiciary/x-1a">June</a>
<a href="/data-news/data-tables/2021/03/31/federal-judicial-caseload-statistics/x-1a">Mar</a>
<a href="?page=1">next</a>
"""
LISTING_1 = """
<a href="/data-news/data-tables/2024/09/30/judicial-business/x-1a">2024</a>
<a href="?page=0">first</a>
"""
LANDING_2020 = """<title>Table X-1A&mdash;Other Judicial Business (September 30, 2020)</title>
<a href="/sites/default/files/data_tables/jb_x1a_0930.2020.pdf">PDF</a>
<a href="/sites/default/files/data_tables/jb_x1a_0930.2020.xlsx">XLSX</a>
<a href="/sites/default/files/other.pdf">unrelated</a>"""
LANDING_2024 = """<title>Table X-1A</title>
<a href="/sites/default/files/2025-01/jb_x1a_0930.2024.pdf">PDF</a>"""


def _site(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    pages = {
        "https://www.uscourts.gov/data-table-numbers/x-1a": LISTING_0,
        "https://www.uscourts.gov/data-table-numbers/x-1a?page=1": LISTING_1,
        "https://www.uscourts.gov/data-news/data-tables/2020/09/30/judicial-business/x-1a": LANDING_2020,
        "https://www.uscourts.gov/data-news/data-tables/2024/09/30/judicial-business/x-1a": LANDING_2024,
    }
    return httpx.Response(200, text=pages[url]) if url in pages else httpx.Response(404)


def _fetcher(handler) -> Fetcher:  # type: ignore[no-untyped-def]
    return Fetcher(
        httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval=0,
        backoff=0,
        max_retries=1,
        sleep=lambda s: None,
    )


def test_discover_follows_pagination_and_filters_series() -> None:
    prev = Manifest(
        tables=[
            TableEntry(
                "jb_x1a", Series.JB, "X-1A", "JB-2020", date(2020, 9, 30), "u",
                files={"xlsx": FileEntry("u", "pinned-sha")},
            )
        ]
    )  # fmt: skip
    m = discover(_fetcher(_site), [FAMILIES["jb_x1a"]], prev, today=date(2026, 9, 26))
    assert [t.edition for t in m.tables] == [
        "JB-2020",
        "JB-2024",
    ]  # 2015 < first_edition
    t2020, t2024 = m.tables
    assert t2020.title == "Table X-1A—Other Judicial Business (September 30, 2020)"
    assert set(t2020.files) == {"pdf", "xlsx"}
    assert t2020.files["xlsx"].sha256 == "pinned-sha"  # pins survive rediscovery
    assert t2024.files["pdf"].url.endswith("/2025-01/jb_x1a_0930.2024.pdf")
    assert t2024.primary_format == "pdf" and t2020.primary_format == "xlsx"
    assert m.generated == "2026-09-26"


def test_landing_files_ignores_other_tables() -> None:
    files = landing_files(LANDING_2020, FAMILIES["jb_c1"], date(2020, 9, 30))
    assert files == {}


def test_manifest_roundtrip(tmp_path: Path) -> None:
    m = load_manifest(MANIFEST_PATH)
    out = tmp_path / "m.yaml"
    dump_manifest(m, out)
    again = load_manifest(out)
    assert [(t.edition, t.table_code, sorted(t.files)) for t in again.tables] == [
        (t.edition, t.table_code, sorted(t.files)) for t in m.tables
    ]
    assert out.read_text().startswith("# Official uscourts.gov tables")


def test_committed_manifest_is_complete_and_pinned() -> None:
    m = load_manifest(MANIFEST_PATH)
    assert len(m.tables) == 60
    assert {t.family for t in m.tables} == set(FAMILIES)
    for t in m.tables:
        assert 2016 <= t.period_end.year <= 2025
        for f in t.files.values():
            assert f.url.startswith("https://www.uscourts.gov/")
            assert f.sha256 and len(f.sha256) == 64, t.edition


def test_committed_fixtures_match_pins() -> None:
    """Fixture files are byte-identical to what the manifest pinned."""
    from .conftest import FIXTURE_RAW

    m = load_manifest(MANIFEST_PATH)
    checked = 0
    for t in m.tables:
        for fmt, f in t.files.items():
            p = t.raw_path(FIXTURE_RAW, fmt)
            if p.is_file():
                assert hashlib.sha256(p.read_bytes()).hexdigest() == f.sha256, p
                checked += 1
    assert checked >= 60


def _one_table(url: str) -> Manifest:
    return Manifest(
        tables=[
            TableEntry(
                "jb_x1a", Series.JB, "X-1A", "JB-2020", date(2020, 9, 30), "landing",
                files={"xlsx": FileEntry(url)},
            )
        ]
    )  # fmt: skip


def test_fetch_all_pins_and_falls_back_to_mirror(tmp_path: Path) -> None:
    url = (
        "https://www.uscourts.gov/sites/default/files/data_tables/jb_x1a_0930.2020.xlsx"
    )
    body = b"workbook bytes"

    def origin(r: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    def mirror(r: httpx.Request) -> httpx.Response:
        assert str(r.url) == WAYBACK.format(url=url)
        return httpx.Response(200, content=body)

    m = _one_table(url)
    rep = fetch_all(m, tmp_path, _fetcher(origin), mirror_fetcher=_fetcher(mirror))
    assert rep.from_mirror == [url] and rep.downloaded == 1 and not rep.failed
    assert m.tables[0].files["xlsx"].sha256 == hashlib.sha256(body).hexdigest()
    # Second run: pinned and cached, no requests at all.
    rep2 = fetch_all(m, tmp_path, _fetcher(origin), mirror_fetcher=_fetcher(origin))
    assert rep2.cached == 1 and rep2.downloaded == 0


def test_fetch_all_reports_failures(tmp_path: Path) -> None:
    m = _one_table("https://www.uscourts.gov/x.xlsx")
    dead = _fetcher(lambda r: httpx.Response(503))
    assert fetch_all(m, tmp_path, dead, mirror=False).failed
    assert fetch_all(m, tmp_path, dead, mirror_fetcher=dead).failed


@pytest.mark.parametrize("fmt", ["xlsx", "pdf"])
def test_raw_path_layout(fmt: str) -> None:
    t = load_manifest(MANIFEST_PATH).tables[5]
    if fmt in t.files:
        assert t.raw_path(Path("raw"), fmt).parent == Path("raw") / t.edition


def test_cli_discover_and_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`discover` writes a manifest from the (mocked) site; `fetch` pins shas."""
    from courts_analyst.pipeline.tables import __main__ as cli

    def site(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith((".xlsx", ".pdf")):
            return httpx.Response(200, content=b"bytes of " + str(request.url).encode())
        return _site(request)

    monkeypatch.setattr(
        cli,
        "Fetcher",
        lambda **kw: Fetcher(
            httpx.Client(transport=httpx.MockTransport(site)), min_interval=0
        ),
    )
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path)
    manifest = tmp_path / "tables.yaml"
    assert (
        cli.main(["discover", "--families", "jb_x1a", "--manifest", str(manifest)]) == 0
    )
    m = load_manifest(manifest)
    assert [t.edition for t in m.tables] == ["JB-2020", "JB-2024"]
    assert cli.main(["fetch", "--manifest", str(manifest), "--no-mirror"]) == 0
    pinned = load_manifest(manifest)
    assert all(f.sha256 for t in pinned.tables for f in t.files.values())
    assert (tmp_path / "raw" / "tables" / "JB-2024" / "jb_x1a_0930.2024.pdf").is_file()


def test_cli_fetch_failure_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from courts_analyst.pipeline.tables import __main__ as cli

    manifest = tmp_path / "m.yaml"
    dump_manifest(_one_table("https://www.uscourts.gov/gone.xlsx"), manifest)
    monkeypatch.setattr(
        cli,
        "Fetcher",
        lambda **kw: _fetcher(lambda r: httpx.Response(404)),
    )
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path)
    assert cli.main(["fetch", "--manifest", str(manifest)]) == 1
