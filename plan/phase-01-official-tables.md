# Phase 1: Official Tables Catalog (edition-aware)

**Goal:** scrape, parse and normalize the official uscourts.gov caseload tables into DuckDB. Every value knows its table, edition, reporting period and definition, and we can list every published revision of the same figure.

**Judging impact:** Innovation (edition tracking is the core differentiator) and technical quality (reproducible pipeline). Also the ground truth for reconciliation and eval.

## Scope

**In (civil-first, FY2015–FY2025, all editions that report those years):**

| Series | Tables | Why |
| --- | --- | --- |
| Judicial Business (Sep 30) | C-1, C-2, C-3, C-5, X-1A, and related | Annual first-published figures; X-1A has weighted filings per judgeship |
| Judicial Facts and Figures | 6.1–6.x (district tables incl. 6.2) | Multi-year series, revised in later editions (the 554 → 322 story) |
| Federal Court Management Statistics (FCMS) | District profiles | Per-district weighted filings per judgeship, vacancies, median times |
| Statistical Tables for the Federal Judiciary / FJCS | C-series (Jun 30, Dec 31, Mar 31) | **(stretch)** Non-fiscal-year periods for period-mismatch traps |
| Judgeship data | Authorized judgeships by district and year; Judicial Conference recommendations; emergencies | For `judgeship_context` |

**Out:** criminal, bankruptcy and appellate tables (stretch, after P10).

## Data model

```
source_file   (file_id, url, sha256, fetched_at, series, table_code, edition, period_end, format)
table_def     (table_code, series, title, description, notes)
measure_def   (measure_id, label, definition, unit, weighted: bool, denominator)
observation   (obs_id, file_id, measure_id, court, fiscal_year, period_end, value, footnote_ids[], cell_ref)
footnote      (footnote_id, file_id, text)
revision      (measure_id, court, fiscal_year, edition, value, prior_value, delta, first_published: bool)  -- derived view
```

- `edition` = the publication (for example `JB-2020`, `JFF-2023`), not the data year.
- `cell_ref` stores the sheet/row/column or PDF page and bbox, so every number links to exactly where it came from.
- `revision` is a **view** built from `observation` grouped by (measure, court, fiscal_year) across editions.

## Tasks

### Discovery
- [ ] Crawl the caseload statistics data-tables index; build `data/manifest/tables.yaml` listing each series, table code, edition, period and URL
- [ ] Write down URL patterns (for example `jb_x1a_0930.2020.pdf`, `jff_6.2_0930.2023.pdf`) and which editions have xlsx versus only PDF
- [ ] Map court names/codes to a canonical `Court` enum (94 districts + national totals; circuits). Handle aliases ("Florida, Northern", "FL-N", "N.D. Fla.")

### Fetch
- [ ] `pipeline/tables/fetch.py`: polite fetcher (rate limit, retries, user agent, `If-Modified-Since`), stores raw files under `data/raw/tables/` with sha256
- [ ] Idempotent: re-running skips files that haven't changed; a changed sha on a "published" edition raises an alert (editions shouldn't change)

### Parse
- [ ] Table-specific parsers under `pipeline/tables/parsers/` (one module per table family), each returning typed `Observation` rows
- [ ] xlsx first (calamine/openpyxl). PDF fallback with pdfplumber for editions without xlsx
- [ ] Capture footnotes and attach them to observations
- [ ] Detect and handle header drift between editions (renamed columns, merged cells, "—" and "NA" markers)

### Load and derive
- [ ] Load into DuckDB (`data/build/courts.duckdb`) + write Parquet copies
- [ ] Build the `revision` view and a `revision_log` table (measure, court, FY, editions, values, delta)
- [ ] Generate `docs/revision-log.md` automatically (reused as an MCP resource in P5)
- [ ] Measure definitions in `pipeline/tables/measures.yaml`, written with the domain expert

### Golden figures
- [ ] `tests/golden/official_figures.yaml` holds hand-verified values with their source URL and cell. At minimum:

| Measure | FY | Court | Edition | Value |
| --- | --- | --- | --- | --- |
| Judgeships | 2020 | National | JB-2020 X-1A | 673 |
| Civil filings per judgeship (unweighted) | 2020 | National | JB-2020 X-1A | 676 |
| Weighted civil filings per judgeship | 2020 | National | JB-2020 X-1A | 554 |
| Judgeships | 2020 | National | JFF-2023 6.2 | 674 |
| Civil filings per judgeship (unweighted) | 2020 | National | JFF-2023 6.2 | 675 |
| Weighted civil filings per judgeship | 2020 | National | JFF-2023 6.2 | 322 |

- [ ] Add at least 40 more golden values across years, districts (including N.D. Fla.) and editions, each double-checked by a second person

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_parsers_<family>.py` | unit | Each parser on committed real fixture files (1–2 per table family, xlsx and PDF) returns the expected rows; snapshot of parsed output |
| `test_header_drift.py` | unit | Same table from two editions with different layouts parses to the same schema |
| `test_court_aliases.py` | unit, hypothesis | Every alias maps to exactly one `Court`; unknown names raise, never guess |
| `test_golden_figures.py` | golden | Every value in `official_figures.yaml` comes out of the built DB with the exact value **and** edition |
| `test_revision_view.py` | integration | FY2020 national weighted per judgeship shows JB-2020 = 554 (first published) and JFF-2023 = 322, delta −232 |
| `test_fetch_idempotent.py` | unit (mocked httpx) | Re-run makes no writes; changed sha raises `EditionChangedError` |
| `test_catalog_completeness.py` | fulldata | Every (series, edition, table) in the manifest has observations; no district missing for any FY in scope |
| `test_cell_refs.py` | integration | Every observation has a resolvable `cell_ref` |

## Exit criteria

- [ ] `make data-tables` builds the catalog from scratch reproducibly (same row counts and checksums twice)
- [ ] All golden figures pass
- [ ] The revision log shows the FY2020–FY2022 weighted revisions (and any others it finds) with no manual work
- [ ] Coverage ≥ 85% for `pipeline/tables/`

## Evidence for the deck

- A screenshot of the revision log listing the 554 → 322 revision
- Count of tables, editions and observations ingested

## Risks

- PDF-only editions are slow to parse → prioritize the tables in the demo storyline and eval; mark others stretch.
- uscourts.gov layout changes → all fetched raw files are cached and committed as a manifest with sha256; the build can run offline.
