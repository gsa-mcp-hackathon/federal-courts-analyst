"""CLI: ``python -m courts_analyst.pipeline.idb {fetch,build,sample,profile,all}``.

- ``fetch``    download the pinned civil IDB release (resumable) and codebook
- ``build``    normalize and load it into DATA_DIR/build/idb.duckdb (offline)
- ``profile``  regenerate docs/data-profile.md from the built database
- ``sample``   write the committed CI fixture (tests/fixtures/idb/)
- ``all``      fetch, build, profile (what ``make data-idb`` runs)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from courts_analyst.config import settings
from courts_analyst.pipeline.idb.fetch import Downloader, Pin, ReleaseChangedError
from courts_analyst.pipeline.idb.load import build_idb, write_report
from courts_analyst.pipeline.idb.manifest import dump_manifest, load_manifest
from courts_analyst.pipeline.idb.normalize import normalize_zip
from courts_analyst.pipeline.idb.profile import write_profile
from courts_analyst.pipeline.idb.sample import build_sample
from courts_analyst.pipeline.tables.fetch import FetchError

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "data" / "manifest" / "idb.yaml"
PROFILE_DOC = ROOT / "docs" / "data-profile.md"
SAMPLE_ZIP = ROOT / "tests" / "fixtures" / "idb" / "cv_sample.zip"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="courts_analyst.pipeline.idb", description=__doc__)
    p.add_argument("command", choices=["fetch", "build", "profile", "sample", "all"])
    p.add_argument("--manifest", type=Path, default=MANIFEST)
    p.add_argument(
        "--zip", type=Path, default=None, help="build from this zip, not the download"
    )
    p.add_argument("--fy-from", type=int, default=None)
    p.add_argument("--fy-to", type=int, default=None)
    p.add_argument(
        "--accept-new-release",
        action="store_true",
        help="build from whatever release the FJC now serves and re-pin it",
    )
    p.add_argument("--profile-doc", type=Path, default=PROFILE_DOC)
    p.add_argument("--sample-out", type=Path, default=SAMPLE_ZIP)
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr
    )

    manifest = load_manifest(args.manifest)
    raw_dir = settings.data_dir / "raw" / "idb"
    zip_path = args.zip or raw_dir / manifest.file_name
    db_path = settings.resolved_idb_path
    fy_from = args.fy_from or manifest.fy_from
    fy_to = args.fy_to or manifest.fy_to

    if args.command in ("fetch", "all"):
        try:
            with Downloader() as dl:
                data = dl.download(
                    manifest.data.url,
                    zip_path,
                    Pin(manifest.data.sha256),
                    accept_new=args.accept_new_release,
                )
                book = dl.download(
                    manifest.codebook.url,
                    raw_dir / "codebook.pdf",
                    Pin(manifest.codebook.sha256),
                    accept_new=args.accept_new_release,
                )
        except (ReleaseChangedError, FetchError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if data.status != "cached":
            manifest.data.sha256, manifest.data.size = data.sha256, data.size
            manifest.data.last_modified = data.last_modified
            manifest.data.etag = data.etag
        if book.status != "cached":
            manifest.codebook.sha256, manifest.codebook.size = book.sha256, book.size
            manifest.codebook.last_modified = book.last_modified
        dump_manifest(manifest, args.manifest)
        print(
            f"fetch: {manifest.file_name} {data.status} ({data.size:,} bytes, "
            f"{data.requests} requests); codebook {book.status}"
        )
        if args.command == "fetch":
            return 0

    if args.command in ("build", "all"):
        if not zip_path.is_file():
            print(f"{zip_path} not found; run `make data-idb` first", file=sys.stderr)
            return 1
        t0 = time.monotonic()
        tsv = settings.data_dir / "build" / "idb-normalized.tsv"
        try:
            stats, cols = normalize_zip(zip_path, manifest.member, tsv)
            t1 = time.monotonic()
            result = build_idb(
                tsv,
                cols,
                db_path,
                settings.idb_parties_path,
                manifest,
                stats,
                fy_from=fy_from,
                fy_to=fy_to,
            )
        finally:
            tsv.unlink(missing_ok=True)
        elapsed = time.monotonic() - t0
        write_report(
            result,
            settings.data_dir / "build" / "idb-report.json",
            {
                "timing_seconds": {
                    "normalize": round(t1 - t0, 1),
                    "total": round(elapsed, 1),
                },
                "normalize": {
                    "rows": stats.rows,
                    "repaired_rows": len(stats.repaired_rows),
                    "control_bytes": stats.control_bytes,
                    "non_ascii_bytes": stats.non_ascii_bytes,
                },
            },
        )
        c = result.counts
        print(
            f"build: {result.release_rows:,} release records → "
            f"{c['idb_civil_record']:,} in FY{fy_from}–FY{fy_to} scope, "
            f"{c['idb_civil']:,} cases, {c['idb_civil_terminations']:,} "
            f"terminations → {db_path} in {elapsed:.0f}s"
        )
        print(f"record checksum: {result.checksum}")
        for w in result.warnings:
            print(f"  warning: {w}", file=sys.stderr)

    if args.command in ("profile", "build", "all"):
        write_profile(db_path, args.profile_doc)
        print(f"profile → {args.profile_doc}")

    if args.command == "sample":
        n = build_sample(
            zip_path,
            manifest.member,
            args.sample_out,
            settings.data_dir / "build",
            fy_from=fy_from,
            fy_to=fy_to,
        )
        print(f"sample: {n:,} records → {args.sample_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
