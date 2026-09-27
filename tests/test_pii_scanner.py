"""Output PII scanner: a result containing a known party name fails closed."""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest
from fastmcp import Client

from courts_analyst.core.cohorts import CohortSpec, CohortStore, find_cases
from courts_analyst.core.db import Database
from courts_analyst.core.glossary import TermLookup
from courts_analyst.core.guardrails import PolicyContext, apply_policies, pii
from courts_analyst.core.provenance import Provenance
from courts_analyst.core.results import ok
from tests.conftest import Catalog, IdbBuild


def _party(idb: IdbBuild) -> str:
    """A multi-word synthetic plaintiff name from the fixture's parties file."""
    con = duckdb.connect()
    name = con.execute(
        f"SELECT plaintiff FROM '{idb.parties}' WHERE plaintiff LIKE '% %' "
        "ORDER BY record_id LIMIT 1"
    ).fetchone()
    assert name
    return str(name[0])


def _result(text: str, source: str = "idb_derived"):  # type: ignore[no-untyped-def]
    return ok(
        TermLookup(query=text, found=False),
        [Provenance(source=source, definition="d")],  # type: ignore[arg-type]
    )


def test_pipeline_writes_the_index(idb: IdbBuild) -> None:
    index = pii.PiiIndex(idb.db.with_name("pii_index.bin"))
    assert len(index) > 100
    raw = idb.db.with_name("pii_index.bin").read_bytes()
    assert _party(idb).encode() not in raw  # hashes, never names


def test_known_party_name_fails_closed(core_db: Database, idb: IdbBuild) -> None:
    name = _party(idb)
    for text in (name, f"see {name.lower()}, et al.", f"x | {name} | y"):
        r = apply_policies(_result(text), PolicyContext("test", core_db))
        assert r.status == "declined" and r.data is None, text
        assert r.declined is not None and r.declined.reason == "pii"


def test_clean_result_passes(core_db: Database) -> None:
    r = apply_policies(
        _result("Northern District of Florida"), PolicyContext("t", core_db)
    )
    assert r.status == "ok"


def test_real_results_pass(core_db: Database, store: CohortStore) -> None:
    r = find_cases(core_db, store, CohortSpec(fy_from=2016, fy_to=2025))
    assert r.status == "ok"


def test_normalize_and_indexable() -> None:
    assert pii.normalize("3M Co., et al.") == ["3M", "CO"]
    assert pii.normalize("O'Brien-Smith") == ["OBRIEN", "SMITH"]
    assert not pii.indexable(["SMITH"])  # bare surnames aren't indexed
    assert not pii.indexable(["A", "B"])  # too few letters
    assert pii.indexable(["JANE", "ROE"])


def test_vocabulary_and_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "idx.bin"
    pii.build_index(["UNITED STATES", "LA ROSE", "JANE Q ROE"], path)
    scanner = pii.Scanner(pii.PiiIndex(path), boundaries=["W.D. La."])
    assert scanner.hits({"x": "Jane Q. Roe filed"}) == ["JANE Q ROE"]
    assert scanner.hits({"x": "the United States courts"}) == []  # our own vocabulary
    assert scanner.hits({"x": "Filings for W.D. La. rose by 41"}) == []  # boundary
    assert scanner.hits({"x": "La Rose v. Smith"}) == ["LA ROSE"]


def test_missing_index_fails_closed_for_idb_results(
    catalog: Catalog, idb: IdbBuild, tmp_path: Path
) -> None:
    db_path = tmp_path / "idb.duckdb"
    shutil.copy(idb.db, db_path)  # no pii_index.bin next to it
    db = Database(catalog.db, db_path)
    try:
        r = apply_policies(_result("anything"), PolicyContext("t", db))
        assert r.status == "declined" and "scanner" in r.declined.message  # type: ignore[union-attr]
        official = apply_policies(
            _result("x", "official_table"), PolicyContext("t", db)
        )
        assert official.status == "ok"
    finally:
        db.close()


def test_corrupt_index_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "pii_index.bin"
    bad.write_bytes(b"not an index")
    with pytest.raises(pii.PiiIndexError):
        pii.PiiIndex(bad)
    pii.build_index(["JANE ROE"], bad)
    bad.write_bytes(bad.read_bytes()[:-3])
    with pytest.raises(pii.PiiIndexError, match="truncated"):
        pii.PiiIndex(bad)


async def test_echoed_name_is_withheld_over_mcp(tools: Client, idb: IdbBuild) -> None:
    """explain_term echoes its input; a party name in it is withheld."""
    r = await tools.call_tool("explain_term", {"term": _party(idb)})
    data = r.structured_content
    assert data is not None and data["status"] == "declined"
    assert data["declined"]["reason"] == "pii" and data["data"] is None
