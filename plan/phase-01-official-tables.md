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
- [x] Crawl the data-tables index; build `data/manifest/tables.yaml` listing each series, table code, edition, period and URL (60 editions, 117 files; crawls `/data-table-numbers/<table>` and each landing page, see Deviations)
- [x] Write down URL patterns and which editions have xlsx versus only PDF ([docs/data-sources.md](../docs/data-sources.md): three different folders, so URLs come from landing pages; JB-2016 is PDF-only)
- [x] Map court names/codes to a canonical registry (`core/courts.py`: 94 districts, 12 circuits, national). Handles "FL,N", "FL-N", "N.D. Fla.", "Florida, Northern", "1st"/"1ST"; unknown or ambiguous names raise

### Fetch
- [x] `pipeline/tables/fetch.py`: polite fetcher (one request at a time, ≥2 s apart, retries with backoff on 429/5xx, `If-Modified-Since`), raw files under `data/raw/tables/<edition>/` with sha256
- [x] Idempotent: pinned files that match are never re-requested; a changed sha on a pinned edition raises `EditionChangedError` and leaves the local copy alone

### Parse
- [x] Table-family parsers (`pipeline/tables/families.py` + `grid.py`), returning typed `Observation` rows (`records.py`)
- [x] xlsx first (openpyxl; calamine not needed). PDF with pdfplumber for JB-2016, and every PDF as a cross-check
- [x] Capture footnotes and attach them to observations (column, row-label and cell markers; general notes kept per file)
- [x] Detect and handle header drift (label-based mapping, C-1 layout change, "—"/"-" as nulls, typos like "Sept. 31", small-digit footnote markers); unmapped required measures fail the build

### Load and derive
- [x] Load into DuckDB (`data/build/courts.duckdb`) + Parquet copies (`data/build/parquet/`)
- [x] Build the `revision` view and a `revision_log` table (measure, court, FY, editions, values, delta), compared at displayed precision
- [x] Generate `docs/revision-log.md` automatically
- [ ] Measure definitions in `pipeline/tables/measures.yaml`, **written with the domain expert** (drafted from the tables' own notes; needs expert review)

### Golden figures
- [x] `tests/golden/official_figures.yaml`: the six concept figures plus 50 more (56 total) across FY2016–FY2025, national and district (N.D. Fla., S.D.N.Y., D.N.J., S.D. W. Va., W.D. Tex., E.D. Ky.), every table family and editions from JB-2016 to JFF-2025. Each value was matched against the PDF text independently of the parsers
- [ ] Each golden value double-checked by a second person (needs the team)

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

- [x] `make data-tables` builds the catalog from scratch reproducibly (same row counts and checksums twice; see Evidence)
- [x] All golden figures pass (56/56, in CI, from committed fixtures)
- [x] The revision log shows the FY2020–FY2022 weighted revisions (and 1,337 others) with no manual work
- [x] Coverage ≥ 85% for `pipeline/tables/` (92%; every module ≥ 91% except the CLI entry point)

## Evidence for the deck

- A screenshot of the revision log listing the 554 → 322 revision
- Count of tables, editions and observations ingested

## Risks

- PDF-only editions are slow to parse → prioritize the tables in the demo storyline and eval; mark others stretch.
- uscourts.gov layout changes → all fetched raw files are cached and committed as a manifest with sha256; the build can run offline.

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| Crawl the data-tables index; URL patterns like `jb_x1a_0930.2020.pdf` | Crawl `/data-table-numbers/<table>` (paginated) and read each landing page's links; never build URLs | The same table sits in three folders (`data_tables/`, `2025-01/`, `document/`); the 2024 and 2025 editions would have been missed by any pattern |
| Scope: C-1, C-2, C-3, C-5, X-1A and related; JFF 6.1–6.x; FCMS; judgeship data | **X-1A, C-1, C-5 (JB) and 6.1, 6.2, 6.3 (JFF)**, FY2016–FY2025. C-2/C-3 (nature of suit), FCMS profiles and judgeship recommendations/emergencies moved to Phase 4 (see [phase-04](phase-04-analytics-core.md#inputs-from-phase-1)) | These six carry the demo story and every golden figure. C-2/C-3 need a nature-of-suit dimension the P4 measures registry will define; FCMS and the Judicial Conference's recommendations feed `judgeship_context`, which is built in P4 |
| FY2015–FY2025 | FY2016–FY2025 editions (earlier years still come in through JFF's multi-year rows: 2015, 2010, 2005, 1995, 1990) | Discovery found no FY2015 JB edition for X-1A/C-1/C-5 on the current site |
| One parser module per table family | One generic grid reader (xlsx + PDF) plus declarative family rules (`families.py`) | Every family has the same shape; the rules are what differ. Adding a table is a few lines |
| xlsx via calamine/openpyxl, PDF fallback | openpyxl for xlsx; **every PDF parsed as a cross-check** and compared value by value | 29,422 values compared with 0 mismatches is stronger evidence than golden figures alone |
| — | Measure-id rules can take the fiscal year from the header (`(?P<fy>…)`) | C-1 before 2023 prints last year's closing pending count; it becomes a FY-1 observation, so the revision view catches pending counts restated between editions |
| — | Revisions compared at the **displayed** precision, with Excel's half-away-from-zero rounding (`core.numbers.round_half_up`) | The first cross-check run flagged 174 exact halves; the tables round 458.5 to 459, Python rounds it to 458 |
| CI never downloads; commit "a handful" of fixtures | Commit **all 57 xlsx + the 3 PDF-only files + 7 other PDFs (≈2 MB)** under `tests/fixtures/tables/` | CI then builds the complete catalog (same checksum as a full download), so golden and revision tests run on every PR ([ADR 0006](../docs/adr/0006-official-tables-ingestion.md)) |
| — | Wayback Machine fallback in `fetch` (sha256-verified; never used in the final build) | uscourts.gov blocked our IP for about 20 minutes after a burst of exploratory requests |
| — | Bulk DuckDB inserts via NDJSON instead of `executemany` | `executemany` probed for numpy/pandas on every value; a 30k-row load took 3 minutes, now under a second |
| — | `core/courts.py` (court registry) and `core/numbers.py` added now | Both are pure domain logic that P4 tools need; the court registry was required to key observations |
| — | Container test mounts a built catalog into the image and checks `server_info` reports `ready` | The deploy path (build outside, mount read-only) is tested from Phase 1 |
| Golden values "double-checked by a second person" | Checked independently by a second *method*: each value matched against the PDF text without the parsers, and the six concept figures by eye | No second person yet; left as an open issue |

## Evidence

**Build (2026-09-26):** `make data-tables` from an empty `data/raw` downloaded all **117 files from uscourts.gov** (none from the mirror; every sha256 matched the earlier pins) and built **20 editions, 60 table editions, 32,582 observations, 152 footnotes, 1,340 revised figures**. A second run made **zero HTTP requests** and produced the same row counts and observation checksum (`61bfdc9d15933296…`). The CI fixture build produces the same checksum.

| Check | Result |
| --- | --- |
| Format cross-check (xlsx vs PDF, every value both print) | 29,422 compared, **0 mismatches** |
| Golden figures | **56/56** pass (6 concept figures + 50 across FY2016–FY2025, national and district) |
| Cell refs | every observation resolves to its spreadsheet cell or PDF line |
| Completeness (`@fulldata`) | every manifest edition parsed; no district missing in any X-1A, C-1, C-5 edition; all 57 dual-format editions cross-checked |

**CI:** green on [PR #2](https://github.com/syedaun-techsur/federal-courts-analyst/pull/2) (lint, test 3.11, test 3.12, docker), building the full catalog from fixtures.

**Automated tests:** 232 passed (default suite; 9 more are `@fulldata`/`@docker`) with **95% total coverage**; `pipeline/tables/` modules 91–98%. `make docker-test`: 6 passed, including the mounted-catalog test. Lint, format, mypy (strict on `core/`) and pre-commit clean.

| Suite | Tests | Covers |
| --- | --- | --- |
| `test_court_aliases.py` | 35 | 94 districts / 12 circuits, every alias resolves back to its court, unknown and ambiguous names raise (hypothesis) |
| `test_fetch_idempotent.py` | 13 | pinned re-run sends no request, `If-Modified-Since`, `EditionChangedError` keeps the local file, 503 backoff, 404 not retried, throttle spacing |
| `test_parsers_tables.py` | 21 | 17 real files (xlsx + PDF, all six families) with snapshots; header-derived FY, June 30 periods, footnote attachment, dashes as nulls |
| `test_header_drift.py` | 11 | same schema across layouts (X-1A 2016↔2025, C-1 2020↔2023, C-5 2016/2017↔2020…); unknown or duplicated headers and inconsistent page headers raise |
| `test_golden_figures.py` | 57 | value **and** edition for every golden figure |
| `test_revision_view.py` | 8 | 554 → 322 (−232) in JFF-2023; 673→674, 676→675; FY2019–FY2025 all revised down; display precision isn't a revision |
| `test_cell_refs.py` | 1 | every `cell_ref` resolves |
| `test_tables_grid.py` | 35 | number parsing, markers, Excel rounding (hypothesis), footnote splitting, group-span algorithms, small-digit markers |
| `test_tables_manifest.py` | 11 | discovery with pagination and series filtering (mocked site), pins survive rediscovery, fixtures match pins, mirror fallback, CLI discover/fetch |
| `test_tables_build.py` | 9 | counts, cross-check, reproducibility, Parquet, revision doc, CLI build and failure paths |

**Browser check (Chrome):**
- Opened the JB-2024 X-1A landing page on uscourts.gov: its two file links are exactly the manifest's `2025-01/` URLs.
- Opened the source PDFs from the manifest. Chrome's PDF viewer only drew thumbnails in automated tabs, so the pages were rendered locally (pypdfium2) and read: **JB-2020 X-1A national row 673 / 676 / 554** ([image](../docs/evidence/phase-01/jb-2020-x1a-national-row.png)) and **JFF-2023 6.2 FY2020 row 674 / 322 / 675** ([image](../docs/evidence/phase-01/jff-2023-6.2-fy2020-row.png)).
- MCP Inspector v2.8.0 web UI over stdio (MCP 2025-11-25): `server_info` returns `data_status: "ready"` with the catalog built ([screenshot](../docs/evidence/phase-01/inspector-server-info-ready.jpg)).
- The generated [revision log](../docs/revision-log.md) rendered on GitHub (PR #2 branch): headings, outline and tables display correctly; the weighted civil table shows every year FY2016–FY2025 revised down, FY2020 554 → 322 ([screenshot](../docs/evidence/phase-01/revision-log-weighted-civil.jpg)).

**Found and fixed during the phase:**
- Python's banker's rounding made 174 xlsx/PDF values disagree; switched to Excel-style rounding everywhere.
- JFF 6.1 PDFs put the year label 3 pt above its numbers; line grouping tolerance raised to 4 pt.
- JB-2016 C-1: shifted continuation pages, a footnote marker printed as a small plain "1", and a "Sept. 31, 2016" typo on page 1; handled by per-page columns, marker detection and comparing pages by mapped measure instead of text.
- JB-2017 C-5: off-centre group labels; blocks now follow the repeated leaf-header pattern.
- DuckDB `executemany` spent 3 minutes on failed numpy imports; replaced with NDJSON bulk loads.

**For the deck:** the revision log's FY2020 row (`554 (JB-2020) → 322 (JFF-2023)`), and "6 tables, 20 editions, 117 files, 32,582 values, 1,340 revised figures, 0 xlsx/PDF mismatches". Also new: the weighted civil series was revised down for **every** year FY2016–FY2025, and the JFF 6.2 notes are word-for-word the same in every edition 2016–2025, so nothing published explains the 2023 revision ([data-sources.md](../docs/data-sources.md#what-the-tables-say-about-the-weighted-filings-revision)).

## Open issues

Live status is on the [issue tracker](https://github.com/syedaun-techsur/federal-courts-analyst/issues); unlinked items are notes, not filed.

1. **Domain expert review** of `measures.yaml` definitions (drafted from the tables' notes). [#5](https://github.com/syedaun-techsur/federal-courts-analyst/issues/5)
2. **Second-person check** of the 56 golden figures (a second method was used; a second person wasn't available). [#7](https://github.com/syedaun-techsur/federal-courts-analyst/issues/7)
3. **ADR 0004 (default edition)** still Proposed. The catalog supports either default: `revision` has both `first_published` and the latest value for every figure. [#4](https://github.com/syedaun-techsur/federal-courts-analyst/issues/4)
4. **AO confirmation** of why JFF-2023 revised the weighted series. The tables' notes don't say; the MDL explanation stays labelled as our inference. [#8](https://github.com/syedaun-techsur/federal-courts-analyst/issues/8)
5. **Deferred to Phase 4:** C-2/C-3 (nature of suit), FCMS district profiles, Judicial Conference judgeship recommendations and emergencies. STFJ/FJCS (June, December, March periods) remain stretch. [#9](https://github.com/syedaun-techsur/federal-courts-analyst/issues/9), [#15](https://github.com/syedaun-techsur/federal-courts-analyst/issues/15)
6. Chrome's built-in PDF viewer doesn't render page content in automated tabs (thumbnails only), and a tab crashed once while loading a PDF; PDFs were verified by local rendering instead.
7. From Phase 0, still open: `~/.npm` permissions (the Inspector ran with a scratch cache again), Claude Desktop not tried by hand. [#14](https://github.com/syedaun-techsur/federal-courts-analyst/issues/14), [#13](https://github.com/syedaun-techsur/federal-courts-analyst/issues/13)
