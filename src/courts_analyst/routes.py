"""Custom HTTP routes for the MCP server.

These are only active when the server runs over HTTP (streamable-http). They
sit alongside the `/mcp` endpoint on the same app.

The `/health` route matters for cloud deploys: cloud.gov, IBM Code Engine, and
Databricks Apps all use an HTTP health check to decide the app started
correctly. Keep it fast and dependency-free.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from courts_analyst import SERVICE_ID, __version__


def register_routes(mcp: FastMCP) -> None:
    """Register custom HTTP routes with the server."""

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy", "service": SERVICE_ID})

    @mcp.custom_route("/version", methods=["GET"])
    async def version(request: Request) -> JSONResponse:
        # GIT_SHA is baked into the container image at build time.
        return JSONResponse(
            {
                "service": SERVICE_ID,
                "version": __version__,
                "git_sha": os.getenv("GIT_SHA", "unknown"),
            }
        )
