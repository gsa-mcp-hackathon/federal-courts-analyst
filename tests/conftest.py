"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastmcp import Client

from courts_analyst.app import mcp


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    """In-memory MCP client on the modern (2026-07-28) protocol."""
    async with Client(mcp) as c:
        yield c


@pytest.fixture
async def legacy_client() -> AsyncIterator[Client]:
    """In-memory MCP client pinned to the 2025-11-25 handshake era."""
    async with Client(mcp, mode="legacy") as c:
        yield c
