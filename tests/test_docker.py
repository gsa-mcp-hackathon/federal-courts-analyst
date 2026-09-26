"""Integration: the built container image serves health, version and MCP.

Run with `make docker-test` (builds the image first). Skipped from the default
suite by the `docker` marker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastmcp import Client

from courts_analyst import __version__

pytestmark = pytest.mark.docker

IMAGE = os.getenv("IMAGE", "federal-courts-analyst:dev")


@pytest.fixture(scope="module")
def container_name() -> Iterator[str]:
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    name = f"fca-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::8080", IMAGE],
        check=True,
        capture_output=True,
    )
    try:
        port = (
            subprocess.run(
                ["docker", "port", name, "8080/tcp"],
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .splitlines()[0]
            .rsplit(":", 1)[1]
        )
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.3)
        else:
            logs = subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True
            )
            pytest.fail(f"container never became healthy:\n{logs.stderr}")
        yield f"{name} {base}"
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture(scope="module")
def container(container_name: str) -> str:
    """Base URL of the running container."""
    return container_name.split()[1]


def test_health(container: str) -> None:
    assert httpx.get(f"{container}/health").json()["status"] == "healthy"


def test_version_has_git_sha(container: str) -> None:
    body = httpx.get(f"{container}/version").json()
    assert body["version"] == __version__
    assert body["git_sha"] != ""


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_mcp_server_info(container: str, mode: str) -> None:
    async with Client(f"{container}/mcp", mode=mode) as c:
        result = await c.call_tool("server_info", {})
    assert result.structured_content is not None
    assert result.structured_content["data_status"] == "not_built"


def test_logs_are_json(container_name: str) -> None:
    import json

    name = container_name.split()[0]
    # Our logger emits JSON in HTTP mode; framework lines (uvicorn) may not.
    logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
    ours = [ln for ln in logs.stderr.splitlines() if '"logger": "courts_analyst' in ln]
    assert ours, logs.stderr
    for line in ours:
        assert json.loads(line)["level"]


def _run_with_catalog(db_dir: str) -> tuple[str, str]:
    """Start the image with a built catalog mounted read-only at DATA_DIR/build."""
    name = f"fca-data-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::8080",
            "-v", f"{db_dir}:/app/data/build:ro", IMAGE,
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    port = (
        subprocess.run(
            ["docker", "port", name, "8080/tcp"],
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()[0]
        .rsplit(":", 1)[1]
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.3)
    return name, base


async def test_container_reads_built_catalog(catalog, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The deploy story: `make data-tables` output mounted into the image → ready."""
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    shutil.copy(catalog.db, build_dir / "courts.duckdb")
    build_dir.chmod(0o755)
    (build_dir / "courts.duckdb").chmod(0o644)
    name, base = _run_with_catalog(str(build_dir))
    try:
        async with Client(f"{base}/mcp") as c:
            result = await c.call_tool("server_info", {})
        assert result.structured_content is not None
        assert result.structured_content["data_status"] == "ready"
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)
