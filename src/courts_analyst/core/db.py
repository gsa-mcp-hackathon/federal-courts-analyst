"""Read-only access to the two analytical stores.

One in-memory DuckDB connection attaches the official tables catalog as
``cat`` and the civil IDB as ``idb``, both ``READ_ONLY``, so no code path in
the server can write to either. Queries take ``?`` parameters only; the SQL
text itself is always a constant or assembled from constant fragments
(``tests/test_sql_safety.py`` enforces this). Each call runs on its own
cursor, so concurrent requests don't share connection state.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import Any

import duckdb

from courts_analyst.core.errors import DataUnavailableError


def _attach_sql(path: Path, alias: str) -> str:
    literal = "'" + str(path).replace("'", "''") + "'"
    return "ATTACH " + literal + " AS " + alias + " (READ_ONLY)"


class Database:
    """The catalog (required) and the IDB (optional) behind one connection."""

    def __init__(self, tables_path: Path, idb_path: Path | None = None) -> None:
        self.tables_path = tables_path
        self.idb_path = idb_path
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None

    def _connect(self) -> duckdb.DuckDBPyConnection:
        if not self.tables_path.is_file():
            raise DataUnavailableError(
                "The official tables catalog hasn't been built. "
                "Run `make data-tables`.",
                ["server_info"],
            )
        con = duckdb.connect(":memory:")
        # ATTACH can't take a parameter. The paths come from server settings,
        # never from a request, and are quoted as SQL string literals.
        con.execute(_attach_sql(self.tables_path, "cat"))
        if self.idb_path is not None and self.idb_path.is_file():
            con.execute(_attach_sql(self.idb_path, "idb"))
        # Nothing after this point may read or write files by path.
        con.execute("SET enable_external_access = false")
        return con

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is None:
                self._con = self._connect()
            return self._con

    @cached_property
    def has_idb(self) -> bool:
        rows = (
            self.con.cursor()
            .execute(
                "SELECT count(*) FROM duckdb_databases() WHERE database_name = 'idb'"
            )
            .fetchone()
        )
        return bool(rows and rows[0])

    def require_idb(self) -> None:
        if not self.has_idb:
            raise DataUnavailableError(
                "The civil IDB hasn't been built, so case-level analysis is "
                "unavailable. Run `make data-idb`.",
                ["server_info", "get_official_figure"],
            )

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run a parameterized query and return every row."""
        return self.con.cursor().execute(sql, list(params)).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> tuple[Any, ...] | None:
        return self.con.cursor().execute(sql, list(params)).fetchone()

    def dicts(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self.con.cursor().execute(sql, list(params))
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None
