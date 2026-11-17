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

That alone (~120 MiB, ~61 MiB zipped) was still refused, so the record table
is also stored *compactly*: ``idb_civil_record`` becomes a view with the same
columns over a narrower base table (``idb_civil_base``). ``case_key`` and
``days_to_disposition`` are computed again in the view, and labels that
depend on one code (``nos_group`` on ``nos_code`` and so on) move to small
lookup tables (``idb_lookup_*``). The fiscal years stay stored: tools filter
on them, and a stored column lets DuckDB skip row groups (computed, the
slowest recorded call took 0.7 s instead of 0.37 s). Each
dependency is checked in the data first; one that doesn't hold stays stored.
The build then compares the view with the table it replaces, row for row,
and refuses to write a copy that differs.

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
BASE_TABLE = "idb_civil_base"

# Labels that depend on a single kept column: key → dependent columns.
LOOKUPS: dict[str, tuple[str, ...]] = {
    "nos_code": ("nos", "nos_group", "nos_category"),
    "origin": ("origin_group", "is_mdl_direct_filed", "is_mdl_transferred"),
    "disposition": ("disposition_group",),
    "pro_se": ("pro_se_group",),
    "jurisdiction": ("jurisdiction_group",),
    "status_code": ("status",),
    "court": ("circuit",),
}

# Columns the view computes again, as built by load.py. ``district_code`` is a
# lookup on ``court`` taken from the full build.
DERIVED: dict[str, str] = {
    "case_key": "district_code || '-' || office || '-' || docket || '-' "
    "|| strftime(filing_date, '%Y%m%d')",
    "days_to_disposition": "CASE WHEN termination_date IS NOT NULL "
    "THEN termination_date - filing_date END",
}


@dataclass(frozen=True)
class SlimResult:
    path: Path
    source_bytes: int
    bytes: int
    tables: dict[str, int]
    dropped_columns: tuple[str, ...]
    computed_columns: tuple[str, ...] = ()


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
        computed = _compact(con) if RECORD_TABLE in counts else ()
        con.execute("DETACH src")
        for (sql,) in views:
            con.execute(sql)
        # DuckDB keeps the space of dropped tables in the file: copy what's
        # left into a fresh one.
        fresh = out.with_name(out.stem + ".fresh.duckdb")
        fresh.unlink(missing_ok=True)
        con.execute(f"ATTACH {_lit(str(fresh))} AS fresh")
        here = _one_str(con, "SELECT current_database()")
        con.execute(f"COPY FROM DATABASE {_q(here)} TO fresh")
        con.execute("DETACH fresh")
    finally:
        con.close()
    tmp.unlink()
    fresh.replace(out)
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
        computed_columns=computed,
    )


def _one(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0]) if row else 0


def _depends(
    con: duckdb.DuckDBPyConnection, table: str, key: str, cols: list[str]
) -> bool:
    """Each value of ``key`` (NULL included) comes with one set of ``cols``."""
    pick = ", ".join(_q(c) for c in [key, *cols])
    with_cols = _one(con, f"SELECT count(*) FROM (SELECT DISTINCT {pick} FROM {table})")
    keys = _one(con, f"SELECT count(*) FROM (SELECT DISTINCT {_q(key)} FROM {table})")
    return with_cols == keys


def _compact(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """Replace the record table with a view of the same columns over a narrower
    base table and lookups (module docstring); the columns no longer stored."""

    def columns(database: str) -> list[str]:
        return [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM duckdb_columns() WHERE database_name = ? "
                "AND table_name = ? ORDER BY column_index",
                [database, RECORD_TABLE],
            ).fetchall()
        ]

    rec = _q(RECORD_TABLE)
    order = columns(_one_str(con, "SELECT current_database()"))
    present, in_full = set(order), set(columns("src"))
    derived = {c: e for c, e in DERIVED.items() if c in present}

    # key → (columns the lookup supplies, table it's read from)
    plan: dict[str, tuple[list[str], str]] = {}
    for key, deps in LOOKUPS.items():
        if key not in present:
            continue
        cols, source = [c for c in deps if c in present], rec
        if key == "court" and "case_key" in derived and "district_code" in in_full:
            cols, source = [*cols, "district_code"], f"src.{rec}"
        if cols and _depends(con, source, key, cols):
            plan[key] = (cols, source)
    if "district_code" not in plan.get("court", ([], ""))[0]:
        derived.pop("case_key", None)

    looked_up = {c for cols, _ in plan.values() for c in cols}
    stored = [c for c in order if c not in derived and c not in looked_up]
    con.execute(
        f"CREATE TABLE {BASE_TABLE} AS SELECT "
        + ", ".join(_q(c) for c in stored)
        + f" FROM {rec}"
    )
    pulled, joins = [], []
    for key, (cols, source) in plan.items():
        name, alias = f"idb_lookup_{key}", f"l_{key}"
        pick = ", ".join(_q(c) for c in [key, *cols])
        con.execute(f"CREATE TABLE {name} AS SELECT DISTINCT {pick} FROM {source}")
        joins.append(
            f"LEFT JOIN {name} {alias} "
            f"ON b.{_q(key)} IS NOT DISTINCT FROM {alias}.{_q(key)}"
        )
        pulled += [f"{alias}.{_q(c)}" for c in cols]
    inner = (
        "SELECT "
        + ", ".join(["b.*", *pulled])
        + f" FROM {BASE_TABLE} b "
        + " ".join(joins)
    )
    view = (
        "SELECT "
        + ", ".join(f"{derived.get(c, _q(c))} AS {_q(c)}" for c in order)
        + f" FROM ({inner}) r"
    )
    # The view must give back exactly the table it replaces.
    for a, b in ((rec, f"({view})"), (f"({view})", rec)):
        extra = _one(con, f"SELECT count(*) FROM (FROM {a} EXCEPT ALL FROM {b})")
        if extra:
            raise RuntimeError(
                f"compact view differs from {RECORD_TABLE}: {extra} rows"
            )
    con.execute(f"DROP TABLE {rec}")
    con.execute(f"CREATE VIEW {rec} AS {view}")
    return tuple(c for c in order if c not in stored)


def _one_str(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    row = con.execute(sql).fetchone()
    return str(row[0]) if row else ""


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
