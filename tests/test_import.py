"""Smoke: the package imports and the server builds without network access."""

from __future__ import annotations

import socket

import pytest

import courts_analyst
from courts_analyst.app import build_server, mcp


def test_version_is_semver() -> None:
    parts = courts_analyst.__version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_module_level_server_exists() -> None:
    # Deploy kits import `courts_analyst.app:mcp`.
    assert mcp.name == courts_analyst.SERVER_NAME


def test_build_server_makes_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("build_server() tried to open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    server = build_server()
    assert server.name == courts_analyst.SERVER_NAME
