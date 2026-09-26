"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastmcp import Client

from courts_analyst.app import mcp


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    """In-memory MCP client on the modern (2026-07-28) protocol."""
    async with Client(mcp) as c:
        yield c


@pytest.fixture
async def legacy_client() -> AsyncIterator[Client]:
    """In-memory MCP client pinned to the 2025-11-25 handshake era."""
    async with Client(mcp, mode="legacy") as c:
        yield c


# ── Official tables catalog (Phase 1) ────────────────────────────────────────
# The committed fixtures hold every file the catalog parses (all xlsx editions
# plus the PDF-only JB-2016 tables) and a few extra PDFs for the format
# cross-check, so CI builds the whole catalog offline.

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_RAW = ROOT / "tests" / "fixtures" / "tables"
MANIFEST_PATH = ROOT / "data" / "manifest" / "tables.yaml"


@dataclass(frozen=True)
class Catalog:
    db: Path
    result: Any
    revision_doc: Path


@pytest.fixture(scope="session")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Catalog:
    """The catalog built from committed fixtures (session-scoped: ~10 s)."""
    from courts_analyst.pipeline.tables.build import build
    from courts_analyst.pipeline.tables.manifest import load_manifest
    from courts_analyst.pipeline.tables.revision_log import write_revision_log

    out = tmp_path_factory.mktemp("catalog")
    db = out / "courts.duckdb"
    result = build(load_manifest(MANIFEST_PATH), FIXTURE_RAW, db, out / "parquet")
    doc = out / "revision-log.md"
    write_revision_log(db, doc)
    return Catalog(db=db, result=result, revision_doc=doc)


@pytest.fixture
def con(catalog: Catalog) -> Iterator[duckdb.DuckDBPyConnection]:
    c = duckdb.connect(str(catalog.db), read_only=True)
    try:
        yield c
    finally:
        c.close()
