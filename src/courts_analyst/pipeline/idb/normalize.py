"""Stream the IDB zip into a clean UTF-8, tab-delimited file DuckDB can read.

The delivered text needs three repairs, each counted in :class:`NormalizeStats`
and reported by the build:

- **Encoding.** The file isn't valid UTF-8 (a few Latin-1 bytes in party
  names), so bytes are decoded as Latin-1, which maps every byte.
- **Control bytes.** A handful of NUL and other control bytes (never tab, CR
  or LF) sit inside party names; they become spaces.
- **Quoted tabs.** Some rows quote a party name that contains a tab, which
  shifts every later column. Rows with the wrong number of tabs are re-split
  honouring double quotes; a row that still doesn't have the right number of
  fields fails the build with its line number.

Nothing is dropped: the output has exactly one line per input record.
"""

from __future__ import annotations

import csv
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from courts_analyst.pipeline.idb.schema import Column, match_schema

_KEEP = {9, 10, 13}  # tab, LF, CR
_CONTROL = bytes(range(256)).maketrans(
    bytes(b for b in [*range(32), 127] if b not in _KEEP),
    b" " * (33 - len(_KEEP)),
)


class MalformedRowError(ValueError):
    """A row can't be split into the schema's columns."""


@dataclass
class NormalizeStats:
    schema: str = ""
    columns: int = 0
    rows: int = 0
    control_bytes: int = 0
    non_ascii_bytes: int = 0
    repaired_rows: list[int] = field(default_factory=list)
    """1-based line numbers (header = line 1) re-split on quotes."""


def normalize_zip(
    zip_path: Path, member: str, out_path: Path
) -> tuple[NormalizeStats, tuple[Column, ...]]:
    """Write ``member`` of ``zip_path`` to ``out_path`` as clean UTF-8 TSV."""
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as src:
        return normalize_stream(src, out_path)


def normalize_stream(
    src: Iterable[bytes], out_path: Path
) -> tuple[NormalizeStats, tuple[Column, ...]]:
    """Normalize a binary line iterator (an open file or zip member)."""
    stats = NormalizeStats()
    lines = iter(src)
    header = _clean(next(lines), stats).rstrip("\r\n").split("\t")
    stats.schema, cols = match_schema(header)
    stats.columns = n = len(cols)
    tabs = n - 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("\t".join(header) + "\n")
        for lineno, raw in enumerate(lines, start=2):
            text = _clean(raw, stats).rstrip("\r\n")
            if text.count("\t") != tabs:
                fields = next(csv.reader([text], delimiter="\t", quotechar='"'))
                if len(fields) != n:
                    raise MalformedRowError(
                        f"line {lineno}: {len(fields)} fields after quote repair, "
                        f"expected {n}: {text[:120]!r}"
                    )
                text = "\t".join(f.replace("\t", " ") for f in fields)
                stats.repaired_rows.append(lineno)
            out.write(text + "\n")
            stats.rows += 1
    return stats, cols


def _clean(raw: bytes, stats: NormalizeStats) -> str:
    if not raw.isascii():
        stats.non_ascii_bytes += sum(1 for b in raw if b > 127)
    cleaned = raw.translate(_CONTROL)
    if cleaned != raw:
        stats.control_bytes += sum(
            1 for a, b in zip(raw, cleaned, strict=True) if a != b
        )
    return cleaned.decode("latin-1")
