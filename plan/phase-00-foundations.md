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
- [x] Create the repo from `GSA-TTS/mcp-hackathon-template` (already existed with the `template` remote); rename `example_server` → `courts_analyst` in the package, `pyproject.toml`, `manifest.yaml`, Dockerfile and deploy kits
- [x] Remove the template's example tools, keeping one `ping`/`server_info` tool so smoke tests still have something to call
- [x] Add the directories `core/`, `pipeline/`, `api/`, `agent/` under the package; add `web/`, `eval/`, `data/`, `docs/adr/` at the root
- [x] `.gitignore` for `data/raw`, `data/build`, `*.duckdb`, `.env`
- [x] `Makefile` (or `justfile`) with `setup`, `lint`, `typecheck`, `test`, `test-full`, `data`, `serve`, `web`, `eval`

### Tooling
- [x] `uv` dependency groups: `dev` (pytest, pytest-asyncio, pytest-cov, hypothesis, syrupy, mypy, ruff), `pipeline`, `api`, `eval`
- [x] ruff config (lint + format), mypy config (strict for `core/` and `models.py`)
- [x] pre-commit hooks: ruff, mypy on changed files, end-of-file, no large files (>5 MB)
- [x] `config.py`: typed settings (pydantic-settings) for `DATA_DIR`, `DUCKDB_PATH`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `COURTLISTENER_API_TOKEN`, `LOG_LEVEL`
- [x] Structured logging (JSON in HTTP mode, pretty locally)

### CI (GitHub Actions)
- [x] `ci.yml`: ruff, mypy, pytest + coverage on push/PR, uv cache
- [x] Coverage report as a PR comment or artifact (artifact + job summary; see Deviations)
- [x] Placeholder `web.yml` job (turned on in P8)
- [x] Placeholder `eval-nightly.yml` (turned on in P3/P10)

### FastMCP and spec spike (half a day, time-boxed)
Build a throwaway server to confirm what actually works, then record the answers in `docs/adr/0001-mcp-capabilities.md`:
- [x] Which FastMCP version the template pins, and whether we can upgrade (3.4.7 locked → upgraded to 4.0.10)
- [x] Does it support the 2026-07-28 spec: structured `outputSchema`, the new elicitation flow, resource annotations/caching hints, MCP Apps (`ui://` resources)?
- [x] Does the in-memory `Client` work for tests (tools, resources, prompts, elicitation handler)?
- [x] Do stdio and HTTP transports work from Claude Desktop/Code and MCP Inspector?
- [x] Record the fallback plan for anything unsupported

### ADRs
- [x] 0001 MCP capabilities matrix (from the spike)
- [x] 0002 Core/adapter architecture
- [x] 0003 DuckDB as the analytical store
- [x] 0004 Default edition policy (latest by default, first-published attached)
- [x] 0005 Frontend served from the Python container

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_import.py` | smoke | Package imports; `app` builds without network |
| `test_registration.py` | MCP | In-memory client lists the expected tools/resources/prompts (starts with `server_info`) |
| `test_config.py` | unit | Settings load from env; missing optional keys don't crash startup |
| `test_transport.py` | integration | HTTP mode starts on an ephemeral port; `/health` and `/version` return 200 |
| CI | pipeline | Lint + typecheck + tests run green on a clean clone |

## Exit criteria

- [x] `make setup && make test` passes on a clean clone on macOS (and on Python 3.11) and in CI ([PR #1](https://github.com/syedaun-techsur/federal-courts-analyst/pull/1): lint, test 3.11, test 3.12, docker all green)
- [x] Claude Code connects over stdio and calls `server_info` (Claude Desktop not yet tried by hand)
- [x] ADR 0001 written, with a yes/no for every MCP feature we plan to use
- [ ] Team items resolved, or a written plan with owners and dates (needs the team; see Open issues)

## Risks

- Template pins an older FastMCP → upgrade in a branch; if deploy kits break, keep the pin and use fallbacks listed in ADR 0001.

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| Pin FastMCP after the spike, possibly keep the template pin | Upgraded to **FastMCP 4.0.10** (`>=4.0.10,<5`) | It implements spec 2026-07-28 and still serves 2024-11-05…2025-11-25 clients. Details and fallbacks are in [ADR 0001](../docs/adr/0001-mcp-capabilities.md) |
| Python 3.12+ | Container and dev use 3.12; `requires-python >=3.11`; CI tests 3.11 and 3.12 | Databricks Apps and the cloud.gov buildpack are 3.11 hosts in the template's kits |
| Keep one `ping`/`server_info` tool | `server_info` only | Spec 2026-07-28 removed the protocol-level `ping`, so a tool with that name would only confuse. `server_info` also reports `data_status` so agents can check readiness |
| Elicitation: "does it support the new flow?" | Yes, but with **three** runtime paths (MRTR, legacy `ctx.elicit`, no handler) | Spec change; recorded in ADR 0001 and in the Phase 5 plan |
| Coverage as a PR comment or artifact | Artifact (`coverage.xml`, `htmlcov/`, `junit.xml`) + GitHub job summary | No third-party action or extra token permission needed; revisit if reviewers want inline comments |
| — | Added `tests/test_architecture.py` (core import ban, layout, requirements mirror, ADRs present) and `tests/test_docker.py` (runs against the built image) | Enforces ADR 0002 from day one; follows the working agreement's "use local Docker" rule |
| — | Subprocess coverage (`[tool.coverage.run] patch = ["subprocess"]`) | Measures `main()` and the HTTP routes in the real server processes the transport tests start |
| — | `.mcp.json` committed | Claude Code users get the server with no setup |
| — | Removed `utils.py` (template `fetch_json`/`paginate`) and runtime `httpx` | Unused now; P1 adds its own HTTP layer in `pipeline/` |
| — | Ruff reformatted `eval/databricks/agent_eval_offline.py` (whitespace only) | Upstream never ran the formatter on it, and our CI checks formatting |

## Evidence

**Automated tests (2026-09-26):** 31 passed (default suite) with 98.6% coverage, plus 5 passed against the Docker image (`make docker-test`). Lint, format, mypy and pre-commit are clean. A clean clone passes `make setup && make lint typecheck test`, and the suite also passes on Python 3.11.

| Suite | Tests | Covers |
| --- | --- | --- |
| `test_import.py` | 3 | Imports, semver, `build_server()` opens no sockets |
| `test_registration.py` | 8 | Tool/resource/prompt lists, stable order, descriptions + `outputSchema` + annotations on every tool, structured output, **legacy (2025-11-25) client**, `data_status` flips when the DuckDB file appears |
| `test_config.py` | 9 | Defaults with no env, env overrides, `.env` file, blank keys → unset, masked secrets, invalid transport rejected, JSON and text logging on stderr only |
| `test_transport.py` | 7 | HTTP subprocess `/health`, `/version`, MCP over HTTP and stdio in **both** protocol eras, injected `PORT` forces HTTP |
| `test_architecture.py` | 4 | `core/` has no adapter imports, layout, requirements mirror pyproject, ADRs 0001–0005 exist |
| `test_docker.py` (`-m docker`) | 5 | Image health, version + git SHA, MCP in both eras, JSON logs |

**Claude Code (stdio):** `claude -p … --mcp-config .mcp.json` called `server_info` and returned the full structured JSON.

**MCP Inspector v2.8.0:**
- CLI against `http://127.0.0.1:8000/mcp`: `tools/list` shows `outputSchema`, and `tools/call server_info` returns `structuredContent` with `isError: false`
- Web UI in Chrome (Claude in Chrome) over stdio: connected and negotiated **MCP 2025-11-25**. The Tools tab shows `server_info` with READ-ONLY and IDEMPOTENT badges. Execute Tool returned the result and a Structured Output panel. No console errors. Screenshot: [`docs/evidence/phase-00/inspector-server-info.jpg`](../docs/evidence/phase-00/inspector-server-info.jpg)
- Chrome: `/health` → `{"status":"healthy","service":"federal-courts-analyst"}` and `/version` → `{"service":…,"version":"0.1.0","git_sha":"unknown"}` (a local run has no SHA; the image bakes one in)

**Issues found and fixed during the phase:**
- Under `python -m courts_analyst.app` the startup log used logger `__main__`, which bypassed our JSON handler. The container log test caught it; the logger now has a fixed name.

## Open issues

1. ~~CI on GitHub not yet run~~: green on PR #1 and merged.
2. **Team items** (domain expert, what's public) need the team.
3. **Claude Desktop** stdio connection not tried by hand (Claude Code and Inspector work over stdio).
4. `~/.npm` has root-owned files, so `npx` fails with EACCES. We ran the Inspector with a scratch npm cache. Fix with `sudo chown -R 502:20 ~/.npm`, or `make inspector` will fail.
5. Inspector CLI quirk: `uv run --quiet …` is parsed as an Inspector flag. Use `uv run courts-analyst` (as `make inspector` does).
6. ADR 0004 (default edition policy) is **Proposed**. Confirm with the domain expert before P1.
