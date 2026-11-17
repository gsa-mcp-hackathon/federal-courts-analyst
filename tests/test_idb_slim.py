"""The slim IDB copy shipped to watsonx Orchestrate (pipeline/idb/slim.py):
same rows, same answers, and no server code reads what it leaves out."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastmcp import Client

from courts_analyst.app import mcp
from courts_analyst.core.db import PII_INDEX_NAME
from courts_analyst.pipeline.idb.slim import (
    DROPPED_COLUMNS,
    DROPPED_TABLES,
    RECORD_TABLE,
    build_slim,
)

from .conftest import IdbBuild

SRC = Path(__file__).resolve().parents[1] / "src" / "courts_analyst"


@pytest.fixture(scope="module")
def slim(idb: IdbBuild, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("slim") / "idb.duckdb"
    build_slim(idb.db, out)
    return out


def _tables(path: Path) -> dict[str, int]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        names = [
            r[0]
            for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
        ]
        names += [
            r[0]
            for r in con.execute(
                "SELECT view_name FROM duckdb_views() WHERE NOT internal"
            ).fetchall()
        ]
        out = {}
        for n in names:
            row = con.execute(f'SELECT count(*) FROM "{n}"').fetchone()
            out[n] = row[0] if row else 0
        return out
    finally:
        con.close()


def test_same_rows_without_the_unread_parts(idb: IdbBuild, slim: Path) -> None:
    full, small = _tables(idb.db), _tables(slim)
    assert set(small) == set(full) - set(DROPPED_TABLES)
    assert all(small[t] == full[t] for t in small)
    con = duckdb.connect(str(slim), read_only=True)
    try:
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM duckdb_columns() WHERE table_name = ?",
                [RECORD_TABLE],
            ).fetchall()
        }
    finally:
        con.close()
    assert cols and not cols & set(DROPPED_COLUMNS)
    assert (slim.parent / PII_INDEX_NAME).read_bytes() == (
        idb.db.parent / PII_INDEX_NAME
    ).read_bytes()


def test_refuses_to_overwrite_the_full_build(idb: IdbBuild) -> None:
    with pytest.raises(ValueError):
        build_slim(idb.db, idb.db)


def test_no_server_code_reads_a_dropped_column() -> None:
    """If a tool starts using one of these, take it off DROPPED_COLUMNS."""
    hits = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(("pipeline/", "evaluation/")):
            continue
        text = path.read_text()
        hits += [f"{rel}: {c}" for c in DROPPED_COLUMNS if re.search(rf"\b{c}\b", text)]
    assert not hits


CALLS: list[tuple[str, dict[str, Any]]] = [
    ("find_cases", {"courts": ["FL-N"], "fy_from": 2020, "fy_to": 2020}),
    ("find_cases", {"fy_from": 2019, "fy_to": 2021, "origins": ["mdl_direct"]}),
    ("find_cases", {"courts": ["CIR-05"], "fy_from": 2018, "fy_to": 2022}),
    (
        "reconcile",
        {"measure": "civil_cases_pending", "court": "US", "fiscal_year": 2017},
    ),
    ("reconcile", {"measure": "civil_cases_filed", "court": "US", "fiscal_year": 2018}),
    (
        "reconcile",
        {"measure": "civil_cases_terminated", "court": "US", "fiscal_year": 2016},
    ),
    (
        "explain_change",
        {
            "court": "FL-N",
            "measure": "civil_cases_filed",
            "period_from": 2019,
            "period_to": 2020,
        },
    ),
    ("server_info", {}),
]
METRICS = (
    "count",
    "trend",
    "median_days_to_disposition",
    "disposition_rates",
    "judgment_for_rates",
    "share_by_nos_group",
    "pro_se_share",
    "still_pending_share",
)


async def _answers(path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "idb_duckdb_path", path)
    out: list[Any] = []
    async with Client(mcp) as c:
        for name, args in CALLS:
            r = await c.call_tool(name, args, raise_on_error=False)
            body = r.structured_content
            if name == "server_info" and isinstance(body, dict):
                body = {k: v for k, v in body.items() if k != "data"} | {
                    "datasets": body.get("data", {}).get("datasets")
                }
            out.append(body)
            handle = (body or {}).get("data", {}).get("handle")
            if name == "find_cases" and handle:
                for metric in METRICS:
                    a = await c.call_tool(
                        "analyze_cohort",
                        {"handle": handle, "metric": metric},
                        raise_on_error=False,
                    )
                    out.append(a.structured_content)
                s = await c.call_tool(
                    "sample_dockets", {"handle": handle, "n": 5}, raise_on_error=False
                )
                out.append(s.structured_content)
                rec = await c.call_tool(
                    "reconcile", {"handle": handle}, raise_on_error=False
                )
                out.append(rec.structured_content)
    return out


async def test_identical_answers(
    server_data: None, idb: IdbBuild, slim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = await _answers(idb.db, monkeypatch)
    small = await _answers(slim, monkeypatch)
    assert len(full) == len(CALLS) + 3 * (len(METRICS) + 2)
    # The calls really ran against data. Not "ok": server_info (no status
    # field) and reconcile on the two multi-court cohorts (it needs one court).
    ok = [a for a in full if isinstance(a, dict) and a.get("status") == "ok"]
    assert len(ok) == len(full) - 3
    assert small == full
