"""Read-only access to the two analytical stores.

One in-memory DuckDB connection attaches the official tables catalog as
``cat`` and the civil IDB as ``idb``, both ``READ_ONLY``, so no code path in
the server can write to either. Queries take ``?`` parameters only; the SQL
text itself is always a constant or assembled from constant fragments
(``tests/test_sql_safety.py`` enforces this). Each call runs on its own
cursor, so concurrent requests don't share connection state.

Resource limits (Phase 6): every query is interrupted after
``query_timeout`` seconds, and a query returning more than ``max_rows`` rows
is refused, so one request can't tie up the server.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import Any

import duckdb

from courts_analyst.core.errors import (
    DataUnavailableError,
    OutputTooLargeError,
    QueryTimeoutError,
)

PII_INDEX_NAME = "pii_index.bin"
QUERY_TIMEOUT_SECONDS = 30.0
MAX_ROWS = 100_000


def _attach_sql(path: Path, alias: str) -> str:
    literal = "'" + str(path).replace("'", "''") + "'"
    return "ATTACH " + literal + " AS " + alias + " (READ_ONLY)"


class Database:
    """The catalog (required) and the IDB (optional) behind one connection."""

    def __init__(
        self,
        tables_path: Path,
        idb_path: Path | None = None,
        pii_index_path: Path | None = None,
        query_timeout: float = QUERY_TIMEOUT_SECONDS,
        max_rows: int = MAX_ROWS,
    ) -> None:
        self.query_timeout = query_timeout
        self.max_rows = max_rows
        self.tables_path = tables_path
        self.idb_path = idb_path
        # The hashed party-name index the output scanner reads (Phase 6);
        # the IDB pipeline writes it next to idb.duckdb.
        self.pii_index_path = pii_index_path or (
            idb_path.with_name(PII_INDEX_NAME) if idb_path is not None else None
        )
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
        # Spill to the system temp dir: the container's filesystem is
        # read-only except /tmp. Constant-derived path, quoted as a literal.
        tmp = "'" + tempfile.gettempdir().replace("'", "''") + "'"
        con.execute("SET temp_directory = " + tmp)
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

    def _fetch(
        self, sql: str, params: Sequence[Any], one: bool = False
    ) -> tuple[list[str], list[tuple[Any, ...]]]:
        cur = self.con.cursor()
        timer = threading.Timer(self.query_timeout, cur.interrupt)
        timer.daemon = True
        timer.start()
        try:
            cur.execute(sql, list(params))
            cols = [d[0] for d in cur.description or []]
            if one:
                row = cur.fetchone()
                return cols, [row] if row is not None else []
            rows = cur.fetchmany(self.max_rows + 1)
        except duckdb.InterruptException as exc:
            raise QueryTimeoutError(
                f"The query took longer than {self.query_timeout:g} s and was "
                "stopped. Narrow the request (fewer years, courts or groups).",
            ) from exc
        finally:
            timer.cancel()
        if len(rows) > self.max_rows:
            raise OutputTooLargeError(
                f"The query returned more than {self.max_rows:,} rows. Narrow the "
                "request."
            )
        return cols, rows

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run a parameterized query and return every row."""
        return self._fetch(sql, params)[1]

    def one(self, sql: str, params: Sequence[Any] = ()) -> tuple[Any, ...] | None:
        rows = self._fetch(sql, params, one=True)[1]
        return rows[0] if rows else None

    def dicts(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cols, rows = self._fetch(sql, params)
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None
