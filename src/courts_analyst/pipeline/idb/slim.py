"""A smaller copy of the built IDB holding only what the server reads.

watsonx Orchestrate runs the server as a *local* toolkit: the package,
data included, is uploaded to the platform, and an upload the size of the
full build (~440 MB) is refused (HTTP 413). The full build carries two
things the server never reads:

- ``idb_civil_raw``, the typed release records the decoded table is built
  from (kept for build checks and the data profile);
- columns of ``idb_civil_record`` that no tool queries (raw codes beside
  their decoded labels, arbitration and jury flags, and so on).

The slim copy keeps every other table, every row, and the views, so the
server gives identical answers from it (tests/test_idb_slim.py replays tool
calls against both). It is rebuilt from the full build, never edited.

Columns are *dropped* by name rather than kept by name, so a column added
to the build later ships by default: the failure mode is a bigger file,
never a wrong answer. tests/test_idb_slim.py fails if server code starts to
read a dropped column.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from courts_analyst.core.db import PII_INDEX_NAME

DROPPED_TABLES = ("idb_civil_raw",)

# Columns of idb_civil_record that no server code reads.
DROPPED_COLUMNS = (
    "record_id",
    "record_seq",
    "n_records",
    "is_repeat_record",
    "tape_year",
    "circuit_code",
    "district_code",
    "transfer_date",
    "county_code",
    "demanded_thousands",
    "amount_received_thousands",
    "codes_outside_validity",
    "origin_code",
    "jurisdiction_code",
    "disposition_code",
    "pro_se_code",
    "judgment_for_code",
    "nos_line",
    "procedural_stage",
    "procedural_progress",
    "procedural_progress_code",
    "nature_of_judgment",
    "nature_of_judgment_code",
    "arbitration_at_filing",
    "arbitration_at_filing_code",
    "arbitration_at_termination",
    "arbitration_at_termination_code",
    "class_action_alleged",
    "class_action_alleged_code",
    "class_action_ruling",
    "class_action_ruling_code",
    "fee_status",
    "fee_status_code",
    "is_ifp",
    "jury_demand",
    "jury_demand_code",
)

RECORD_TABLE = "idb_civil_record"


@dataclass(frozen=True)
class SlimResult:
    path: Path
    source_bytes: int
    bytes: int
    tables: dict[str, int]
    dropped_columns: tuple[str, ...]


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def build_slim(source: Path, out: Path) -> SlimResult:
    """Write the slim copy of ``source`` to ``out`` (replacing it), with the
    output scanner's party-name index beside it."""
    if source.resolve() == out.resolve():
        raise ValueError("the slim copy must not overwrite the full build")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(f"ATTACH {_lit(str(source))} AS src (READ_ONLY)")
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM duckdb_tables() "
                "WHERE database_name = 'src' ORDER BY table_name"
            ).fetchall()
            if r[0] not in DROPPED_TABLES
        ]
        present = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM duckdb_columns() "
                "WHERE database_name = 'src' AND table_name = ?",
                [RECORD_TABLE],
            ).fetchall()
        }
        dropped = tuple(c for c in DROPPED_COLUMNS if c in present)
        counts: dict[str, int] = {}
        for t in tables:
            cols = "*"
            if t == RECORD_TABLE and dropped:
                cols = "* EXCLUDE (" + ", ".join(_q(c) for c in dropped) + ")"
            con.execute(f"CREATE TABLE {_q(t)} AS SELECT {cols} FROM src.{_q(t)}")
            row = con.execute(f"SELECT count(*) FROM {_q(t)}").fetchone()
            counts[t] = int(row[0]) if row else 0
        views = con.execute(
            "SELECT sql FROM duckdb_views() "
            "WHERE database_name = 'src' AND NOT internal ORDER BY view_name"
        ).fetchall()
        con.execute("DETACH src")
        for (sql,) in views:
            con.execute(sql)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    tmp.replace(out)
    index = source.with_name(PII_INDEX_NAME)
    if index.is_file():
        shutil.copyfile(index, out.with_name(PII_INDEX_NAME))
    else:
        out.with_name(PII_INDEX_NAME).unlink(missing_ok=True)
    return SlimResult(
        path=out,
        source_bytes=source.stat().st_size,
        bytes=out.stat().st_size,
        tables=counts,
        dropped_columns=dropped,
    )


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
