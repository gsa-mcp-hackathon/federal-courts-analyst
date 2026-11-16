"""Fetch every manifest file, parse, cross-check formats, load, and report."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from courts_analyst.core.numbers import round_half_up
from courts_analyst.pipeline.tables.families import FAMILIES, ParseResult, parse
from courts_analyst.pipeline.tables.fetch import Fetcher, FetchError
from courts_analyst.pipeline.tables.load import build_database, content_checksum
from courts_analyst.pipeline.tables.manifest import Manifest, TableEntry
from courts_analyst.pipeline.tables.records import Footnote, Observation, SourceFile

log = logging.getLogger("courts_analyst.pipeline.tables")

WAYBACK = "https://web.archive.org/web/2026id_/{url}"
"""Fallback mirror. ``id_`` returns the archived bytes unmodified, and the sha256
pin (when present) proves they match what uscourts.gov published."""


@dataclass
class FetchReport:
    downloaded: int = 0
    cached: int = 0
    from_mirror: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def fetch_all(
    manifest: Manifest,
    raw_dir: Path,
    fetcher: Fetcher,
    *,
    mirror: bool = True,
    mirror_fetcher: Fetcher | None = None,
) -> FetchReport:
    """Download every file in the manifest; pin sha256 on first download."""
    report = FetchReport()
    for t in manifest.tables:
        for fmt, f in t.files.items():
            dest = t.raw_path(raw_dir, fmt)
            try:
                res = fetcher.fetch(f.url, dest, f.sha256)
            except FetchError as exc:
                if not mirror:
                    report.failed.append(f"{f.url}: {exc}")
                    continue
                log.warning("origin failed for %s (%s); trying Wayback", f.url, exc)
                try:
                    res = (mirror_fetcher or fetcher).fetch(
                        WAYBACK.format(url=f.url), dest, f.sha256
                    )
                except FetchError as exc2:
                    report.failed.append(f"{f.url}: {exc2}")
                    continue
                report.from_mirror.append(f.url)
            if res.status == "cached":
                report.cached += 1
            else:
                report.downloaded += 1
            f.sha256 = res.sha256
    return report


def source_file(t: TableEntry, fmt: str) -> SourceFile:
    f = t.files[fmt]
    return SourceFile(
        file_id=t.file_id(fmt),
        url=f.url,
        landing_url=t.landing_url,
        sha256=f.sha256 or "",
        series=t.series,
        table_code=t.table_code,
        edition=t.edition,
        period_end=t.period_end,
        format=fmt,
        title=t.title,
    )


def compare_formats(
    t: TableEntry, xlsx: ParseResult, pdf: ParseResult
) -> list[dict[str, Any]]:
    """Every value the PDF prints must equal the workbook value at PDF precision."""
    pdf_by_key = {(o.measure_id, o.court, o.fiscal_year): o for o in pdf.observations}
    rows = []
    for o in xlsx.observations:
        p = pdf_by_key.get((o.measure_id, o.court, o.fiscal_year))
        if p is None:
            continue
        dec = p.decimals if p.decimals is not None else 0
        agrees = (o.value is None and p.value is None) or (
            o.value is not None
            and p.value is not None
            and round_half_up(o.value, dec) == p.value
        )
        rows.append(
            {
                "edition": t.edition,
                "table_code": t.table_code,
                "measure_id": o.measure_id,
                "court": o.court,
                "fiscal_year": o.fiscal_year,
                "xlsx_value": o.value,
                "pdf_value": p.value,
                "pdf_raw": p.raw,
                "agrees": agrees,
            }
        )
    return rows


@dataclass
class BuildResult:
    counts: dict[str, int]
    checksum: str
    warnings: list[str]
    errors: list[str]
    format_mismatches: int
    format_compared: int
    per_family: dict[str, dict[str, Any]]


def build(
    manifest: Manifest,
    raw_dir: Path,
    db_path: Path,
    parquet_dir: Path | None = None,
    *,
    cross_check: bool = True,
    strict: bool = True,
) -> BuildResult:
    """Parse every table in the manifest from the raw cache and write DuckDB."""
    sources: list[SourceFile] = []
    observations: list[Observation] = []
    footnotes: list[Footnote] = []
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    per_family: dict[str, dict[str, Any]] = {}

    for t in manifest.tables:
        family = FAMILIES[t.family]
        fam = per_family.setdefault(
            t.family,
            {"editions": [], "observations": 0, "formats": {"xlsx": 0, "pdf": 0}},
        )
        results: dict[str, ParseResult] = {}
        for fmt in sorted(t.files, key=lambda f: f != t.primary_format):
            path = t.raw_path(raw_dir, fmt)
            src = source_file(t, fmt)
            sources.append(src)
            if fmt != t.primary_format and (not cross_check or not path.is_file()):
                continue  # the cross-check copy is optional (CI fixtures omit most)
            if not path.is_file():
                errors.append(f"{src.file_id}: raw file missing ({path})")
                continue
            try:
                results[fmt] = parse(family, src, path)
            except Exception as exc:  # parser errors are reported, not hidden
                msg = f"{src.file_id}: {type(exc).__name__}: {exc}"
                if fmt == t.primary_format:
                    errors.append(msg)
                else:
                    warnings.append(f"cross-check skipped, {msg}")
                continue
            warnings.extend(results[fmt].warnings)
        primary = results.get(t.primary_format)
        if primary is None:
            continue
        observations.extend(primary.observations)
        footnotes.extend(primary.footnotes)
        fam["editions"].append(t.edition)
        fam["observations"] += len(primary.observations)
        fam["formats"][t.primary_format] += 1
        if "xlsx" in results and "pdf" in results:
            checks.extend(compare_formats(t, results["xlsx"], results["pdf"]))

    if strict and errors:
        raise RuntimeError("build failed:\n  " + "\n  ".join(errors))
    counts = build_database(
        db_path, sources, observations, footnotes, checks, parquet_dir
    )
    mismatches = sum(1 for c in checks if not c["agrees"])
    return BuildResult(
        counts=counts,
        checksum=content_checksum(observations),
        warnings=warnings,
        errors=errors,
        format_mismatches=mismatches,
        format_compared=len(checks),
        per_family=per_family,
    )


def write_report(
    result: BuildResult, path: Path, fetch: FetchReport | None = None
) -> None:
    """Machine-readable build report (counts, checksum) for reproducibility checks."""
    data: dict[str, Any] = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": result.counts,
        "observation_checksum": result.checksum,
        "format_check": {
            "compared": result.format_compared,
            "mismatches": result.format_mismatches,
        },
        "families": result.per_family,
        "warnings": result.warnings,
    }
    if fetch is not None:
        data["fetch"] = {
            "downloaded": fetch.downloaded,
            "cached": fetch.cached,
            "from_mirror": fetch.from_mirror,
            "failed": fetch.failed,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
