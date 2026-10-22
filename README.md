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
- The request desk, a sandboxed write workflow (proposed, Phase 9b): [`docs/desk.md`](docs/desk.md)

Built on the [GSA MCP hackathon template](https://github.com/GSA-TTS/mcp-hackathon-template)
with [FastMCP 4](https://gofastmcp.com) (MCP spec 2026-07-28, backward compatible
with 2025-11-25 clients) and [uv](https://docs.astral.sh/uv/).

> **Status: Phase 6 (guardrails and security).** Nine analysis tools plus
> `server_info`, six resources and four prompts over an edition-aware catalog
> of the official tables (FY2016–FY2025, 60 table editions) and the FJC civil
> IDB (FY2015–FY2025). One guardrail layer covers every tool: small-cell and
> complementary suppression, never-mix-vintages series, factual answers for
> periods not held, structured declines for judge-level and party-name
> requests, and an output scanner for party names. The HTTP endpoint and
> container are hardened ([SECURITY.md](SECURITY.md)). An eval benchmark of
> 173 questions scores every answer deterministically. Over HTTP the same
> process serves a REST API (same envelopes as the tools) and an agent that
> streams answers as typed server-sent events (`POST /api/ask`), with
> CourtListener docket lookups ([ADR 0011](docs/adr/0011-agent-and-api.md)).
> A web app at `/` shows every figure with its edition and table, the
> editions side by side, a district map, court profiles and the agent
> ([ADR 0012](docs/adr/0012-web-app.md), [web/README.md](web/README.md)).

## Tools

| Tool | Answers |
| --- | --- |
| `explain_change` | Why a measure changed between two fiscal years: exact breakdowns by district and case type, drivers labelled official / IDB-derived / inferred |
| `get_official_figure` | One published statistic in the latest edition, with the first-published value, every edition and why they differ |
| `compare_courts` | Courts ranked on one measure, all from one edition |
| `find_cases` / `analyze_cohort` | A cohort of IDB civil cases by handle; medians, outcome rates and trends with n and 95% CIs |
| `reconcile` | Whether the IDB reproduces a published count, and why not |
| `judgeship_context` | Weighted filings against the Judicial Conference's 430/600 thresholds and its 2025 recommendations (never its own) |
| `explain_term` | Definitions of terms, measures and nature-of-suit codes |
| `sample_dockets` | Example docket references for CourtListener, labelled "match may be inexact" |
| `server_info` | Version, protocols and which datasets are loaded |

**Request desk (sandbox, [docs/desk.md](docs/desk.md)).** A question never
writes anything. When a user wants an answer kept, these write to a separate
sandbox store; the official data stays read-only and the agent is never
offered them.

| Tool | Does |
| --- | --- |
| `keep_answer` | One call for what the web app's button does: check the answer, then save it as a verified copy, a watch, or a question to the statistics office |
| `my_requests` | The asker's inbox: status, verified answer, the office's response, updates |
| `check_inquiry_eligibility` | Whether a figure's revision can go to the statistics office (read-only) |
| `find_published_answers` | Search approved answers in the public library (read-only) |
| `open_request`, `save_verified_answer`, `file_revision_inquiry` | The same steps one at a time |
| `inquiry_queue`, `record_official_response`, `publish_answer` | The simulated statistics office; registered only with `DESK_STAFF_MODE=true` |

Plus the `desk://library` resource and the `keep_this_answer` prompt. Any MCP
client gets the full desk; the web app is one client of the same functions,
and a demo account's name (`asker_name="Priya"`) is the same person in both.

Resources: `courts://catalog`, `courts://revisions`, `courts://glossary`,
`courts://editions/{edition}/{table}` (immutable), `courts://codebook/{field}`,
`courts://methodology/{topic}`. Prompts: `district_caseload_profile`,
`what_changed_and_why`, `judgeship_briefing`, `compare_editions`. An ambiguous
question (raw or weighted filings?) is asked back through elicitation on
clients that support it, and returned as `needs_clarification` otherwise.

---

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and `make`. Docker is optional.

```bash
make setup        # install dev + pipeline deps, pre-commit hooks, create .env
make test         # pytest with coverage (builds both datasets from committed fixtures)
make data-tables  # download the official tables (≈4 min, polite) and build courts.duckdb
make data-idb     # download the FJC civil IDB (330 MB) and build idb.duckdb (≈1.5 min)
make serve        # MCP over stdio (what Claude Desktop/Code launch)
make serve-http   # MCP over streamable HTTP on :8000 (/mcp, /health, /version)
make help         # every target
```

Connect Claude Code: the repo ships a project `.mcp.json`, so opening Claude Code
in this directory offers the `courts-analyst` server. For Claude Desktop or
another directory, add:

```json
{
  "mcpServers": {
    "courts-analyst": {
      "command": "uv",
      "args": ["run", "--quiet", "--directory", "/absolute/path/to/this/repo", "courts-analyst"]
    }
  }
}
```

More in [QUICKSTART.md](QUICKSTART.md).

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
| `data-idb` | Fetch the pinned civil IDB release (resumable) and build `data/build/idb.duckdb` and `docs/data-profile.md`; party names go to `data/private/` |
| `data-idb-sample` | Rebuild the committed IDB test sample from the download |
| `data-discover` | Re-crawl uscourts.gov and rewrite the table manifest (review the diff) |
| `data` | Both datasets (`data-tables` + `data-idb`) |
| `eval-validate` / `eval` | Validate the question bank / harness self-check (gold 100%, null 0%) |
| `eval-claude` | The 20-question smoke set with Claude (headless Claude Code + this server) |
| `variance-report` | Reconcile every court-year into `docs/variance-report.md` |
| `schemas` | Export result JSON Schemas for the frontend |
| `desk-seed` / `desk-check` / `desk-reset` | Request desk: demo opening state / flag answers a newer edition revised / empty the sandbox |
| `eval-write-safety` | The desk's write-safety suite → `eval/results/write-safety.md` |
| `web` | Placeholder until Phase 8 |

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
├── pipeline/         # data ingestion: tables/ (P1), idb/ (P2)
│   └── tables/       #   official tables: discover, fetch, parse, load (ADR 0006)
├── api/              # FastAPI REST + agent SSE at /api (ADR 0011)
└── agent/            # agent loop, model providers, CourtListener wrappers
tests/                # unit, golden, MCP protocol, transport, container tests
├── fixtures/tables/  # real uscourts.gov files (≈2 MB) so CI builds the catalog
└── golden/           # hand-verified official figures
web/                  # React web app served at / (ADR 0012)
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
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | unset | Agent and eval models |
| `AGENT_MODEL` | `anthropic:claude-sonnet-5` | Model behind `/api/ask` (`openai:<model>` also works) |
| `COURTLISTENER_API_TOKEN` / `AGENT_COURTLISTENER` | unset / `auto` | Live CourtListener lookups (else a labelled synthetic fixture) |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `auto` | `auto` = JSON over HTTP, text on stdio |
| `DESK_STORE_PATH` | unset (in memory) | Request desk sandbox store (writable, outside `data/build`) |
| `DESK_STAFF_TOKEN` | unset (staff side off) | Token for the simulated statistics office's screen and routes |
| `DESK_STAFF_MODE` | `false` | Also register the two staff tools on MCP |

## HTTP API

`make serve-http` serves everything on one port: MCP at `/mcp`, the REST
explorer and agent at `/api` (schema at `/api/openapi.json`), `/health`.

| Endpoint | Same as |
| --- | --- |
| `GET /api/figures?measure&fiscal_year&court&edition` | `get_official_figure` |
| `GET /api/figures/{measure}/{court}/series?from&to` | never-mix-vintages series |
| `GET /api/compare?measure&fiscal_year&courts&top_n` | `compare_courts` |
| `GET /api/explain-change?measure&court&from&to` | `explain_change` |
| `GET /api/courts`, `/api/courts/{court}/profile` | court registry, `judgeship_context` |
| `GET /api/revisions`, `/api/eval/runs[/{id}]` | revision log, committed eval runs |
| `POST /api/ask` → SSE | the agent (`turn_start` … `turn_end`; schema in `web/src/api/schemas/agent-event.schema.json`) |
| `POST /api/ask/{turn_id}/clarify` | answers a `clarify` event; the stream resumes |
| `/api/desk/...` | the request desk (options, My requests, library, staff side): see [docs/desk.md](docs/desk.md) |

```bash
make serve-http PORT=8000
make ask Q="Why did weighted civil filings per judgeship change in FY2020?"
```

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

## Issues and phase tracking

The build runs in phases ([plan/](plan/README.md)). Each phase file records what was built, the evidence, deviations and open issues. Open issues are filed on the [GitHub issue tracker](https://github.com/syedaun-techsur/federal-courts-analyst/issues), labelled by phase (`phase N`) and by what they need (`needs domain expert`, `needs team`, `data`, `dev environment`, `stretch`). When a phase finishes, Claude files its open issues there, and it updates or closes them as later work resolves them.

## License

[MIT](LICENSE). See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy.
