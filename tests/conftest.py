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


# ── Civil IDB (Phase 2) ──────────────────────────────────────────────────────
# tests/fixtures/idb/cv_sample.zip is a stratified sample of the real release
# in the FJC's own format (party names synthetic), built by
# `python -m courts_analyst.pipeline.idb sample`.

IDB_SAMPLE_ZIP = ROOT / "tests" / "fixtures" / "idb" / "cv_sample.zip"
IDB_MANIFEST_PATH = ROOT / "data" / "manifest" / "idb.yaml"


@dataclass(frozen=True)
class IdbBuild:
    db: Path
    parties: Path
    result: Any
    stats: Any


def build_idb_from_zip(zip_path: Path, out: Path) -> IdbBuild:
    """Normalize and load an IDB-format zip into ``out`` (used by tests)."""
    from courts_analyst.pipeline.idb.load import build_idb
    from courts_analyst.pipeline.idb.manifest import load_manifest
    from courts_analyst.pipeline.idb.normalize import normalize_zip

    manifest = load_manifest(IDB_MANIFEST_PATH)
    tsv = out / "normalized.tsv"
    stats, cols = normalize_zip(zip_path, manifest.member, tsv)
    db, parties = out / "idb.duckdb", out / "private" / "idb_parties.parquet"
    result = build_idb(tsv, cols, db, parties, manifest, stats)
    tsv.unlink()
    return IdbBuild(db=db, parties=parties, result=result, stats=stats)


@pytest.fixture(scope="session")
def idb(tmp_path_factory: pytest.TempPathFactory) -> IdbBuild:
    """The IDB built from the committed sample (session-scoped: ~2 s)."""
    return build_idb_from_zip(IDB_SAMPLE_ZIP, tmp_path_factory.mktemp("idb"))


@pytest.fixture
def idb_con(idb: IdbBuild) -> Iterator[duckdb.DuckDBPyConnection]:
    c = duckdb.connect(str(idb.db), read_only=True)
    try:
        yield c
    finally:
        c.close()


# ── Analytics core (Phase 4) ─────────────────────────────────────────────────
# The core reads both fixture builds through one read-only connection, the
# way the server does.


@pytest.fixture(scope="session")
def core_db(catalog: Catalog, idb: IdbBuild) -> Iterator[Any]:
    from courts_analyst.core.db import Database

    db = Database(catalog.db, idb.db)
    yield db
    db.close()


@pytest.fixture(scope="session")
def tables_only_db(catalog: Catalog) -> Iterator[Any]:
    """The catalog without the IDB (as when only `make data-tables` has run)."""
    from courts_analyst.core.db import Database

    db = Database(catalog.db, None)
    yield db
    db.close()


@pytest.fixture
def store() -> Any:
    from courts_analyst.core.cohorts import CohortStore

    return CohortStore()


FULL_TABLES = ROOT / "data" / "build" / "courts.duckdb"
FULL_IDB = ROOT / "data" / "build" / "idb.duckdb"


@pytest.fixture(scope="session")
def full_db() -> Iterator[Any]:
    """The full local builds (`make data`), for @fulldata tests."""
    from courts_analyst.core.db import Database

    if not (FULL_TABLES.is_file() and FULL_IDB.is_file()):
        pytest.skip("full datasets not built (make data)")
    db = Database(FULL_TABLES, FULL_IDB)
    yield db
    db.close()
