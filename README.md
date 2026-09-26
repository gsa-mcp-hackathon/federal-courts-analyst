# Federal Courts Analyst

An MCP server that answers plain-language questions about federal court workload,
built for GSA's MCP Server and AI Agent Government Hackathon (Dataset Access track).
For recent years the judiciary publishes more than one official figure for the same
statistic. This server knows which edition each number comes from and why the
editions differ.

- Concept: [`Federal Courts Analyst — MCP Hackathon Concept.md`](Federal%20Courts%20Analyst%20—%20MCP%20Hackathon%20Concept.md)
- Build plan and phase status: [`plan/`](plan/README.md)
- Architecture decisions: [`docs/adr/`](docs/adr/README.md)
- Data sources and methodology: [`docs/data-sources.md`](docs/data-sources.md)
- Every official figure revised between editions: [`docs/revision-log.md`](docs/revision-log.md)

Built on the [GSA MCP hackathon template](https://github.com/GSA-TTS/mcp-hackathon-template)
with [FastMCP 4](https://gofastmcp.com) (MCP spec 2026-07-28, backward compatible
with 2025-11-25 clients) and [uv](https://docs.astral.sh/uv/).

> **Status: Phase 1 (official tables catalog).** `make data-tables` builds an
> edition-aware catalog of six uscourts.gov tables (FY2016–FY2025, 60 editions,
> ~32,600 values) in DuckDB, with a generated revision log. The server still
> exposes only `server_info`; the IDB (P2) and statistics tools (P4–P5) follow.

---

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and `make`. Docker is optional.

```bash
make setup        # install dev + pipeline deps, pre-commit hooks, create .env
make test         # pytest with coverage (builds the catalog from committed fixtures)
make data-tables  # download the official tables (≈4 min, polite) and build courts.duckdb
make serve        # MCP over stdio (what Claude Desktop/Code launch)
make serve-http   # MCP over streamable HTTP on :8000 (/mcp, /health, /version)
make help         # every target
```

Connect Claude Code: the repo ships a project `.mcp.json`, so opening Claude Code
in this directory offers the `courts-analyst` server. For Claude Desktop, see
[QUICKSTART.md](QUICKSTART.md).

## Make targets

| Target | What it does |
| --- | --- |
| `setup` | `uv sync --group dev --group pipeline`, install pre-commit hooks, copy `.env.example` → `.env` |
| `lint` / `format` | ruff lint and format check / auto-fix |
| `typecheck` | mypy (strict on `core/` and `models.py`) |
| `test` | Fast suite with coverage (excludes `@fulldata` and `@docker`) |
| `test-full` | Everything, including full-data tests |
| `docker-build` / `docker-run` / `docker-test` | Build the image, run it on :8080, run container integration tests |
| `inspector` | Open the MCP Inspector against the stdio server |
| `data-tables` | Fetch every file in `data/manifest/tables.yaml` (sha256-pinned) and build `data/build/courts.duckdb`, Parquet, `docs/revision-log.md` |
| `data-discover` | Re-crawl uscourts.gov and rewrite the table manifest (review the diff) |
| `data` | All datasets (tables now; the IDB joins in P2) |
| `web` / `eval` | Placeholders until Phases 8 and 3 |

## Repository layout

```
src/courts_analyst/
├── app.py            # thin entry point: build_server() + transport choice
├── config.py         # typed settings (pydantic-settings) from env / .env
├── logging_config.py # JSON logs over HTTP, readable text locally; always stderr
├── models.py         # shared Pydantic models (tool outputs, provenance)
├── routes.py         # /health, /version
├── tools/            # one file per MCP tool, each with register(mcp)
├── resources/        # courts:// and ui:// resources
├── prompts/          # analyst prompts
├── core/             # pure domain logic, no MCP/HTTP imports (ADR 0002)
│   ├── courts.py     #   94 districts, 12 circuits, alias resolution
│   └── numbers.py    #   Excel-style rounding for published figures
├── pipeline/         # data ingestion (P2 adds the IDB)
│   └── tables/       #   official tables: discover, fetch, parse, load (ADR 0006)
├── api/              # FastAPI REST + agent SSE (P7)
└── agent/            # model adapters (P7)
tests/                # unit, golden, MCP protocol, transport, container tests
├── fixtures/tables/  # real uscourts.gov files (≈2 MB) so CI builds the catalog
└── golden/           # hand-verified official figures
web/                  # React frontend (P8)
eval/                 # benchmark and eval kits (P3, P10)
data/                 # committed manifest; gitignored downloads and DuckDB build
docs/adr/             # architecture decision records
deploy/               # template kits: Databricks Apps, IBM watsonx / Code Engine
plan/                 # phased build plan
```

## Configuration

Every setting is optional; see [`.env.example`](.env.example) and
[`config.py`](src/courts_analyst/config.py).

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` (a host-injected `PORT`/`DATABRICKS_APP_PORT` forces HTTP) |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | HTTP bind address |
| `DATA_DIR` | `data` | Downloads (`raw/`) and build outputs (`build/`) |
| `DUCKDB_PATH` | `$DATA_DIR/build/courts.duckdb` | Analytical store |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | unset | Agent and eval models (P7, P10) |
| `COURTLISTENER_API_TOKEN` | unset | CourtListener handoff (P7) |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `auto` | `auto` = JSON over HTTP, text on stdio |

## Adding a tool

Tools are thin adapters over `core/` (see [ADR 0002](docs/adr/0002-core-adapter-architecture.md)):

1. Put the logic in `core/` with unit tests.
2. Create `tools/<name>.py` with `register(mcp)`, returning a Pydantic model
   (FastMCP publishes it as the tool's `outputSchema`).
3. Call it from `tools/__init__.py` and add the name to `EXPECTED_TOOLS` in
   `tests/test_registration.py`.

## Deploying

The template's kits work unchanged with the renamed package. See
[deploy/README.md](deploy/README.md) for Databricks Apps and IBM watsonx
Orchestrate / Code Engine. The `Dockerfile` builds a locked, non-root image
serving `/mcp` on :8080.

## License

[MIT](LICENSE). See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy.
