# Phase 5: MCP Server

**Goal:** expose the core as a small set of goal-oriented MCP tools with precise descriptions, Pydantic inputs, declared output schemas, resources, prompts and elicitation, following the template's one-tool-per-file convention.

**Judging impact:** Technical quality (MCP design principles are named in the rubric) and innovation (cohort handles, elicitation, edition-locked cacheable resources).

## Tools (one file each under `tools/`)

| Tool | Input model (Pydantic) | Output | Notes |
| --- | --- | --- | --- |
| `explain_change` | `ExplainChangeInput(measure, court="national", period_from, period_to)` | `ToolResult[ChangeExplanation]` | Flagship |
| `get_official_figure` | `OfficialFigureInput(measure, court, fiscal_year, edition=None)` | `ToolResult[OfficialFigure]` | Returns all revisions |
| `compare_courts` | `CompareCourtsInput(metric, courts: list[Court] \| "all", fiscal_year, edition=None, top_n=None)` | `ToolResult[CourtComparison]` | Weighted metrics come from official tables only |
| `find_cases` | `CohortSpec` | `ToolResult[CohortSummary]` (handle, n, breakdown preview) | Never returns row-level party data |
| `analyze_cohort` | `AnalyzeCohortInput(handle, metric, group_by=None)` | `ToolResult[CohortAnalysis]` | CIs + n always |
| `reconcile` | `ReconcileInput(handle \| figure_ref)` | `ToolResult[Reconciliation]` | Badge + variance explanation |
| `judgeship_context` | `JudgeshipContextInput(court, fiscal_year=None)` | `ToolResult[JudgeshipContext]` | No own recommendations |
| `explain_term` | `ExplainTermInput(term)` | `ToolResult[TermDefinition]` | Fuzzy match with "did you mean" |
| `sample_dockets` | `SampleDocketsInput(handle, n≤10)` | `ToolResult[DocketRefs]` | Labeled "match may be inexact"; formatted for CourtListener lookup |

(That's 9 including the find/analyze pair; the concept counts them as 8.)

### Description standard (every tool)
Each description answers, in this order: **what question it answers**, **when to use it vs. the neighbouring tool**, **what it returns**, **one example**. Descriptions are tuned only against the eval `dev` split. Enum values (courts, measures, editions) come from the schema, so models can't invent them.

Example:
> Use `get_official_figure` when the user asks for a single published statistic (for example, weighted civil filings per judgeship for a district and fiscal year). Returns the figure from the latest edition by default, plus the first-published value and every later revision, each with its table and edition. For "why did X change", use `explain_change` instead.

### Annotations
- All tools: `readOnlyHint: true`, `openWorldHint: false` (except `sample_dockets`, which references external identifiers).
- Idempotent hints where true.

## Resources

| URI | Content | Cache hint |
| --- | --- | --- |
| `courts://catalog` | Table catalog (series, tables, editions, periods) | short |
| `courts://editions/{edition}/{table}` | A published table as normalized JSON | **immutable** (published editions never change) |
| `courts://revisions` | Revision log | short |
| `courts://codebook/{field}` | IDB code lists with validity ranges | long |
| `courts://methodology/{topic}` | Methodology notes (weighted filings, MDL, fiscal vs statistical year, reconciliation) | long |
| `courts://glossary` | Glossary | long |

## Prompts

- `district_caseload_profile(court, fiscal_year)`
- `what_changed_and_why(measure, period_from, period_to)`
- `judgeship_briefing(court)`: neutral, source-tagged summary
- `compare_editions(measure, fiscal_year)`

## Elicitation

Triggered when the input is ambiguous in ways that change the answer:
- raw vs weighted filings
- fiscal year vs statistical year (pre-1993) or a non-Sep-30 period
- "civil filings" including vs excluding directly filed MDL cases
- edition: "current official" vs "as first published" when a figure was revised

If the client supports elicitation: send a schema-constrained request (enum choices). If not (detected from client capabilities): return a structured `NeedsClarification` result with the same choices, which the agent can show to the user. Both paths share one `Clarification` model.

## Server plumbing

- `app.py` keeps the template's transport auto-selection; `tools/__init__.py` registers all tools.
- Consistent error model: typed errors (`UnknownCourt`, `OutOfScopePeriod`, `UnknownHandle`, `Declined`) mapped to MCP tool errors with helpful messages and `suggested_next`.
- Request logging with tool name, arguments hash, latency, result size (OpenTelemetry spans for Phoenix in P10).
- Output size budget: tool results stay under a fixed token budget; large results return a handle instead.

## Tasks

- [ ] Implement each tool file as a thin adapter: validate → call core → wrap `ToolResult`
- [ ] Declare output schemas from the Pydantic models
- [ ] Resources and prompts modules
- [ ] Elicitation + fallback
- [ ] Tool description review against the dev split (iterate, track tool-selection accuracy per revision)
- [ ] MCP Inspector walkthrough recorded for the deck
- [ ] Claude Desktop/Code config snippet in the README

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_tool_registry.py` | MCP | Exactly the expected tools, each with description, input and output schema, annotations |
| `test_tool_schemas.py` | MCP | Every tool's actual output validates against its declared `outputSchema` (run over fixtures) |
| `test_tools_happy_path.py` | MCP (in-memory client) | One call per tool on the fixture DB; snapshot the structured output |
| `test_tools_errors.py` | MCP | Unknown court, bad FY, unknown handle → helpful typed error, not a stack trace |
| `test_enum_constraints.py` | MCP | Invented court/edition names are rejected by the schema |
| `test_resources.py` | MCP | Resource list, templates resolve, immutable hints on edition resources |
| `test_prompts.py` | MCP | Prompts render with arguments |
| `test_elicitation.py` | MCP | With an elicitation handler: ambiguous input triggers a request and the chosen answer is honored. Without: `NeedsClarification` returned |
| `test_output_budget.py` | MCP | No tool output exceeds the size budget on the largest fixture queries |
| `test_description_lint.py` | unit | Each description has the four required parts and stays under a length limit |
| Tool-selection eval | eval (dev split) | ≥ 90% correct tool on dev with Claude before moving on |

## Exit criteria

- [ ] All tools callable from Claude Desktop/Code and MCP Inspector over stdio and HTTP
- [ ] Schema, protocol and snapshot tests green
- [ ] Tool-selection accuracy on dev ≥ 90% (Claude); first numbers for a second model family
- [ ] First eval e2e run with our server recorded as the baseline for P6–P10
