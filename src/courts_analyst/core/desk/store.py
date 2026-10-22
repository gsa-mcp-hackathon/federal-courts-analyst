"""The desk store: a small SQLite database, separate from the official data.

The catalog and the IDB stay attached ``READ_ONLY`` (ADR 0008); this is the
only writable store the core opens (ADR 0013). SQLite because desk records
are row-level, transactional writes and it ships with Python. With no path
the store lives in memory, so tests and a fresh demo start empty.

Every write runs in one transaction and appends an ``audit_event``; triggers
make that table append-only. SQL text is constant; values go in as ``?``
parameters (``tests/test_sql_safety.py``).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    staff INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS request (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    option TEXT NOT NULL,
    account_id TEXT NOT NULL,
    asker_name TEXT NOT NULL,
    asker_role TEXT NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL,
    needs_reverification INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS answer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES request(id),
    version INTEGER NOT NULL,
    text TEXT NOT NULL,
    edition_basis TEXT NOT NULL,
    computed_sources TEXT NOT NULL DEFAULT '',
    verified_at TEXT NOT NULL,
    UNIQUE (request_id, version)
);
CREATE TABLE IF NOT EXISTS citation (
    answer_id INTEGER NOT NULL REFERENCES answer(id),
    position INTEGER NOT NULL,
    record TEXT NOT NULL,
    measure TEXT NOT NULL,
    court TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    edition TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (answer_id, position)
);
CREATE TABLE IF NOT EXISTS inquiry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    measure TEXT NOT NULL,
    court TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    from_edition TEXT NOT NULL,
    from_value REAL NOT NULL,
    to_edition TEXT NOT NULL,
    to_value REAL NOT NULL,
    route TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (measure, court, fiscal_year, from_edition, to_edition)
);
CREATE TABLE IF NOT EXISTS inquiry_request (
    inquiry_id INTEGER NOT NULL REFERENCES inquiry(id),
    request_id INTEGER NOT NULL REFERENCES request(id),
    PRIMARY KEY (inquiry_id, request_id)
);
CREATE TABLE IF NOT EXISTS response (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inquiry_id INTEGER NOT NULL UNIQUE REFERENCES inquiry(id),
    outcome TEXT NOT NULL,
    text TEXT NOT NULL,
    entered_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL UNIQUE REFERENCES request(id),
    answer_id INTEGER NOT NULL REFERENCES answer(id),
    published_by TEXT NOT NULL,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_update (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES request(id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    dedup TEXT,
    created_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    UNIQUE (request_id, dedup)
);
CREATE TABLE IF NOT EXISTS idempotency (
    account_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    PRIMARY KEY (account_id, tool, key)
);
CREATE TABLE IF NOT EXISTS audit_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    tool TEXT NOT NULL,
    record TEXT NOT NULL,
    before TEXT,
    after TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_event
BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_event
BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;
"""

FIRST_REQUEST_ID = 1001
"""Request numbers start here so they read like ticket numbers."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DeskStore:
    """One SQLite connection behind a lock (the desk is low-volume)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(
            str(path) if path is not None else ":memory:",
            check_same_thread=False,
            isolation_level=None,
        )
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        if path is not None:
            self._con.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            self._con.executescript(SCHEMA)
            self._con.execute(
                "INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)",
                [str(SCHEMA_VERSION)],
            )
            seq = self._con.execute(
                "SELECT count(*) FROM sqlite_sequence WHERE name = 'request'"
            ).fetchone()[0]
            if not seq:
                self._con.execute(
                    "INSERT INTO sqlite_sequence (name, seq) VALUES ('request', ?)",
                    [FIRST_REQUEST_ID - 1],
                )

    # ── access ────────────────────────────────────────────────────────────────

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One atomic unit of work; rolled back on any error."""
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                yield self._con
            except BaseException:
                self._con.execute("ROLLBACK")
                raise
            self._con.execute("COMMIT")

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._con.execute(sql, list(params)).fetchall())

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._con.execute(sql, list(params)).fetchone()
            return row

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # ── helpers used inside a transaction ─────────────────────────────────────

    @staticmethod
    def audit(
        con: sqlite3.Connection,
        actor: str,
        tool: str,
        record: str,
        before: str | None,
        after: str | None,
    ) -> None:
        con.execute(
            "INSERT INTO audit_event (at, actor, tool, record, before, after) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [now(), actor, tool, record, before, after],
        )

    @staticmethod
    def add_update(
        con: sqlite3.Connection,
        request_id: int,
        kind: str,
        text: str,
        dedup: str | None = None,
    ) -> bool:
        """Add an inbox entry; with ``dedup``, at most one per request. Returns
        whether a row was added."""
        cur = con.execute(
            "INSERT OR IGNORE INTO request_update "
            "(request_id, kind, text, dedup, created_at) VALUES (?, ?, ?, ?, ?)",
            [request_id, kind, text, dedup, now()],
        )
        return cur.rowcount > 0

    @staticmethod
    def set_status(con: sqlite3.Connection, request_id: int, status: str) -> None:
        con.execute(
            "UPDATE request SET status = ?, updated_at = ? WHERE id = ?",
            [status, now(), request_id],
        )

    # ── idempotency ───────────────────────────────────────────────────────────

    def remembered(self, account_id: str, tool: str, key: str | None) -> str | None:
        if not key:
            return None
        row = self.one(
            "SELECT outcome FROM idempotency WHERE account_id = ? AND tool = ? "
            "AND key = ?",
            [account_id, tool, key],
        )
        return str(row[0]) if row else None

    @staticmethod
    def remember(
        con: sqlite3.Connection,
        account_id: str,
        tool: str,
        key: str | None,
        outcome: str,
    ) -> None:
        if key:
            con.execute(
                "INSERT OR IGNORE INTO idempotency VALUES (?, ?, ?, ?)",
                [account_id, tool, key, outcome],
            )

    # ── accounts ──────────────────────────────────────────────────────────────

    def ensure_account(
        self, account_id: str, name: str, role: str, staff: bool
    ) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO account VALUES (?, ?, ?, ?) ON CONFLICT (id) DO UPDATE "
                "SET name = excluded.name, role = excluded.role, "
                "staff = excluded.staff",
                [account_id, name, role, int(staff)],
            )

    def reset(self) -> None:
        """Empty every table (``make desk-reset``). The audit log is dropped
        and recreated: a reset is the one way to clear it."""
        with self._lock:
            self._con.executescript(
                "DROP TABLE IF EXISTS audit_event; DROP TABLE IF EXISTS idempotency;"
                "DROP TABLE IF EXISTS request_update;"
                "DROP TABLE IF EXISTS library_entry;"
                "DROP TABLE IF EXISTS response; DROP TABLE IF EXISTS inquiry_request;"
                "DROP TABLE IF EXISTS inquiry; DROP TABLE IF EXISTS citation;"
                "DROP TABLE IF EXISTS answer; DROP TABLE IF EXISTS request;"
                "DROP TABLE IF EXISTS account; DROP TABLE IF EXISTS meta;"
                "DELETE FROM sqlite_sequence;"
            )
            self._con.executescript(SCHEMA)
            self._con.execute(
                "INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)",
                [str(SCHEMA_VERSION)],
            )
            self._con.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('request', ?)",
                [FIRST_REQUEST_ID - 1],
            )
