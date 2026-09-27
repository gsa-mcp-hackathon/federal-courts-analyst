"""No string-formatted SQL in core/, and the connection can't write."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from courts_analyst.core.db import Database

CORE = Path(__file__).resolve().parents[1] / "src" / "courts_analyst" / "core"
QUERY_METHODS = {"rows", "one", "dicts", "execute", "sql", "query"}


def _formatted(node: ast.AST) -> bool:
    """True for f-strings, .format(...) and % formatting anywhere in node."""
    for n in ast.walk(node):
        if isinstance(n, ast.JoinedStr):
            return True
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod):
            return True
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "format"
        ):
            return True
    return False


def _sql_assignments(tree: ast.AST) -> dict[str, ast.AST]:
    """Module/function-level names assigned a value used as SQL."""
    out: dict[str, ast.AST] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value
    return out


def test_no_formatted_sql_in_core() -> None:
    offenders = []
    for path in CORE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        assigned = _sql_assignments(tree)
        for n in ast.walk(tree):
            if not (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in QUERY_METHODS
                and n.args
            ):
                continue
            sql = n.args[0]
            if _formatted(sql):
                offenders.append(f"{path.name}:{n.lineno}")
            elif (
                isinstance(sql, ast.Name)
                and sql.id in assigned
                and _formatted(assigned[sql.id])
            ):
                offenders.append(f"{path.name}:{n.lineno} ({sql.id})")
    assert not offenders, offenders


def test_the_checker_catches_formatting() -> None:
    bad = ast.parse('db.rows(f"SELECT * FROM t WHERE x = {x}")')
    assert _formatted(bad)
    assert _formatted(ast.parse('"SELECT %s" % x'))
    assert _formatted(ast.parse('"SELECT {}".format(x)'))
    assert not _formatted(ast.parse('"SELECT " + FRAGMENT + " WHERE x = ?"'))


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE cat.x (a INTEGER)",
        "DELETE FROM cat.observation",
        "INSERT INTO idb.data_breaks (id) VALUES ('x')",
        "SELECT * FROM read_csv('/etc/passwd')",
        "ATTACH '/tmp/other.duckdb' AS other",
        "COPY (SELECT 1) TO '/tmp/out.csv'",
    ],
)
def test_connection_is_read_only(core_db: Database, sql: str) -> None:
    with pytest.raises(Exception):  # noqa: B017 - any DuckDB refusal will do
        core_db.rows(sql)


def test_missing_catalog_is_a_typed_error(tmp_path: Path) -> None:
    from courts_analyst.core.errors import DataUnavailableError

    with pytest.raises(DataUnavailableError, match="make data-tables"):
        Database(tmp_path / "none.duckdb").rows("SELECT 1")
