# Phase 0: Foundations

**Goal:** a repo built from the GSA template with tooling, CI and a test skeleton, and a verified FastMCP/spec capability matrix. (We're already registered for the competition, so there's no eligibility gate.)

**Judging impact:** Technical quality (clean repo, CI, modular layout from day one).

## Team items (non-code)

- [ ] Named court-statistics domain expert on the team
- [ ] Decide what's public: repo visibility, and whether the revision narrative can be shown before AO statistics staff review it

## Scope

**In:** repo scaffolding, tooling, CI, test harness skeleton, FastMCP/spec spike, ADRs for key decisions.
**Out:** any real data or tools.

## Tasks

### Repo
- [ ] Create the repo from `GSA-TTS/mcp-hackathon-template`; rename `example_server` → `courts_analyst` in the package, `pyproject.toml`, `manifest.yaml`, Dockerfile and deploy kits
- [ ] Remove the template's example tools, keeping one `ping`/`server_info` tool so smoke tests still have something to call
- [ ] Add the directories `core/`, `pipeline/`, `api/`, `agent/` under the package; add `web/`, `eval/`, `data/`, `docs/adr/` at the root
- [ ] `.gitignore` for `data/raw`, `data/build`, `*.duckdb`, `.env`
- [ ] `Makefile` (or `justfile`) with `setup`, `lint`, `typecheck`, `test`, `test-full`, `data`, `serve`, `web`, `eval`

### Tooling
- [ ] `uv` dependency groups: `dev` (pytest, pytest-asyncio, pytest-cov, hypothesis, syrupy, mypy, ruff), `pipeline`, `api`, `eval`
- [ ] ruff config (lint + format), mypy config (strict for `core/` and `models.py`)
- [ ] pre-commit hooks: ruff, mypy on changed files, end-of-file, no large files (>5 MB)
- [ ] `config.py`: typed settings (pydantic-settings) for `DATA_DIR`, `DUCKDB_PATH`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `COURTLISTENER_API_TOKEN`, `LOG_LEVEL`
- [ ] Structured logging (JSON in HTTP mode, pretty locally)

### CI (GitHub Actions)
- [ ] `ci.yml`: ruff, mypy, pytest + coverage on push/PR, uv cache
- [ ] Coverage report as a PR comment or artifact
- [ ] Placeholder `web.yml` job (turned on in P8)
- [ ] Placeholder `eval-nightly.yml` (turned on in P3/P10)

### FastMCP and spec spike (half a day, time-boxed)
Build a throwaway server to confirm what actually works, then record the answers in `docs/adr/0001-mcp-capabilities.md`:
- [ ] Which FastMCP version the template pins, and whether we can upgrade
- [ ] Does it support the 2026-07-28 spec: structured `outputSchema`, the new elicitation flow, resource annotations/caching hints, MCP Apps (`ui://` resources)?
- [ ] Does the in-memory `Client` work for tests (tools, resources, prompts, elicitation handler)?
- [ ] Do stdio and HTTP transports work from Claude Desktop/Code and MCP Inspector?
- [ ] Record the fallback plan for anything unsupported

### ADRs
- [ ] 0001 MCP capabilities matrix (from the spike)
- [ ] 0002 Core/adapter architecture
- [ ] 0003 DuckDB as the analytical store
- [ ] 0004 Default edition policy (latest by default, first-published attached)
- [ ] 0005 Frontend served from the Python container

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_import.py` | smoke | Package imports; `app` builds without network |
| `test_registration.py` | MCP | In-memory client lists the expected tools/resources/prompts (starts with `server_info`) |
| `test_config.py` | unit | Settings load from env; missing optional keys don't crash startup |
| `test_transport.py` | integration | HTTP mode starts on an ephemeral port; `/health` and `/version` return 200 |
| CI | pipeline | Lint + typecheck + tests run green on a clean clone |

## Exit criteria

- [ ] `make setup && make test` passes on a clean clone on macOS and in CI
- [ ] Claude Code/Desktop connects over stdio and calls `server_info`
- [ ] ADR 0001 written, with a yes/no for every MCP feature we plan to use
- [ ] Team items resolved, or a written plan with owners and dates

## Risks

- Template pins an older FastMCP → upgrade in a branch; if deploy kits break, keep the pin and use fallbacks listed in ADR 0001.
