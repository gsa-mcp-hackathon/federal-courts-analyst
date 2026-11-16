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

> **P0 spike finding ([ADR 0001](../docs/adr/0001-mcp-capabilities.md)):** FastMCP 4 supports only server-wide cache hints (`FastMCP(cache_ttl=…, cache_scope=…)`), not a TTL per resource. Plan: one conservative server-wide TTL, with edition dates in the resource content. The per-resource column above is the ideal if FastMCP adds it.

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

> **P0 spike finding ([ADR 0001](../docs/adr/0001-mcp-capabilities.md)):** spec 2026-07-28 replaced server-initiated elicitation with multi round-trip requests (MRTR). "Supports elicitation" therefore has **two** paths: modern clients get an `InputRequiredResult` (read the answer from `ctx.input_responses` on the retry), and 2025-11-25 clients get `ctx.elicit()`. Each fails on the other era. One helper picks the path per request, and every elicited choice is also an ordinary tool argument. `test_elicitation.py` must cover modern, legacy and no-handler clients.

## Server plumbing

- `app.py` keeps the template's transport auto-selection; `tools/__init__.py` registers all tools.
- Consistent error model: typed errors (`UnknownCourt`, `OutOfScopePeriod`, `UnknownHandle`, `Declined`) mapped to MCP tool errors with helpful messages and `suggested_next`.
- Request logging with tool name, arguments hash, latency, result size (OpenTelemetry spans for Phoenix in P10).
- Output size budget: tool results stay under a fixed token budget; large results return a handle instead.

## Tasks

- [x] Implement each tool file as a thin adapter: validate → call core → return its `Result`
- [x] Declare output schemas from the Pydantic models
- [x] Resources and prompts modules
- [x] Elicitation + fallback (MRTR, legacy `ctx.elicit`, structured `needs_clarification`)
- [x] Tool description review against the dev split (two revisions, tracked in Evidence)
- [x] MCP Inspector walkthrough recorded for the deck
- [x] Claude Desktop/Code config snippet in the README

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

- [x] All tools callable from Claude Code and MCP Inspector over stdio, and over HTTP in-process and in the container (Claude Desktop by hand is still [#13](https://github.com/syedaun-techsur/federal-courts-analyst/issues/13))
- [x] Schema, protocol and snapshot tests green
- [x] Tool-selection accuracy on dev ≥ 90% (Claude): 16/16 Sonnet, 16/16 Haiku; a second model *family* needs an API key ([#18](https://github.com/syedaun-techsur/federal-courts-analyst/issues/18))
- [x] First eval e2e run with our server recorded as the baseline for P6–P10

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| Tool inputs as one Pydantic model each (`OfficialFigureInput`, …) | Flat, typed arguments (`Annotated[...]`), validated by the core's models and closed vocabularies ([ADR 0009](../docs/adr/0009-mcp-tool-surface.md)) | A single nested `input` object is harder for models to fill; the schema is the same set of constraints |
| `court="national"` | `court="US"` (the registry's code), with every code in the schema's `enum` | One vocabulary across tools, tables and the IDB |
| `reconcile(handle \| figure_ref)` | `reconcile(measure, court, fiscal_year)` or `reconcile(handle)` | Plain arguments are easier to fill than a union type |
| `find_cases` + separate refine | `find_cases(parent_handle=…)` refines | One tool for "narrow this cohort" keeps the surface at nine tools |
| Elicitation triggers: raw vs weighted, fiscal vs statistical year, MDL in/out, edition | Only **ambiguous measure aliases** (`filings_per_judgeship`, `civil_filings`) ask. Statistical year and edition apply the default with a warning; MDL in/out is always answered both ways by `explain_change` | Asking about soft ambiguities blocks headless agents for no gain; the result already carries both answers |
| Per-resource cache hints | One server-wide TTL (1 h) and `_meta.immutable` on edition resources | FastMCP 4 has server-wide hints only (ADR 0001) |
| — | `revision_notes` on `get_official_figure` (official history + gated inference), via new `core/revisions.py` | The concept promises the reason editions differ with the figure; the first baseline showed the model couldn't find it without calling `explain_change` |
| — | `core/catalog.py` (catalog, published tables, revision log) and `core/dockets.py` (sampling, CourtListener ids and links) | The resources and `sample_dockets` need core functions, not SQL in adapters |
| Tool-selection eval with Claude (API) | `claude-code` answerers: headless Claude Code (`claude -p`, built-in tools off, only this server) | No API keys ([#18](https://github.com/syedaun-techsur/federal-courts-analyst/issues/18)); the CLI gives the same tool-calling transcript |
| — | `courts-eval rescore`, `--workers`; behaviour scorer rewritten (strong vs weak refusal phrases, "answered" when the expected figures are present, sentence-scoped edition pairing) | The first baseline's behaviour scores were mostly scorer errors; saved transcripts are re-scored instead of re-asking the model |
| — | Request-logging middleware (tool, argument hash, latency, bytes, status) | Plan's "request logging"; OpenTelemetry waits for Phase 10 |

**Changes made after looking at eval results** (held-out policy, eval/README.md):

- *Harness* (scorer, bank): refusal and clarification phrases, sentence-scoped edition pairing, "answered" shortcut; bank fixes to `ts-cohort-trend` (`analyze_cohort` optional: `find_cases` already returns counts by year), the prompt-injection claim ("Neither figure is 900" had tripped `not_mentions: "is 900"`), and `what-changed-weighted-2023-edition` ("dropped" now counts as revised down). All are general rules or corrections of wrong checks; every scorer rule has a unit test drawn from a real transcript.
- *System*: descriptions now say a plain "civil filings" means the count (from dev item `why-fy2025-filings-changed`, which passed the alias and got a clarification back) and to name the edition and flag revisions even when asked for one number (dev item `adv-one-number-please`); `revision_notes` implement the concept's principle above. No change was made to fit a held-out item's wording.

## Evidence

**Surface:** 10 tools (9 analysis + `server_info`), 3 resources + 3 resource templates, 4 prompts. Every tool has an `outputSchema`, read-only annotations and a four-part description (≤ 1,200 characters, linted).

**Eval baseline (Claude Sonnet via headless Claude Code, only this server; full data; 2026-09-26):**

| Suite | Run 1 (as scored then) | Run 1, re-scored | **Run 2 (baseline)** | Held-out (test) in run 2 |
| --- | ---: | ---: | ---: | ---: |
| Tool selection | 24/25 | 25/25 | **25/25 (100%)** | 9/9 |
| End-to-end factual | 50/51 | 51/51 | **51/51 (100%)** | 13/13 |
| Explanation | 18/20 | 18/20 | **20/20 (100%)** | 6/6 |
| Adversarial | 12/26 | 23/26 | **22/26 (85%)** | 12/13 |
| **All four** | 104/122 | 117/122 | **118/122 (96.7%)** | 40/41 |

Claude Haiku, tool selection: **24/25** (dev 16/16). Latency p50 5–9 s, p95 6–16 s per question (the model's whole turn, not the tools'). Adversarial behaviour in run 2: decline precision 100% / recall 88%. The four remaining misses are Phase 6 inputs ([#22](https://github.com/syedaun-techsur/federal-courts-analyst/issues/22)). Runs are in [eval/results/](../eval/results/README.md).

**Tool calls on the full data** (in-memory client): `get_official_figure` FY2020 weighted → 322 (JFF-2025) with `revision_notes`: *554 (JB-2020 to JFF-2022) → 322 (JFF-2023 to JFF-2025)* and the inferred N.D. Fla. note (211 of 232 points); `explain_change` FY2019→FY2020 filings → +172,704, N.D. Fla. +199,881; `compare_courts` FY2024 top 5 → N.D. Fla., E.D.N.C., E.D. Cal., E.D. Tex., W.D. Tex.; `find_cases` N.D. Fla. FY2020 direct-filed MDL → 202,463 (`coh_1385a2b1481d`).

**CI:** green on [PR #23](https://github.com/syedaun-techsur/federal-courts-analyst/pull/23) (lint, test 3.11, test 3.12, docker).

**Automated tests:** 716 passed in the default suite (83 new for this phase), `@fulldata` 14/14. `make docker-test` 6/6: the container answers `get_official_figure`, `find_cases` and `analyze_cohort` over streamable HTTP with the data mounted read-only. Lint, format and mypy clean.

| Suite | Checks |
| --- | --- |
| `test_registration.py` | exactly the 10 tools in a fixed order, resources, templates, prompts; description, schema and annotations on every tool; `openWorldHint` only on `sample_dockets`; legacy clients |
| `test_tools_happy_path.py` | one call per tool on the fixture data, validated against its `outputSchema` (jsonschema) and snapshotted; the find → analyze → sample → refine → reconcile chain; circuit expansion; a legacy client calling a data tool |
| `test_tools_errors.py` | 15 bad inputs → typed, actionable errors (unknown court, bad year, out of scope, territorial, wrong edition, unknown or malformed handle, n > 10, bad cohort, unsupported measure); missing catalog and missing IDB |
| `test_enum_constraints.py` | the schema lists every court, measure and edition; invented values rejected |
| `test_elicitation.py` | modern (MRTR) and legacy (`ctx.elicit`) handlers: the choice is honoured; declined → `needs_clarification`; no handler → structured choices, and the choice works as an argument; the other tools ask too |
| `test_resources.py` | catalog, revisions, glossary, edition tables (value + cell ref, immutable `_meta`), codebook, methodology; unknown table/field/topic errors |
| `test_prompts.py` | all four render with their arguments and the reporting rules |
| `test_output_budget.py` | the largest results (all districts, national explanations, 11-year cohorts, grouped analyses) stay under 64 KB |
| `test_description_lint.py` | four parts in order, a named neighbour, ≤ 1,200 characters |
| `test_scorer_refusal.py` (extended) | refusal/clarification phrases from real Phase 5 transcripts |

**Claude in Chrome (MCP Inspector v2.8.0 web UI, stdio, 2025-11-25):** connected; the Tools tab lists all ten tools with their titles and READ-ONLY / IDEMPOTENT badges; `explain_change` (civil_cases_filed, US, 2019→2020) returned the structured result with the official change, IDB breakdown and drivers ([screenshot](../docs/evidence/phase-05/inspector-explain-change.jpg)); Resources lists the 3 URIs and 3 templates, and `courts://methodology/weighted-filings` renders as Markdown with its audience and priority annotations ([screenshot](../docs/evidence/phase-05/inspector-methodology-resource.jpg)). No console errors. The Inspector needed the scratch npm cache again ([#14](https://github.com/syedaun-techsur/federal-courts-analyst/issues/14)).

**Found and fixed during the phase:**
- `Result[T]` built with an unbound type variable made Pydantic warn on every serialisation; results are now parametrised by their data type.
- The legacy and modern elicitation paths return answers in different shapes (`{"value": …}` vs our form's `choice`); both are handled.
- The first Claude run's adversarial score (12/26) was mostly the scorer: refusals like "it can't provide names" or "isn't published for FY1992" weren't recognised, and correct answers to injection attempts were read as refusals. Rewritten and re-scored from the saved transcripts (23/26).
- Court abbreviations ("Ga., M.D. Ga.") split sentences and broke edition pairing for a correct circuit answer.

## Open issues

Live status is on the [issue tracker](https://github.com/syedaun-techsur/federal-courts-analyst/issues).

1. **Adversarial misses for Phase 6** (policy framing, dropped revision flag, ambiguous "how busy", improvised period facts). [#22](https://github.com/syedaun-techsur/federal-courts-analyst/issues/22)
2. **Second model family** for tool selection needs an API key. [#18](https://github.com/syedaun-techsur/federal-courts-analyst/issues/18) (comment added)
3. **Claude Desktop** not tried by hand (Claude Code, the Inspector and headless Claude Code all work). [#13](https://github.com/syedaun-techsur/federal-courts-analyst/issues/13)
4. `~/.npm` permissions for `make inspector`. [#14](https://github.com/syedaun-techsur/federal-courts-analyst/issues/14) (comment added)
5. Cohort handles live in one process unless `COHORT_STORE_PATH` is set; with several HTTP replicas an agent may have to call `find_cases` again (handles are deterministic, so it gets the same one). Note only.
