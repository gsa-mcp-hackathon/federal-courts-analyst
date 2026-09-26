"""Shared Pydantic models for tool inputs and outputs.

Tools return these models so FastMCP publishes a precise `outputSchema` and
clients receive `structuredContent`. Provenance and edition models land here
in Phase 1/4.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DataStatus = Literal["not_built", "ready"]


class ServerInfo(BaseModel):
    """Identity and readiness of the Federal Courts Analyst server."""

    name: str = Field(description="Human-readable server name.")
    version: str = Field(description="Server package version (semver).")
    protocol_versions: list[str] = Field(
        description="MCP protocol versions this server can negotiate, newest first."
    )
    data_status: DataStatus = Field(
        description=(
            "'ready' when the analytical DuckDB file exists; 'not_built' before "
            "`make data` has run, in which case data tools will be unavailable."
        )
    )
    coverage: str = Field(
        description="Plain-language summary of what the data covers.",
    )
    tools: list[str] = Field(description="Names of the tools this server exposes.")
