# Phase 9: MCP App and Deployment

**Goal:** (1) results render as an inline, interactive chart with provenance badges inside MCP clients that support MCP Apps, with text/table fallback everywhere else; (2) the server is deployed through the template's kits so judges can use it from Databricks and watsonx Orchestrate.

**Judging impact:** Innovation (creative use of MCP tooling), technical quality (works across platforms), presentation (the inline chart moment in the demo).

## Part A: MCP App

- A separate Vite entry in `web/mcp-app/` that builds to a **single self-contained HTML bundle**, reusing `VintageChart`, `ContributorWaterfall`, comparison bars and `ProvenanceBadge` from the design system.
- Served as a `ui://` resource; tools that return chartable results (`explain_change`, `get_official_figure` with revisions, `compare_courts`) reference it in their result metadata per the MCP Apps extension.
- The chart spec is the same one the web app receives in `chart` SSE events: one spec, two renderers.
- **Fallback:** every chartable result also includes a Markdown table + one-sentence summary in its text content, so watsonx and Databricks (or any client without MCP Apps) still get a complete answer.
- Theme follows the host (light/dark) where the host exposes it.
- Bundle size budget (for example < 250 KB gzipped); no external network calls from inside the app.

## Part B: Deployment

| Target | Approach | Output |
| --- | --- | --- |
| Docker (base) | Template Dockerfile + multi-stage build: Node builds `web/`, Python image serves everything; DuckDB file baked in or mounted | One image |
| Databricks Apps | Template's Databricks kit; DuckDB file from a Unity Catalog volume or baked in; secrets via secret scope | Public-to-judges URL: web app + `/mcp` |
| Databricks tables | Load the same official tables + IDB subset into Unity Catalog Delta tables | Needed for the Genie baseline in P10 |
| IBM watsonx Orchestrate | Template's IBM kit (Code Engine build-from-Git or prebuilt image) | Toolkit registered in Orchestrate |
| IBM ContextForge | Register the server in the gateway **(stretch)** | Cross-platform credit |
| Claude Desktop / VS Code | Documented config for stdio and remote HTTP | README snippets |

## Tasks

- [ ] MCP App bundle build + `ui://` resource + result metadata wiring
- [ ] Text/table fallback generator shared by all chartable tools
- [ ] Multi-stage Dockerfile; image size and cold-start measured
- [ ] Databricks Apps deploy via kit; Unity Catalog tables for Genie
- [ ] watsonx Orchestrate deploy via kit; a working agent there using our tools
- [ ] Deploy runbook in `docs/deploy.md` (reproducible by a judge)
- [ ] Health checks, versioned `/version` endpoint showing DB build hash and data vintages

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_ui_resource.py` | MCP | `ui://` resource is listed, returns HTML, correct MIME type, under the size budget |
| `test_chart_metadata.py` | MCP | Chartable tool results reference the UI resource and include the chart spec |
| `test_text_fallback.py` | MCP | Every chartable result includes a Markdown table + summary that match the structured data |
| MCP App render test | Playwright | The bundle loaded in a harness page with a sample spec renders the chart and badges; axe passes |
| Container test | CI | Build image, start it, `/health`, `/version`, one MCP tool call, one `/api` call |
| Deploy smoke | manual + scripted | Databricks URL and watsonx agent answer three canned questions; results logged in `docs/deploy.md` |
| Client matrix | manual checklist | Claude Desktop, Claude Code, VS Code, ChatGPT (if MCP Apps supported), watsonx, Databricks: tool calls work, chart or fallback renders. Screenshots saved for the deck |

## Exit criteria

- [ ] Inline chart renders in at least one major client (Claude or VS Code), fallback confirmed in watsonx and Databricks
- [ ] Deployed on Databricks Apps; watsonx agent working
- [ ] Container test green in CI; runbook verified by someone who didn't write it
