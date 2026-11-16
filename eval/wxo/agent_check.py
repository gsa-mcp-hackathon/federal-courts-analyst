"""Check the live wxO agent against an instruction file and write provenance.

Reads the output of ``orchestrate agents list -v`` (JSON objects mixed with
log lines), finds the agent by id, and compares its instructions with the
file (trailing newlines stripped). Writes a provenance JSON for
``courts-eval run --provenance`` and exits 1 when the instructions differ or
the agent doesn't have the expected number of tools.

Usage:
    orchestrate agents list -v > agents.txt
    python eval/wxo/agent_check.py agents.txt AGENT_ID eval/wxo/instructions/v8.txt \\
        --tools 8 --out provenance.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def text_hash(text: str) -> int:
    """The 32-bit hash the tuning notes quote ("5285 / 2507654590")."""
    h = 0
    for c in text:
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return h


def json_objects(raw: str) -> list[Any]:
    """Every JSON value that starts at a ``[`` or ``{`` in *raw*."""
    dec = json.JSONDecoder()
    out: list[Any] = []
    i = 0
    while True:
        starts = [p for p in (raw.find("[", i), raw.find("{", i)) if p >= 0]
        if not starts:
            return out
        j = min(starts)
        try:
            obj, i = dec.raw_decode(raw, j)
            out.append(obj)
        except ValueError:
            i = j + 1


def find_agent(objs: list[Any], agent_id: str) -> dict[str, Any] | None:
    def walk(o: Any) -> Iterator[dict[str, Any]]:
        if isinstance(o, dict):
            if o.get("id") == agent_id:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)

    return next(walk(objs), None)


def check(
    agents_output: str, agent_id: str, instructions: str, tools: int
) -> tuple[dict[str, Any], list[str]]:
    """Provenance for the run and a list of problems (empty when it matches)."""
    want = instructions.rstrip("\n")
    agent = find_agent(json_objects(agents_output), agent_id)
    if agent is None:
        return {"agent_id": agent_id}, [f"agent {agent_id} not in the listing"]
    have = str(agent.get("instructions") or "").rstrip("\n")
    tool_list = agent.get("tools") or []
    prov = {
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "model": agent.get("llm"),
        "tools": len(tool_list),
        "instructions_chars": len(have),
        "instructions_hash": text_hash(have),
        "instructions_sha256": hashlib.sha256(have.encode()).hexdigest(),
    }
    problems = []
    if have != want:
        problems.append(
            f"server instructions ({len(have)} chars, hash {text_hash(have)}) "
            f"differ from the file ({len(want)} chars, hash {text_hash(want)})"
        )
    if len(tool_list) != tools:
        problems.append(f"agent has {len(tool_list)} tools, expected {tools}")
    return prov, problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("agents_output", type=Path)
    p.add_argument("agent_id")
    p.add_argument("instructions", type=Path)
    p.add_argument("--tools", type=int, default=8)
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    prov, problems = check(
        a.agents_output.read_text(),
        a.agent_id,
        a.instructions.read_text(),
        a.tools,
    )
    prov["instructions_file"] = str(a.instructions)
    if a.out:
        a.out.write_text(json.dumps(prov, indent=2) + "\n")
    for line in problems:
        print(f"agent-check: {line}", file=sys.stderr)
    if not problems:
        print(
            f"agent-check: OK {prov['agent_name']} {prov['model']} "
            f"{prov['tools']} tools, instructions {prov['instructions_chars']} "
            f"chars hash {prov['instructions_hash']}"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
