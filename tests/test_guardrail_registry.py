"""Every data-returning core function passes through apply_policies.

Exit criterion for Phase 6: any public function in core/ annotated to return
a ``Result`` must be decorated with ``@guarded`` (and so appear in the
registry), and every tool calls only such functions.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

import courts_analyst.core as core_pkg
from courts_analyst.core.guardrails import REGISTRY, is_guarded

PKG = Path(core_pkg.__file__).parent
TOOLS = PKG.parent / "tools"


# Result builders (ok, clarify, decline) construct envelopes; they return no data.
BUILDERS = "courts_analyst.core.results"


def _core_modules() -> list[str]:
    return [
        m.name
        for m in pkgutil.walk_packages([str(PKG)], prefix="courts_analyst.core.")
        if not m.ispkg and m.name != BUILDERS
    ]


def _result_functions() -> dict[str, object]:
    found = {}
    for name in _core_modules():
        mod = importlib.import_module(name)
        for fname, fn in inspect.getmembers(mod, inspect.isfunction):
            if fname.startswith("_") or fn.__module__ != name:
                continue
            ret = str(getattr(fn, "__annotations__", {}).get("return", ""))
            if ret.startswith("Result["):
                found[f"{name}.{fname}"] = fn
    return found


def test_every_result_function_is_guarded() -> None:
    fns = _result_functions()
    assert len(fns) >= 11, sorted(fns)
    unguarded = [n for n, fn in fns.items() if not is_guarded(fn)]
    assert not unguarded, unguarded
    assert set(fns) <= set(REGISTRY)


def test_tools_call_only_guarded_core_functions() -> None:
    guarded_names = {n.rsplit(".", 1)[1] for n in REGISTRY}
    result_names = {n.rsplit(".", 1)[1] for n in _result_functions()}
    for path in TOOLS.glob("*.py"):
        tree = ast.parse(path.read_text())
        imported = {
            a.asname or a.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("courts_analyst.core")
            for a in node.names
        }
        calls = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        for name in imported & calls & result_names:
            assert name in guarded_names, (path.name, name)
