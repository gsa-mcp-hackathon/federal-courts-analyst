# Phase 4: Analytics Core

**Goal:** the pure-Python domain layer that every adapter (MCP, REST) calls. It owns provenance, measures, official-figure lookup, cohorts, `explain_change` decomposition and reconciliation. It has no MCP or HTTP imports.

**Judging impact:** Technical quality (modular, typed, heavily tested) and innovation (decomposition + reconciliation is what no other server does).

## Inputs from Phase 1

Phase 1 built the official tables catalog ([ADR 0006](../docs/adr/0006-official-tables-ingestion.md), [data-sources.md](../docs/data-sources.md)). Build on it rather than re-creating it:

- `core/courts.py` already is the court registry (94 districts, 12 circuits, `US`) with alias resolution; `enums.py` should re-export it, not redefine it.
- `pipeline/tables/measures.yaml` is the seed of the measures registry (37 measures with label, definition, unit, weighted flag, display decimals).
- DuckDB tables `observation`, `source_file`, `edition`, `footnote`, `measure_def`, `court`, the `revision` view and `revision_log` supply `get_official_figure`, `list_revisions` and `first_published`/`later_revisions`. Every observation has a `cell_ref`.
- `core/numbers.round_half_up` is the display rule (Excel-style); use it for every published figure.
- Moved here from P1: C-2/C-3 (civil filings by nature of suit, national and by district), FCMS district profiles (vacancies, median times, weighted filings), and Judicial Conference judgeship recommendations and judicial emergencies for `judgeships.py`. Add each as a table family (a few rules each) plus its measures.

## Inputs from Phase 2

Phase 2 built the civil IDB ([ADR 0007](../docs/adr/0007-idb-ingestion.md), [methodology](../docs/methodology/idb.md)):

- It lives in its own file, `settings.resolved_idb_path` (`data/build/idb.duckdb`). Attach it read-only next to `courts.duckdb`.
- **Pick the grain per measure:** filings and cohorts from `idb_civil` (one row per case); terminations, dispositions and time to disposition from `idb_civil_terminations` (every terminated record, which matches C-1 exactly). `idb_civil_record` is the base table.
- Fiscal years: `filing_fy`/`termination_fy` (AO dates) and `core.fiscal`. `nos_category`/`nos_group`/`nos_line` follow Table C-2, which makes C-2 reconciliation a join.
- Pending on a past date needs the rule in `pipeline/idb/profile.py` (`PENDING_AT`); move it into `measures.py`. FY2017 is 7.2% above C-1 because reopenings aren't dated (the `reopened-without-date` data break), so `reconcile` should explain that variance.
- `data_breaks` and `code_validity` tables feed the data-break warnings. Party names are not in the database and must never be.

## Module layout

```
core/
├── provenance.py     # Provenance, RevisionStatus, Edition, build helpers
├── enums.py          # Court, Measure, CaseType/NOSGroup, EditionId, PeriodType
├── measures.py       # measure registry: definition, unit, source preference, IDB formula
├── official.py       # get_official_figure(), list_revisions(), compare_courts()
├── cohorts.py        # CohortSpec, CohortStore (handles), analyze_cohort()
├── explain.py        # explain_change(): decomposition + driver detection
├── reconcile.py      # reconcile(): IDB-derived vs official, variance explanation
├── judgeships.py     # judgeship_context(): thresholds 430/600, emergencies, recommendations
├── glossary.py       # explain_term()
├── stats.py          # CIs (Wilson, bootstrap for medians), small-n flags
├── db.py             # DuckDB connection, read-only, parameterized queries only
└── results.py        # Result envelopes: data + provenance + warnings + suggested_next
```

## Shared models (the contract every tool returns)

```python
class Provenance(BaseModel):
    source: Literal["official_table", "idb_derived", "derived"]
    table_code: str | None           # "X-1A", "6.2"
    series: str | None               # "Judicial Business", "Judicial Facts and Figures"
    edition: EditionId | None        # "JB-2020", "JFF-2023"
    period: Period                   # fiscal_year, period_end, period_type
    definition: str                  # plain-language definition of the measure
    url: HttpUrl | None
    cell_ref: str | None
    revision_status: Literal["original", "revised", "only_edition"]
    first_published: FigureRef | None
    later_revisions: list[FigureRef]
    reconciliation: ReconciliationBadge | None   # matched / explained_variance / unexplained

class Warning(BaseModel):
    code: Literal["small_cell", "data_break", "revised_figure", "period_mismatch",
                  "inferred_not_official", "inexact_match", "out_of_scope"]
    message: str
    severity: Literal["info", "caution", "block"]

class ToolResult(BaseModel, Generic[T]):
    data: T
    provenance: list[Provenance]
    warnings: list[Warning]
    suggested_next: list[str]        # hints for the agent ("call explain_change for ...")
```

## Key algorithms

### `explain_change(measure, court, period_a, period_b)`
1. Compute total change Δ for the measure (official figure when available, IDB otherwise, tagged either way).
2. Decompose Δ by district × NOS group using IDB counts (additive for counts; for per-judgeship measures, a **shift-share** split into a filings effect and a judgeship effect).
3. Rank contributors; mark the top ones that explain ≥ 80% of Δ.
4. Run **driver detectors** over the contributors:
   - `mdl_direct_filed`: share of the contributor's filings with the MDL direct-filed flag
   - `pandemic_window`: periods overlapping Mar 2020–FY2021 notes
   - `methodology_revision`: the official figure changed across editions (from P1's revision log)
   - `data_break`: a codebook change inside the window
5. Return contributors, drivers (each with evidence and whether it's **official** or **inferred**), and provenance.

The 554 → 322 explanation is always labeled `inferred_not_official` until AO staff confirm it.

### Cohort handles
- `CohortSpec` (Pydantic): court(s), FY range, NOS groups, origin, jurisdiction, disposition, MDL flags.
- `CohortStore` saves the spec + row count + a SQL fingerprint and returns a short handle (`coh_7f3a…`). Handles are **deterministic** (hash of the normalized spec), so the same question yields the same handle across sessions and tests.
- Handles can be refined: `refine(handle, extra_filters) -> new handle` (keeps parent for lineage).
- Storage: an in-process LRU + a DuckDB table so handles survive restarts in HTTP mode.

### `reconcile(handle | figure)`
- Rebuild the official measure from IDB (for example filings by district/FY), compare with the matching official table cell.
- Classify variance: within tolerance, explained (known reasons: dedup timing, snapshot date, transfers, reopened cases, MDL counting rules) or unexplained.
- Returns a `ReconciliationBadge` used everywhere in the UI.
- Byproduct: `docs/variance-report.md` generated across all districts and years.

### `analyze_cohort(handle, metric)`
Metrics: count, trend by FY, median days to disposition (bootstrap CI), disposition/outcome rates (Wilson CI), share by NOS. Always returns `n`, CI, and small-cell warnings.

## Tasks

- [x] Enums and shared models in `core/` (`enums.py`, `provenance.py`, `results.py`); JSON schema export for the frontend (`make schemas` → `web/src/api/schemas/`, checked current by a test)
- [x] Measures registry (YAML + loader), including which source is authoritative per measure (`core/data/measures.yaml`: official tables for every measure; `idb` rule for the three C-1 counts)
- [x] `official.py` with default-edition policy (latest, with first-published attached)
- [x] Cohort spec/store/handles + `analyze_cohort`
- [x] `explain.py` with decomposition and four driver detectors (plus `mdl_cases` for terminations/pending and `judgeship_change`)
- [x] `reconcile.py` + variance report generator (`make variance-report`)
- [x] `judgeships.py` (thresholds as data, not constants in code; each tagged with its CRS/Judicial Conference source; plus the Conference's 2025 recommendations)
- [x] `glossary.py` from a YAML glossary (NOS codes, weighted filings, directly filed MDL, fiscal vs statistical year…); domain expert review is [#5](https://github.com/syedaun-techsur/federal-courts-analyst/issues/5)
- [x] All SQL parameterized; DuckDB opened read-only by the core (and external file access disabled)

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_provenance.py` | unit | Every result factory fills required provenance fields; revised figures always carry `first_published` |
| `test_official_default_edition.py` | golden | FY2020 weighted → 322 (JFF-2023) by default, `first_published` = 554 (JB-2020); `edition="JB-2020"` returns 554 |
| `test_decomposition_additivity.py` | property (hypothesis) | For random count tables, contributors sum exactly to Δ; shift-share effects sum to Δ |
| `test_explain_fy2020.py` | integration (fixture) | FY2019→FY2020 civil filings: N.D. Fla. is the top contributor; `mdl_direct_filed` driver fires; label is official for counts, inferred for the weighted revision |
| `test_cohort_handles.py` | unit | Same spec → same handle; refine keeps lineage; unknown handle → typed error |
| `test_analyze_cohort_stats.py` | unit | Wilson and bootstrap CIs on known data; small-n warning at the threshold boundary |
| `test_reconcile.py` | integration | Fixture district/FY within tolerance → `matched`; engineered mismatch → `unexplained`; known dedup case → `explained` |
| `test_judgeship_context.py` | unit | Thresholds and emergency flags come from data with source tags; never produces a recommendation of its own |
| `test_sql_safety.py` | unit | No string-formatted SQL in `core/` (AST lint test); connection is read-only |
| `test_core_isolation.py` | unit | `core/` imports nothing from `fastmcp`, `fastapi`, `anthropic`, `openai` |

**Coverage gate:** ≥ 90% for `core/`.

## Exit criteria

- [x] All eval **engine** questions from P3 pass at the defined tolerance, or have a documented explained variance (30/30 pass)
- [x] `explain_change` produces the FY2020 storyline on full data
- [x] Variance report generated ([docs/variance-report.md](../docs/variance-report.md))
- [x] mypy strict clean on `core/`

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| `models.py` holds the shared models; `enums.py` re-exports courts | Models in `core/provenance.py` and `core/results.py`; `enums.py` builds closed vocabularies (courts, measures, editions, codebook groups) as `str` + JSON Schema `enum` | The core owns its contract (ADR 0002); an `enum` schema lets MCP clients list every allowed value without Python enums for 107 courts |
| `Warning` model | `Caveat` class, published under the schema title `Warning` | `Warning` shadows a Python builtin |
| `ToolResult[T]` with data, provenance, warnings, suggested_next | `Result[T]` adds `status` (`ok` / `needs_clarification`) and `clarification` | Phase 5's elicitation fallback returns the same envelope instead of a second type |
| Measures registry as a new YAML | Moved `pipeline/tables/measures.yaml` to `core/data/measures.yaml` and added `tables` and `idb`; the pipeline reads it from there | One file defines each measure for both the catalog and the server |
| Pending rule "move into `measures.py`" | `PENDING_WHERE` in `core/measures.py`, parameterized; `pipeline/idb/profile.py` uses it | Same rule everywhere, no formatted SQL |
| Bootstrap CI for medians | Distribution-free order-statistic interval (exact binomial ranks n ≤ 200) with a coverage simulation test | Exact, reproducible, and two quantile lookups instead of thousands of resamples |
| Decompose "by district × NOS group" | Three breakdowns (district, case type, and the pair), each summing exactly to the IDB change, plus the change excluding directly filed MDL cases | The single cross-product is hard to read; separate lists answer "where" and "what kind" directly |
| Per-judgeship decomposition | Shift-share on the **first-published** X-1A series with district rows; revised national values reported separately with a `revised_figure` warning | Only Judicial Business prints district rows; mixing its districts with a revised JFF national figure would mix series |
| `methodology_revision` detector | Two drivers: the official revision (`official`) and, when the evidence supports it, the district inference (`inferred`, gated: ≥ 50% of the revision and a majority-MDL district) | The first version also "explained" FY2019 by C.D. Cal. (25 of 49 points); the gate keeps inference to cases the data supports |
| — | `judgeship_change` and `mdl_cases` (terminations, pending) drivers | Needed for the FY2024 terminations and pending stories |
| `reconcile`: dedup timing, snapshot date, transfers, reopened cases, MDL counting | Four quantified causes: restated edition, repeat records, undated reopenings, snapshot drift; tolerances fixed before the report ran | Only causes we can measure count as "explained"; the rest are reported as unexplained |
| — | Compare pending counts with the **latest** edition | The AO restates the prior year's closing pending count; this resolves [#11](https://github.com/syedaun-techsur/federal-courts-analyst/issues/11) |
| `judgeship_context`: thresholds, emergencies, recommendations | Thresholds (430, 600) and the Conference's **2025** recommendations (69 district judgeships, 25 districts; PDF sha256-pinned). No emergency status | Emergencies depend on current vacancies, which we don't hold; claiming one would be wrong |
| Inputs from P1: add C-2/C-3 and FCMS as table families | Not added; the IDB's nature-of-suit hierarchy (checked against C-2 in Phase 2) serves the case-type breakdowns | The core didn't need them for any P4 exit criterion; they stay open in [#9](https://github.com/syedaun-techsur/federal-courts-analyst/issues/9) |
| — | `EngineAnswerer` (`courts-eval run --answerer engine`) | Makes the engine exit criterion a repeatable eval run |
| — | Glossary claim "tables use fiscal years from 1992" dropped, with the matching eval claim | Not verified against a source |
