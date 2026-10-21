"""ADR 0013: the official data stays read-only; only the desk store writes.

The catalog and IDB are attached READ_ONLY (ADR 0008, tests/test_sql_safety.py
checks the connection itself). Here: no core module other than the desk
store opens a SQLite connection, no new DuckDB connection appears in the
core, and the desk store can't be pointed at the read-only build folder by
accident.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from courts_analyst.core.db import Database

CORE = Path(__file__).resolve().parents[1] / "src" / "courts_analyst" / "core"

# Writable DuckDB files the core already knew before the desk: the cohort
# handle store (ADR 0008 consequences). db.py opens the in-memory reader.
DUCKDB_OPENERS = {"db.py", "cohorts.py"}


def _calls(pattern: str) -> set[str]:
    rx = re.compile(pattern)
    return {
        str(p.relative_to(CORE))
        for p in CORE.rglob("*.py")
        if rx.search(p.read_text())
    }


def test_only_the_desk_store_opens_sqlite() -> None:
    assert _calls(r"sqlite3\.connect\(") == {"desk/store.py"}


def test_no_new_duckdb_connections_in_the_core() -> None:
    assert _calls(r"duckdb\.connect\(") == DUCKDB_OPENERS


def test_desk_never_touches_the_catalog_connection_for_writes() -> None:
    desk = "\n".join(p.read_text() for p in (CORE / "desk").glob("*.py"))
    # The desk reads the catalog through db.rows/db.one (load_chain,
    # revisions) only; every write statement goes through the desk store.
    assert not re.search(r"db\.(execute|con|_con)\b", desk)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM cat.revision_log",
        "UPDATE cat.observation SET value = 0",
        "CREATE TABLE cat.desk_request (id INTEGER)",
    ],
)
def test_catalog_still_refuses_writes(core_db: Database, sql: str) -> None:
    with pytest.raises(Exception, match="(?i)read.only|read-only"):
        core_db.rows(sql)


def test_desk_store_is_separate_from_the_build(tmp_path: Path, core_db: Any) -> None:
    from courts_analyst.core.desk.store import DeskStore

    store = DeskStore(tmp_path / "sandbox" / "desk.sqlite")
    try:
        assert store.path is not None and store.path.exists()
        assert store.path != core_db.tables_path
        assert store.one("PRAGMA journal_mode")[0] == "wal"
    finally:
        store.close()
