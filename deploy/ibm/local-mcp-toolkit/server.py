#!/usr/bin/env python
"""Local MCP toolkit entrypoint for watsonx Orchestrate (stdio transport).

watsonx Orchestrate runs a LOCAL MCP toolkit by starting this script inside its
own runtime and speaking MCP over stdio. This entrypoint reuses the EXISTING
FastMCP server defined in the `courts_analyst` package and runs it over stdio —
no HTTP, no Code Engine, no container.

The register script stages this file NEXT TO the `courts_analyst` package
(flattened out of the repo's src/ layout), so `courts_analyst` is importable
from this script's own directory. We add that directory to sys.path defensively
in case Orchestrate runs the command from a different working directory.

Orchestrate invokes:  python server.py
"""

import os
import sys

# Ensure the directory containing this file (which also contains the
# `courts_analyst` package after staging) is importable, regardless of CWD.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The register script ships the official tables catalog next to this file
# (data/courts.duckdb). Settings are read at import, so set the paths first;
# an explicit environment variable still wins.
os.environ.setdefault("DUCKDB_PATH", os.path.join(HERE, "data", "courts.duckdb"))
# The civil IDB, when the register script shipped it (its hashed party-name
# index sits next to it). If it's absent the case-level tools say so.
os.environ.setdefault("IDB_DUCKDB_PATH", os.path.join(HERE, "data", "idb.duckdb"))
# The request desk (ADR 0013) needs a writable file; the toolkit's own folder
# may not be writable, /tmp is.
os.environ.setdefault("DESK_STORE_PATH", "/tmp/courts-analyst/desk.sqlite")

from courts_analyst.app import mcp  # noqa: E402

if __name__ == "__main__":
    # stdio is the transport watsonx Orchestrate uses for local MCP toolkits.
    mcp.run(transport="stdio")
