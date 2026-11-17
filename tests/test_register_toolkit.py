"""Tests for deploy/ibm/local-mcp-toolkit/register-toolkit.sh.

Verifies that the script handles large `orchestrate` output (10 000+ lines)
without SIGPIPE errors, replaces an existing toolkit only when asked to
(REPLACE_EXISTING=1), applies the size cap only when replacing, and refuses to
ship an IDB without its party-name index.
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
    inherited = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {"REPLACE_EXISTING", "INCLUDE_IDB", "IDB_DUCKDB_PATH", "MAX_STAGE_MB"}
    }
    return {
        **inherited,
        "WXO_ENV_NAME": "testenv",
        "WXO_INSTANCE_URL": "https://example.invalid",
        "TOOLKIT_NAME": name,
        "WXO_API_KEY": "dummy",  # pragma: allowlist secret
        "DUCKDB_PATH": str(duckdb),
    }


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_remove_called_when_toolkit_exists(tmp_path: Path) -> None:
    """When the toolkit name appears in ``toolkits list`` and REPLACE_EXISTING=1,
    the script must call ``toolkits remove`` before ``toolkits import`` and must
    exit successfully."""
    name = "courts_analyst_test"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    log_file.touch()

    _make_fake_orchestrate(bin_dir, log_file, env_name="testenv", toolkit_name=name)

    env = _base_env(tmp_path, name)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["REPLACE_EXISTING"] = "1"

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


def _run(
    tmp_path: Path, listed: str, wanted: str, **extra: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the script against a fake ``orchestrate`` that lists *listed*."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_file = tmp_path / "calls.log"
    log_file.write_text("")
    _make_fake_orchestrate(bin_dir, log_file, env_name="testenv", toolkit_name=listed)
    env = _base_env(tmp_path, wanted)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env.update(extra)
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True
    )
    return result, log_file.read_text().splitlines()


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_existing_toolkit_is_left_alone_without_replace(tmp_path: Path) -> None:
    """Replacing takes the tools off every agent, so it needs REPLACE_EXISTING=1:
    without it the script stops before removing or importing anything."""
    result, calls = _run(tmp_path, "courts_analyst_test", "courts_analyst_test")
    assert result.returncode == 1
    assert "Nothing changed" in result.stderr
    assert not any("toolkits remove" in c or "toolkits import" in c for c in calls)


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_size_cap_applies_only_when_replacing(tmp_path: Path) -> None:
    """A refused upload under a new name breaks nothing (that's how to test a
    size), but when replacing it would leave the name empty."""
    result, calls = _run(
        tmp_path, "other_toolkit", "courts_analyst_new", MAX_STAGE_MB="0"
    )
    assert result.returncode == 0, result.stderr
    assert any("toolkits import" in c for c in calls)

    result, calls = _run(
        tmp_path,
        "courts_analyst_test",
        "courts_analyst_test",
        REPLACE_EXISTING="1",
        MAX_STAGE_MB="0",
    )
    assert result.returncode == 1
    assert "Nothing was changed" in result.stderr
    assert not any("toolkits remove" in c or "toolkits import" in c for c in calls)


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not installed")
def test_idb_needs_its_party_name_index(tmp_path: Path) -> None:
    """INCLUDE_IDB=1 stops (nothing imported) if the IDB or the hashed
    party-name index the output scanner needs is missing."""
    idb_dir = tmp_path / "slim"
    idb_dir.mkdir()
    idb = idb_dir / "idb.duckdb"
    result, calls = _run(
        tmp_path, "x", "courts_analyst_new", INCLUDE_IDB="1", IDB_DUCKDB_PATH=str(idb)
    )
    assert result.returncode == 1
    assert "no IDB" in result.stderr

    idb.touch()
    result, calls = _run(
        tmp_path, "x", "courts_analyst_new", INCLUDE_IDB="1", IDB_DUCKDB_PATH=str(idb)
    )
    assert result.returncode == 1
    assert "pii_index.bin" in result.stderr
    assert not any("toolkits import" in c for c in calls)

    (idb_dir / "pii_index.bin").touch()
    result, calls = _run(
        tmp_path, "x", "courts_analyst_new", INCLUDE_IDB="1", IDB_DUCKDB_PATH=str(idb)
    )
    assert result.returncode == 0, result.stderr
    assert "including the civil IDB" in result.stdout
