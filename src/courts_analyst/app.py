"""MCP server entry point.

Keep this file THIN. It only:
  1. builds the FastMCP instance (`build_server`),
  2. registers tools / prompts / resources / routes from the submodules, and
  3. decides which transport to run (stdio locally vs. HTTP when deployed).

The deploy kits import the module-level `mcp` (`courts_analyst.app:mcp`), so
it must exist at import time and must not touch the network or the data files.
"""

from __future__ import annotations

import logging
import os

from fastmcp import FastMCP

from courts_analyst import SERVER_NAME, __version__
from courts_analyst.config import settings
from courts_analyst.logging_config import configure_logging
from courts_analyst.middleware import RequestLogging
from courts_analyst.prompts import register_prompts
from courts_analyst.resources import register_resources
from courts_analyst.routes import register_routes
from courts_analyst.tools import register_tools

INSTRUCTIONS = (
    "Federal Courts Analyst answers questions about federal district court "
    "workload (civil and criminal filings, terminations, pending cases, time to "
    "disposition, judgeships) from official uscourts.gov tables (FY2016–FY2025, "
    "with national rows back to 1990) and the FJC Integrated Database (civil "
    "cases, FY2015–FY2025). Official figures can differ between editions of the "
    "same table: every figure says which edition it comes from. When editions "
    "disagree, give both and say which is current; never average or mix them. "
    "Label anything marked 'inferred' as inference. Report n and say when there "
    "are too few cases. The server has no judge-level data and no party names: "
    "decline requests to rank or profile judges or to name parties. Call "
    "`server_info` to check what data is loaded."
)

# The data only changes when `make data` rebuilds it (ADR 0001: FastMCP 4 has
# server-wide cache hints only; edition resources also say so in their _meta).
CACHE_TTL_SECONDS = 3600


def build_server() -> FastMCP:
    """Create the FastMCP server with every tool, resource, prompt and route."""
    server = FastMCP(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        cache_ttl=CACHE_TTL_SECONDS,
        cache_scope="public",
    )
    server.add_middleware(RequestLogging())
    register_tools(server)
    register_prompts(server)
    register_resources(server)
    register_routes(server)
    return server


mcp = build_server()
# Not __name__: under `python -m courts_analyst.app` that is "__main__".
logger = logging.getLogger("courts_analyst.app")


def main() -> None:
    """Start the server, choosing a transport based on the environment.

    Precedence:
      1. A platform-injected port (Databricks `DATABRICKS_APP_PORT` or a generic
         `PORT`) → run HTTP on that port. Cloud hosts set this for you.
      2. `MCP_TRANSPORT=streamable-http` in the environment → run HTTP on
         `MCP_HOST`:`MCP_PORT` (see config.py / .env).
      3. Otherwise → stdio, which is how local clients (Claude Desktop, Claude
         Code, Zed) launch the server as a subprocess.
    """
    platform_port = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    http = bool(platform_port) or settings.mcp_transport == "streamable-http"

    json_logs = settings.log_format == "json" or (
        settings.log_format == "auto" and http
    )
    configure_logging(settings.log_level, json_format=json_logs)
    logger.info(
        "starting server",
        extra={
            "version": __version__,
            "transport": "http" if http else "stdio",
            "port": int(platform_port or settings.mcp_port) if http else None,
        },
    )

    if platform_port:
        mcp.run(transport="http", host="0.0.0.0", port=int(platform_port))
    elif http:
        mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
