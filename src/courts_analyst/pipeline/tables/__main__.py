"""CLI: ``python -m courts_analyst.pipeline.tables {discover,fetch,build,all}``.

- ``discover``  crawl uscourts.gov and (re)write the committed manifest
- ``fetch``     download manifest files into DATA_DIR/raw/tables, pin sha256
- ``build``     parse the raw cache into DATA_DIR/build/courts.duckdb (offline)
- ``all``       fetch, then build (what ``make data-tables`` runs)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from courts_analyst.config import settings
from courts_analyst.pipeline.tables.build import build, fetch_all, write_report
from courts_analyst.pipeline.tables.families import FAMILIES
from courts_analyst.pipeline.tables.fetch import Fetcher
from courts_analyst.pipeline.tables.manifest import (
    discover,
    dump_manifest,
    load_manifest,
)
from courts_analyst.pipeline.tables.revision_log import write_revision_log

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "data" / "manifest" / "tables.yaml"
REVISION_DOC = ROOT / "docs" / "revision-log.md"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="courts_analyst.pipeline.tables", description=__doc__
    )
    p.add_argument("command", choices=["discover", "fetch", "build", "all"])
    p.add_argument("--manifest", type=Path, default=MANIFEST)
    p.add_argument(
        "--families", nargs="*", default=None, help="limit to these family keys"
    )
    p.add_argument(
        "--no-mirror", action="store_true", help="never fall back to Wayback"
    )
    p.add_argument(
        "--min-interval", type=float, default=2.0, help="seconds between requests"
    )
    p.add_argument("--revision-doc", type=Path, default=REVISION_DOC)
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr
    )

    raw_dir = settings.data_dir / "raw" / "tables"
    db_path = settings.resolved_duckdb_path
    parquet_dir = settings.data_dir / "build" / "parquet"
    families = [FAMILIES[k] for k in (args.families or FAMILIES)]

    if args.command == "discover":
        previous = load_manifest(args.manifest) if args.manifest.is_file() else None
        with Fetcher(min_interval=args.min_interval) as fetcher:
            manifest = discover(fetcher, families, previous)
        if args.families and previous:  # keep other families' entries
            keep = [t for t in previous.tables if t.family not in args.families]
            manifest.tables = keep + manifest.tables
            manifest.sorted()
        dump_manifest(manifest, args.manifest)
        print(f"manifest: {len(manifest.tables)} table editions → {args.manifest}")
        return 0

    manifest = load_manifest(args.manifest)
    if args.families:
        manifest.tables = [t for t in manifest.tables if t.family in args.families]

    fetch_report = None
    if args.command in ("fetch", "all"):
        with (
            Fetcher(min_interval=args.min_interval, max_retries=3) as fetcher,
            Fetcher(min_interval=1.0, max_retries=3) as mirror,
        ):
            fetch_report = fetch_all(
                manifest,
                raw_dir,
                fetcher,
                mirror=not args.no_mirror,
                mirror_fetcher=mirror,
            )
        if not args.families:
            dump_manifest(manifest, args.manifest)  # persist sha256 pins
        print(
            f"fetch: {fetch_report.downloaded} downloaded, "
            f"{fetch_report.cached} cached, "
            f"{len(fetch_report.from_mirror)} from mirror, "
            f"{len(fetch_report.failed)} failed"
        )
        for f in fetch_report.failed:
            print(f"  FAILED {f}", file=sys.stderr)
        if fetch_report.failed:
            return 1
        if args.command == "fetch":
            return 0

    try:
        result = build(manifest, raw_dir, db_path, parquet_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    write_report(
        result, settings.data_dir / "build" / "tables-report.json", fetch_report
    )
    write_revision_log(db_path, args.revision_doc)
    c = result.counts
    print(
        f"build: {c['source_file']} files, {c['edition']} editions, "
        f"{c['observation']} observations, {c['footnote']} footnotes, "
        f"{c['revision_log']} revised figures → {db_path}"
    )
    print(
        f"format cross-check: {result.format_compared} values compared, "
        f"{result.format_mismatches} mismatches"
    )
    print(f"observation checksum: {result.checksum}")
    for w in result.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
