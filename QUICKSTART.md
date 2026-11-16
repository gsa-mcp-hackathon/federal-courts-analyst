# Quickstart — Run Federal Courts Analyst in 5 Minutes

This gets you from clone to a running server connected to a client.

## 1. Install prerequisites

You need [uv](https://docs.astral.sh/uv/) (a fast Python package manager):

```bash
pip install uv     # or: brew install uv
```

## 2. Set up the project

```bash
make setup     # or: cp .env.example .env && uv sync --group dev
```

## 3. Run the server

```bash
uv run python main.py
```

The server starts in **stdio** mode and waits for a client to connect over
stdin/stdout. That's correct — it doesn't print a URL, because a local MCP
server is launched *by* the client as a subprocess. Press `Ctrl-C` to stop it.

## 4. Connect a client

### Claude Code

The repo already includes a project `.mcp.json`; start Claude Code in the repo
and approve the `courts-analyst` server. To use it from another directory, add
this to your user MCP settings with the **absolute path** to this repo:

```json
{
  "mcpServers": {
    "courts-analyst": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/absolute/path/to/federal-courts-analyst", "courts-analyst"]
    }
  }
}
```

### Claude Desktop

Add the same block to
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows), then restart Claude
Desktop.

`uv run --directory` runs the server from the repo, so it finds `data/`
wherever the client starts it. Build the data first (`make data`).

Once connected, try:

> "Call server_info from the courts-analyst server." (version, protocols, which datasets are built)
>
> "What were weighted civil filings per judgeship nationally in FY2020?" (322 in JFF-2025, first published as 554 in JB-2020)
>
> "Why did federal civil filings jump in FY2020?" (explain_change: N.D. Fla., directly filed MDL cases)
>
> "Which five districts had the highest weighted filings per judgeship in FY2024?" (compare_courts)

## 5. Verify everything

```bash
make lint typecheck test
```

## 6. Test HTTP mode (optional)

Cloud hosts run the server over HTTP. Try it locally:

```bash
MCP_TRANSPORT=streamable-http uv run python main.py
# in another terminal:
curl http://localhost:8000/health      # {"status":"healthy",...}
```

---

## Next steps

- Build plan and current phase: [plan/README.md](plan/README.md)
- Deploy: [deploy/README.md](deploy/README.md) (Databricks Apps, IBM watsonx Orchestrate)
- Inspect the server in a browser: `make inspector`
