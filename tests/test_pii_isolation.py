"""Party names never reach idb.duckdb, and nothing the server reads can see them."""

from __future__ import annotations

import ast
from pathlib import Path

import duckdb
import pytest

from courts_analyst.config import Settings
from tests.conftest import IdbBuild

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "courts_analyst"

PARTY_WORDS = ("plt", "def", "plaintiff", "defendant", "party", "parties", "name")


def _columns(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    return con.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
    ).fetchall()


def test_no_party_columns_anywhere(idb_con: duckdb.DuckDBPyConnection) -> None:
    bad = [
        (t, c)
        for t, c in _columns(idb_con)
        if any(c.lower() == w or c.lower().startswith(w + "_") for w in PARTY_WORDS)
    ]
    assert not bad, bad
    tables = {t for t, _ in _columns(idb_con)}
    assert "idb_parties" not in tables
    with pytest.raises(duckdb.CatalogException):
        idb_con.execute("SELECT * FROM idb_parties")


def test_no_party_values_anywhere(
    idb: IdbBuild, idb_con: duckdb.DuckDBPyConnection
) -> None:
    """No text cell in any table equals a party name (the sample's are synthetic)."""
    names = {
        r[0]
        for r in idb_con.execute(
            f"SELECT plaintiff FROM '{idb.parties}' UNION SELECT defendant FROM '{idb.parties}'"
        ).fetchall()
    }
    assert names and all(n.startswith(("PLAINTIFF ", "DEFENDANT ")) for n in names)
    text_cols = [
        (t, c)
        for t, c, typ in idb_con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns"
        ).fetchall()
        if typ == "VARCHAR"
    ]
    for t, c in text_cols:
        hit = idb_con.execute(
            f'SELECT count(*) FROM "{t}" WHERE "{c}" LIKE \'PLAINTIFF %\' '
            f"OR \"{c}\" LIKE 'DEFENDANT %'"
        ).fetchone()
        assert hit == (0,), (t, c)


def test_parties_file_is_keyed_and_separate(
    idb: IdbBuild, idb_con: duckdb.DuckDBPyConnection
) -> None:
    assert idb.parties.is_file() and idb.parties.parent != idb.db.parent
    unmatched = idb_con.execute(
        f"""SELECT count(*) FROM '{idb.parties}' p
            ANTI JOIN idb_civil_record r USING (record_id)"""
    ).fetchone()
    assert unmatched == (0,)
    n = idb_con.execute(f"SELECT count(*) FROM '{idb.parties}'").fetchone()
    assert n == idb_con.execute("SELECT count(*) FROM idb_civil_record").fetchone()


def test_parties_path_is_outside_the_mounted_build_dir() -> None:
    s = Settings(data_dir=Path("/srv/data"))
    assert s.resolved_idb_path.parent == Path("/srv/data/build")
    assert Path("/srv/data/build") not in s.idb_parties_path.parents
    assert "data/private/" in (ROOT / ".dockerignore").read_text()
    assert "data/private/" in (ROOT / ".gitignore").read_text()


def test_server_code_never_mentions_parties() -> None:
    """Only the pipeline may name the parties file; core, tools, api can't."""
    offenders = []
    for sub in ("core", "tools", "resources", "prompts", "api", "agent"):
        for p in (PKG / sub).rglob("*.py"):
            tree = ast.parse(p.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if "idb_parties" in node.value:
                        offenders.append(str(p.relative_to(ROOT)))
                elif (
                    isinstance(node, ast.Attribute) and node.attr == "idb_parties_path"
                ):
                    offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, offenders
