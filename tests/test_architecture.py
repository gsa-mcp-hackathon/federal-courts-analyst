"""Architecture rules (ADR 0002) and repo hygiene checks."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "courts_analyst"

# core/ is pure domain logic: no protocol or web framework imports.
FORBIDDEN_IN_CORE = {"fastmcp", "mcp", "mcp_types", "starlette", "fastapi", "httpx"}


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_has_no_adapter_imports() -> None:
    offenders = {
        str(p.relative_to(ROOT)): bad
        for p in (PKG / "core").rglob("*.py")
        if (bad := _imported_roots(p) & FORBIDDEN_IN_CORE)
    }
    assert not offenders, offenders


def test_package_layout() -> None:
    for sub in ["core", "pipeline", "api", "agent", "tools", "resources", "prompts"]:
        assert (PKG / sub / "__init__.py").is_file(), sub
    for d in ["web", "eval", "data", "docs/adr"]:
        assert (ROOT / d).is_dir(), d


def _names(reqs: list[str]) -> set[str]:
    return {re.split(r"[<>=!~\[; ]", r.strip(), maxsplit=1)[0].lower() for r in reqs}


def test_requirements_txt_mirrors_pyproject() -> None:
    """Buildpack hosts read requirements.txt; keep it in step with pyproject."""
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    for req_file in [
        ROOT / "requirements.txt",
        ROOT / "deploy/ibm/local-mcp-toolkit/requirements.txt",
    ]:
        lines = [
            ln
            for ln in req_file.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        assert sorted(lines) == sorted(deps), req_file.relative_to(ROOT)
    assert _names(deps)  # sanity


def test_adrs_present() -> None:
    names = sorted(p.name for p in (ROOT / "docs/adr").glob("0*.md"))
    assert [n[:4] for n in names] == [f"{i:04d}" for i in range(1, len(names) + 1)]
    assert len(names) >= 6
