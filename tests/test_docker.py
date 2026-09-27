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

# How the image is meant to run (Phase 6): read-only root filesystem with a
# small writable /tmp, no Linux capabilities, no privilege escalation.
HARDENED = [
    "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
]  # fmt: skip


@pytest.fixture(scope="module")
def container_name() -> Iterator[str]:
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    name = f"fca-test-{uuid.uuid4().hex[:8]}"
    cmd = ["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::8080"]
    subprocess.run(
        [*cmd, *HARDENED, IMAGE],
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


def test_container_is_hardened(container_name: str) -> None:
    """Non-root, read-only root filesystem, writable /tmp only."""
    name = container_name.split()[0]

    def sh(cmd: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "exec", name, "sh", "-c", cmd], capture_output=True, text=True
        )

    assert sh("id -u").stdout.strip() == "10001"
    assert sh("touch /app/x").returncode != 0
    assert sh("touch /app/data/x").returncode != 0
    assert sh("touch /tmp/x && rm /tmp/x").returncode == 0


def test_security_headers(container: str) -> None:
    r = httpx.get(f"{container}/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_logs_are_json(container_name: str) -> None:
    import json

    name = container_name.split()[0]
    # Our logger emits JSON in HTTP mode; framework lines (uvicorn) may not.
    logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
    ours = [ln for ln in logs.stderr.splitlines() if '"logger": "courts_analyst' in ln]
    assert ours, logs.stderr
    for line in ours:
        assert json.loads(line)["level"]


CORE_SMOKE = """
from courts_analyst.config import settings
from courts_analyst.core.db import Database
from courts_analyst.core.official import get_official_figure
from courts_analyst.core.reconcile import classify
db = Database(settings.resolved_duckdb_path, settings.resolved_idb_path)
f = get_official_figure(db, "weighted_civil_filings_per_judgeship", "US", 2020).data
print(f.value, f.edition, f.first_published.value, classify("civil_cases_filed", 1, 1, [])[0])
"""


def _run_with_catalog(db_dir: str) -> tuple[str, str]:
    """Start the image with a built catalog mounted read-only at DATA_DIR/build."""
    name = f"fca-data-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::8080",
            *HARDENED, "-v", f"{db_dir}:/app/data/build:ro", IMAGE,
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


async def test_container_reads_built_catalog(catalog, idb, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The deploy story: `make data` output mounted into the image → ready.

    Only data/build is mounted; the IDB party names (data/private) never are.
    """
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    shutil.copy(catalog.db, build_dir / "courts.duckdb")
    shutil.copy(idb.db, build_dir / "idb.duckdb")
    shutil.copy(idb.db.with_name("pii_index.bin"), build_dir / "pii_index.bin")
    build_dir.chmod(0o755)
    for f in build_dir.iterdir():
        f.chmod(0o644)
    name, base = _run_with_catalog(str(build_dir))
    try:
        async with Client(f"{base}/mcp") as c:
            result = await c.call_tool("server_info", {})
        assert result.structured_content is not None
        assert result.structured_content["data_status"] == "ready"
        assert result.structured_content["datasets"] == {
            "official_tables": "ready",
            "idb_civil": "ready",
        }
        ls = subprocess.run(
            ["docker", "exec", name, "ls", "-A", "/app/data"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "private" not in ls.stdout.split()
        # The data tools answer over streamable HTTP from the container.
        async with Client(f"{base}/mcp") as c:
            fig = await c.call_tool(
                "get_official_figure",
                {
                    "measure": "weighted_civil_filings_per_judgeship",
                    "fiscal_year": 2020,
                },
            )
            cases = await c.call_tool(
                "find_cases", {"courts": ["FL-N"], "fy_from": 2020, "fy_to": 2020}
            )
            handle = cases.structured_content["data"]["handle"]
            median = await c.call_tool(
                "analyze_cohort",
                {"handle": handle, "metric": "median_days_to_disposition"},
            )
        assert cases.structured_content["status"] == "ok"  # PII scanner loaded
        assert fig.structured_content["data"]["value"] == 322
        assert fig.structured_content["data"]["first_published"]["value"] == 554
        assert median.structured_content["data"]["results"][0]["n"] > 0
        # Phase 7: REST and the agent stream from the same container.
        rest = httpx.get(
            f"{base}/api/figures",
            params={
                "measure": "weighted_civil_filings_per_judgeship",
                "fiscal_year": 2020,
            },
            timeout=10,
        )
        assert rest.status_code == 200 and rest.headers["etag"]
        assert rest.json()["data"] == fig.structured_content["data"]
        declined = httpx.post(
            f"{base}/api/ask",
            json={"question": "Rank the judges in S.D.N.Y. by speed"},
            timeout=30,
        )
        assert "event: warning" in declined.text
        assert '"stop_reason":"declined"' in declined.text
        # No model key in the container: a typed error, then turn_end.
        no_key = httpx.post(
            f"{base}/api/ask", json={"question": "What data is loaded?"}, timeout=30
        )
        assert '"code":"model_not_configured"' in no_key.text
        assert no_key.text.rstrip().splitlines()[-1].startswith("data: ")
        assert "event: turn_end" in no_key.text
        # Phase 8: the web app is served at / with its own CSP, deep links too.
        page = httpx.get(
            f"{base}/editions/weighted-civil-filings-per-judgeship/national/2020",
            timeout=10,
        )
        assert page.status_code == 200 and '<div id="root">' in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        geo = httpx.get(f"{base}/geo/districts.topo.json", timeout=10)
        assert geo.status_code == 200 and geo.json()["type"] == "Topology"
        runs = httpx.get(f"{base}/api/eval/runs", timeout=10).json()["runs"]
        assert any(r["run_id"] == "phase3-gold-all" for r in runs)
        # The analytics core runs in the image against the mounted data.
        core = subprocess.run(
            ["docker", "exec", name, "python", "-c", CORE_SMOKE],
            capture_output=True,
            text=True,
            check=True,
        )
        assert core.stdout.split() == ["322.0", "JFF-2025", "554.0", "matched"], (
            core.stderr
        )
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)
