"""Tests for deploy/ibm/local-mcp-toolkit/register-toolkit.sh.

Verifies that the script handles large `orchestrate` output (10 000+ lines)
without SIGPIPE errors, and correctly decides whether to remove an existing
toolkit before importing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path("deploy/ibm/local-mcp-toolkit/register-toolkit.sh")


def _make_fake_orchestrate(
    bin_dir: Path,
    log_file: Path,
    env_name: str,
    toolkit_name: str,
) -> None:
    """Write a fake `orchestrate` script into *bin_dir*.

    For ``env list`` it prints 5 000 filler lines, then a line containing
    *env_name*, then 5 000 more.  For ``toolkits list`` the same but with
    *toolkit_name*.  This is large enough that a pipe into ``grep -q`` would
    trigger SIGPIPE on the writer if composed as ``orchestrate … | grep -q``.

    For every invocation it appends ``"$@"`` to *log_file*.
    """
    filler = "\n".join(f"filler line {i}" for i in range(5000))
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> {log_file}
        case "$1 $2" in
          "env list")
            printf '%s\\n' {filler!r}
            echo "  {env_name}  "
            printf '%s\\n' {filler!r}
            ;;
          "toolkits list")
            printf '%s\\n' {filler!r}
            echo "  {toolkit_name}  "
            printf '%s\\n' {filler!r}
            ;;
          "env activate")
            ;;
          "env add")
            ;;
          "toolkits remove")
            ;;
          "toolkits import")
            ;;
          *)
            ;;
        esac
        """
    )
    fake = bin_dir / "orchestrate"
    fake.write_text(script)
    fake.chmod(0o755)


def _base_env(tmp_path: Path, name: str) -> dict[str, str]:
    """Environment variables for a register-toolkit.sh run."""
    duckdb = tmp_path / "courts.duckdb"
    duckdb.touch()
    return {
        **os.environ,
        "WXO_ENV_NAME": "testenv",
        "WXO_INSTANCE_URL": "https://example.invalid",
        "TOOLKIT_NAME": name,
        "WXO_API_KEY": "dummy",  # pragma: allowlist secret
        "DUCKDB_PATH": str(duckdb),
    }


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_remove_called_when_toolkit_exists(tmp_path: Path) -> None:
    """When the toolkit name appears in ``toolkits list``, the script must call
    ``toolkits remove`` before ``toolkits import`` and must exit successfully."""
    name = "courts_analyst_test"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    log_file.touch()

    _make_fake_orchestrate(bin_dir, log_file, env_name="testenv", toolkit_name=name)

    env = _base_env(tmp_path, name)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    calls = log_file.read_text().splitlines()

    # ``toolkits remove`` must precede ``toolkits import``
    remove_indices = [i for i, c in enumerate(calls) if "toolkits remove" in c]
    import_indices = [i for i, c in enumerate(calls) if "toolkits import" in c]
    assert remove_indices, f"toolkits remove not called; calls={calls}"
    assert import_indices, f"toolkits import not called; calls={calls}"
    assert remove_indices[0] < import_indices[0], (
        f"toolkits remove must come before toolkits import; calls={calls}"
    )

    # The env already exists, so ``env add`` must NOT be called
    assert not any("env add" in c for c in calls), (
        f"env add must not be called when env exists; calls={calls}"
    )


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_no_remove_when_toolkit_absent(tmp_path: Path) -> None:
    """When the toolkit name does NOT appear in ``toolkits list``, the script
    must not call ``toolkits remove`` and must still exit successfully."""
    present_name = "courts_analyst_test2"
    wanted_name = "courts_analyst_test"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    log_file.touch()

    # The fake orchestrate outputs *present_name* for toolkits, not *wanted_name*
    _make_fake_orchestrate(
        bin_dir, log_file, env_name="testenv", toolkit_name=present_name
    )

    env = _base_env(tmp_path, wanted_name)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    calls = log_file.read_text().splitlines()
    assert not any("toolkits remove" in c for c in calls), (
        f"toolkits remove must not be called when toolkit is absent; calls={calls}"
    )
