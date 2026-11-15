"""eval/wxo/run_eval.sh and eval/wxo/agent_check.py, with fake ``orchestrate``
and ``courts-eval`` commands: the agent check, provenance, the held-out guard,
and the exit status on a preview-rule violation."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path("eval/wxo/run_eval.sh").resolve()
CHECK = Path("eval/wxo/agent_check.py").resolve()
AGENT = "743f0672-0000-0000-0000-000000000000"
INSTR = "Answer only with these tools.\n\nShall I go ahead?"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")


def _agent_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agent_check", CHECK)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _listing(instructions: str, tools: int) -> str:
    agent = {
        "id": AGENT,
        "name": "Untitled_Agent_1_test",
        "llm": "groq/openai/gpt-oss-120b",
        "tools": [f"t{i}" for i in range(tools)],
        "instructions": instructions,
    }
    other = {"id": "someone-else", "instructions": "x", "tools": []}
    return (
        "[INFO] - Active workspace\n" + json.dumps([other, agent]) + "\ntrailing log\n"
    )


def test_agent_check_matches_and_reports_provenance() -> None:
    mod = _agent_check()
    prov, problems = mod.check(_listing(INSTR, 8), AGENT, INSTR + "\n", 8)
    assert problems == []
    assert prov["model"] == "groq/openai/gpt-oss-120b"
    assert prov["tools"] == 8
    assert prov["instructions_chars"] == len(INSTR)
    assert prov["instructions_hash"] == mod.text_hash(INSTR)


def test_agent_check_flags_other_instructions_tools_and_missing_agent() -> None:
    mod = _agent_check()
    _, problems = mod.check(_listing(INSTR + " v2", 7), AGENT, INSTR, 8)
    assert len(problems) == 2
    assert "differ from the file" in problems[0]
    assert "7 tools, expected 8" in problems[1]
    _, problems = mod.check(_listing(INSTR, 8), "missing-id", INSTR, 8)
    assert problems == ["agent missing-id not in the listing"]


def test_text_hash_matches_the_tuning_notes() -> None:
    # v8 as committed: 5285 characters, hash 2507654590 (step 09).
    v8 = Path("eval/wxo/instructions/v8.txt").read_text().rstrip("\n")
    assert len(v8) == 5285
    assert _agent_check().text_hash(v8) == 2507654590


def _fakes(tmp: Path, listing: str, violations: int) -> dict[str, str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "calls.log"
    (tmp / "listing.txt").write_text(listing)
    orch = bin_dir / "orchestrate"
    orch.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "orchestrate $*" >> {log}
            case "$1 $2" in
              "agents list") cat {tmp / "listing.txt"} ;;
            esac
            """
        )
    )
    ce = bin_dir / "fake-courts-eval"
    ce.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "courts-eval $*" >> {log}
            if [ "$1" = run ]; then
              while [ $# -gt 0 ]; do
                case "$1" in
                  --results-dir) dir=$2 ;;
                  --provenance) cp "$2" {tmp / "provenance.json"} ;;
                esac
                shift
              done
              sleep 1; echo '{{}}' > "$dir/20990101T000000Z-wxo-all.jsonl"
            elif [ "$1" = preview-check ]; then
              [ {violations} -eq 0 ]
            fi
            """
        )
    )
    for f in (orch, ce):
        f.chmod(0o755)
    instr = tmp / "v.txt"
    instr.write_text(INSTR + "\n")
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "COURTS_EVAL": str(ce),
        "PYTHON": sys.executable,
        "WXO_INSTANCE_URL": "https://example.invalid",
        "WXO_API_KEY": "not-a-real-key-0123456789",
        "WXO_AGENT_ID": AGENT,
        "WXO_ENV_NAME": "testenv",
        "RESULTS_DIR": str(tmp / "results"),
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        cwd=CHECK.parents[2],
    )


def test_heldout_runs_test2_once_with_provenance(tmp_path: Path) -> None:
    env = _fakes(tmp_path, _listing(INSTR, 8), violations=0)
    instr = str(tmp_path / "v.txt")
    first = _run(env, "heldout", instr)
    assert first.returncode == 0, first.stderr
    calls = (tmp_path / "calls.log").read_text()
    assert "--split test2" in calls
    assert "--repeats 3" in calls and "--agent-tools wxo" in calls
    assert "preview-check" in calls
    prov = json.loads((tmp_path / "provenance.json").read_text())
    assert prov["instructions_hash"] == _agent_check().text_hash(INSTR)
    assert prov["tools"] == 8
    assert env["WXO_API_KEY"] not in first.stdout + first.stderr

    again = _run(env, "heldout", instr)
    assert again.returncode == 1
    assert "already scored" in again.stderr
    env["HELDOUT_AGAIN"] = "1"
    assert _run(env, "heldout", instr).returncode == 0


def test_mismatched_agent_stops_before_the_run(tmp_path: Path) -> None:
    env = _fakes(tmp_path, _listing(INSTR + " older", 8), violations=0)
    r = _run(env, "dev", str(tmp_path / "v.txt"))
    assert r.returncode == 1
    assert "differ from the file" in r.stderr
    assert "courts-eval run" not in (tmp_path / "calls.log").read_text()


def test_preview_violation_fails_the_run(tmp_path: Path) -> None:
    env = _fakes(tmp_path, _listing(INSTR, 8), violations=1)
    r = _run(env, "dev", str(tmp_path / "v.txt"))
    assert r.returncode == 1
    assert "--split dev" in (tmp_path / "calls.log").read_text()


def test_missing_key_and_bad_kind(tmp_path: Path) -> None:
    env = _fakes(tmp_path, _listing(INSTR, 8), violations=0)
    del env["WXO_API_KEY"]
    r = _run(env, "dev", str(tmp_path / "v.txt"))
    assert r.returncode == 1
    assert "WXO_API_KEY is not set" in r.stderr
    assert _run(env, "everything").returncode == 2
