"""Integration: the real server process over HTTP and stdio."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from courts_analyst import SERVICE_ID, __version__

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _server_env(**extra: str) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in {"PORT", "DATABRICKS_APP_PORT"}
    }
    env["PYTHONPATH"] = str(ROOT / "src")
    env.update(extra)
    return env


@pytest.fixture(scope="module")
def http_server() -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "courts_analyst.app"],
        env=_server_env(
            MCP_TRANSPORT="streamable-http", MCP_HOST="127.0.0.1", MCP_PORT=str(port)
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err = proc.stderr.read().decode() if proc.stderr else ""
                pytest.fail(f"server exited early: {err}")
            try:
                if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not become healthy within 20s")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_health(http_server: str) -> None:
    r = httpx.get(f"{http_server}/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy", "service": SERVICE_ID}


def test_version(http_server: str) -> None:
    r = httpx.get(f"{http_server}/version")
    assert r.status_code == 200
    assert r.json()["version"] == __version__


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_mcp_over_http(http_server: str, mode: str) -> None:
    async with Client(f"{http_server}/mcp", mode=mode) as c:
        result = await c.call_tool("server_info", {})
    assert result.structured_content is not None
    assert result.structured_content["version"] == __version__


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_mcp_over_stdio(mode: str) -> None:
    transport = StdioTransport(
        sys.executable, ["-m", "courts_analyst.app"], env=_server_env(), cwd=str(ROOT)
    )
    async with Client(transport, mode=mode) as c:
        result = await c.call_tool("server_info", {})
    assert result.structured_content is not None
    from tests.test_registration import EXPECTED_TOOLS

    assert result.structured_content["tools"] == sorted(EXPECTED_TOOLS)


def test_platform_port_forces_http() -> None:
    """A host-injected PORT must win over MCP_TRANSPORT=stdio (cloud deploys)."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "courts_analyst.app"],
        env=_server_env(MCP_TRANSPORT="stdio", PORT=str(port)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
                assert r.status_code == 200
                return
            except httpx.TransportError:
                time.sleep(0.1)
        pytest.fail("server did not serve HTTP on the injected PORT")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
