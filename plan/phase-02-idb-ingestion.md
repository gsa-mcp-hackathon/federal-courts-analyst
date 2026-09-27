# Phase 2: IDB Ingestion

**Goal:** load the FJC Integrated Database civil files (FY2015–FY2025) into DuckDB with every code decoded, codebook changes tracked, and party names isolated so they can't leak into outputs.

**Judging impact:** Technical quality (reproducible build over messy bulk data) and innovation (flexible cohort queries that the official tables can't answer).

## Scope

**In:** civil IDB, cases filed or terminated FY2015–FY2025; codebooks; a data-break registry.
**Out:** criminal, appellate and bankruptcy IDB (stretch).

## Design

```
idb_civil_raw        -- as delivered, typed, one row per case record (never queried by tools)
idb_civil            -- cleaned + decoded view used by core (no party-name columns)
idb_parties          -- party names, separate table, not exposed to any tool (PII)
code_nos, code_origin, code_disposition, code_jurisdiction, code_procprog, ...  -- lookup tables
code_validity        -- (field, code, valid_from, valid_to, note), e.g. origin 13 only from Jul 2016
data_breaks          -- (field, date, description, source) known codebook/collection changes
```

Key derived columns on `idb_civil`:
- `filing_fy`, `termination_fy` (federal fiscal year, Oct–Sep)
- `court` (same canonical `Court` enum as P1)
- `is_mdl_direct_filed` (origin code for MDL cases filed directly in the district; confirm the code value against the codebook, valid from July 2016)
- `is_mdl_transferred` (MDL transfer origin codes)
- `days_to_disposition`
- `nos_group` (nature-of-suit grouping matching official tables, for example "Personal injury – product liability")

**Record dedup:** the IDB delivers records as snapshots; a case can appear more than once across releases. Keep the latest record per case key (circuit, district, office, docket, filing date), and document the rule in `docs/methodology/idb.md`.

## Tasks

### Acquire
- [x] `pipeline/idb/fetch.py`: download civil IDB files from fjc.gov, record URL, release date and sha256 in `data/manifest/idb.yaml`
- [x] Support resuming large downloads; don't commit raw files

### Load
- [x] Stream the delimited files into DuckDB (`read_csv` with explicit types; no pandas for full loads)
- [x] Build lookup tables from the codebook (hand-transcribed YAML under `pipeline/idb/codebook/`, reviewed by the domain expert)
- [x] Build `idb_civil` view with decoded labels and derived columns; move party names to `idb_parties`
- [x] Record `data_breaks` entries (for example origin code 13 starts Jul 2016; any NOS code additions; COVID-era reporting notes)

### Subset for the repo
- [x] `make data-idb-sample` produces a small, deterministic fixture (for example ~5,000 cases stratified by district, FY, NOS, including N.D. Fla. 3M earplug MDL cases) at `tests/fixtures/idb_sample.parquet`, with party names replaced by synthetic values
- [x] A reproducible subset build for judges: civil FY2015–FY2025 only, with a single command

### Sanity profiling
- [x] `docs/data-profile.md` generated automatically: rows per FY, per district, null rates, code distributions, unknown-code counts

## Tests

| Test | Type | Checks |
| --- | --- | --- |
| `test_codebook.py` | unit | Every code in the YAML has a label; no duplicate codes per field; validity ranges don't overlap |
| `test_decode.py` | unit | Known raw rows decode to expected labels; unknown codes become `UNKNOWN(<code>)`, never dropped silently |
| `test_fiscal_year.py` | unit, hypothesis | `filing_fy` for any date: Oct 1 starts a new FY; boundary dates correct |
| `test_dedup.py` | unit | Duplicate snapshot records collapse to the latest; count checks on fixture |
| `test_mdl_flags.py` | unit | Origin 13 before Jul 2016 is flagged as a data break; direct-filed and transferred flags are mutually exclusive |
| `test_pii_isolation.py` | integration | `idb_civil` has no party-name columns; querying through `core` can't reach `idb_parties` |
| `test_sample_fixture.py` | integration | Fixture builds deterministically (same hash twice) and includes the N.D. Fla. MDL stratum |
| `test_full_load.py` | fulldata | Row counts per FY within expected ranges; unknown-code rate < 0.5% per field |
| `test_nd_fla_surge.py` | fulldata | FY2020 N.D. Fla. direct-filed MDL filings > 200,000 (matches the concept's claim) |

## Exit criteria

- [x] `make data-idb` builds the full civil subset from raw files in a documented time
- [x] The committed fixture supports all later unit and integration tests without the full data
- [x] Party names are unreachable from `idb_civil` (test enforced)
- [x] Data profile and data-break registry exist in `docs/`

## Risks

- File sizes and format changes across releases → loader is driven by a per-release schema map; fail loudly on unknown columns.
- Codebook transcription errors → domain-expert review plus the unknown-code rate test.
- IDB counts won't exactly match official tables → expected; that's what P4 reconciliation explains.

## Deviations

| Plan said | We did | Why |
| --- | --- | --- |
| "Download civil IDB files" | One file: the cumulative tab-delimited `cv88on.zip` (330 MB), not the per-year SAS datasets | Same records, no SAS reader or pandas, one streaming load |
| Record the release date and sha256 | Pin sha256, size, Last-Modified and ETag; a different release fails (`ReleaseChangedError`) unless `--accept-new-release` | The FJC replaces the file in place each quarter; the Wayback Machine has older releases but not this one |
| Dedup: "keep the latest record per case" | Keep **every** record; `idb_civil` (latest per case) for filings, `idb_civil_terminations` (every terminated record) for terminations | Repeat records are re-terminations, not snapshots. Every terminated record reproduces C-1 terminations **exactly** FY2016–FY2025; the plan's rule would lose ~22,000 FY2017 terminations ([ADR 0007](../docs/adr/0007-idb-ingestion.md)) |
| `read_csv` with explicit types | Streaming normalize pass first (Latin-1, control bytes, quote-aware re-split of 638 shifted rows), then `read_csv` with an exact text column list, typed in SQL | The raw file isn't valid UTF-8 and has rows DuckDB would reject or silently drop |
| `idb_parties` table in the database | Party names in `data/private/idb_parties.parquet`, outside `data/build`; dropped from every table | The server never has the file at all, which is stronger than "no tool queries it" |
| Tables in the analytical store | Separate `data/build/idb.duckdb` | Tables (10 s) and IDB (80 s) rebuild independently; P4 attaches both read-only |
| `idb_civil_raw` "as delivered" | Typed, in scope, without party names, judge columns or the four unused procedural-date columns | Judge columns must be blank (the build fails otherwise); unused columns are always empty |
| `nos_group` matching official tables | `nos_category` › `nos_group` › `nos_line` = the JB-2024 Table C-2 hierarchy, checked against C-2's FY2024 column (every group within 0.6%, bar three that differ by ≤15 cases) | The check caught TCPA (485) misfiled under Consumer Credit |
| Fixture at `tests/fixtures/idb_sample.parquet`, ~5,000 cases | `tests/fixtures/idb/cv_sample.zip`, 4,182 records (150 KB) in the FJC's own zip/TSV format | CI runs the same normalize → load path as the full build |
| Scope "filed or terminated FY2015–FY2025" | Every record of a case **active** in FY2015–FY2025 (includes older still-open cases and FY2026 terminations of cases filed by FY2025) | Needed to reconstruct pending counts |
| — | `core/fiscal.py` (fiscal-year helpers) with a property test that SQL and Python agree | Every later phase keys on fiscal years |
| — | `server_info` gains `datasets` (`official_tables`, `idb_civil`) | Clients can see the IDB is loaded |
| `test_mdl_flags`: origin 13 before July 2016 flagged | Generic `codes_outside_validity` list driven by `code_validity`; no real record violates it (tested on synthetic rows) | Works for any future code with a validity range |

## Evidence

**Build (2026-09-26):** `make data-idb` from an empty `data/raw/idb` downloaded the 330 MB release and codebook and built `idb.duckdb` in **84 s** (download ~10 s, normalize 28 s, load ~45 s). The release has **10,960,173 records**; the FY2015–FY2025 scope holds **3,805,976 records for 3,774,979 cases**, 3,498,547 terminations, 307,429 pending. Normalization repaired 638 rows and replaced 53 control bytes; **no unknown codes** and no warnings. A second run made **zero requests** and gave the same record checksum (`3805976:3f4c19a9…`).

| Check against official tables | Result |
| --- | --- |
| C-1 terminations FY2016–FY2025 (every terminated record) | **exact, 10/10 years** |
| C-1 filings (one row per case) | within **0.31%** every year |
| C-1 pending (reconstructed) | within 0.7% in 9/10 years; FY2017 +7.2% (S.D. W. Va. reopenings, see methodology) |
| C-2 FY2024 by category and group | 25 rows, all within 0.6% except RICO +15, environmental +6, tax −5 cases |
| N.D. Fla. FY2020 direct-filed MDL | **202,463** (> 200,000 claim), 202,362 in MDL 2885 |

**CI:** green on [PR #3](https://github.com/syedaun-techsur/federal-courts-analyst/pull/3) (lint, test 3.11, test 3.12, docker), building the IDB from the committed sample.

**Automated tests:** 328 passed in the default suite (96 new for this phase), **96% total coverage**; `pipeline/idb/` modules 90–100%. `@fulldata` IDB suite: 7/7 against the full build. `make docker-test`: 6/6, including a container reading both mounted databases and confirming `data/private` is absent. Lint, format, mypy and pre-commit clean.

| Suite | Tests | Covers |
| --- | --- | --- |
| `test_codebook.py` | 41 | labels and unique codes per field, ordered validity, 94 districts ↔ registry, circuits, C-2 placement, bad YAML rejected (duplicate code, stray key from an unquoted comma, reversed validity) |
| `test_idb_normalize.py` | 6 | Latin-1 and control bytes, quoted-tab repair, unrepairable row names its line, header drift |
| `test_decode.py` | 8 | known row → labels and derived columns, missing vs unknown, `UNKNOWN(<code>)` counted, pending, judge codes stop the build, consistency and court warnings |
| `test_fiscal_year.py` | 3 | boundaries; hypothesis: Oct 1 starts a new FY; SQL = Python |
| `test_dedup.py` | 4 | re-terminated case → 1 case, 2 terminations; sequencing across the window; scope edges; fixture counts |
| `test_mdl_flags.py` | 3 | origin 13 before July 2016 flagged; direct/transferred exclusive; N.D. Fla. MDL 2885 stratum |
| `test_pii_isolation.py` | 5 | no party columns or values in any table, no `idb_parties`, parties file outside `data/build`, server packages never name it |
| `test_sample_fixture.py` | 3 | sampling is byte-deterministic; 94 districts, 12 FYs, pending and discontinued codes present |
| `test_idb_fetch.py` | 9 | pinned file → no request, Range/If-Range resume, mid-download release change restarts, new release refused then accepted, retries, 404/403, truncation |
| `test_idb_build.py` | 13 | tables and views, provenance row, dropped columns, reproducible checksum, report, profile, CLI build/sample/fetch |
| `test_full_load.py` (`@fulldata`) | 7 | rows per FY, unknown rate < 0.5%, C-1 terminations exact, filings ±0.5%, C-2 groups ±1%, N.D. Fla. surge, origin-13 validity |

**Claude in Chrome:**
- Opened the FJC civil IDB page: its codebook and `cv88on.zip` links and the coverage text ("Cases terminated in SY 1988 through June 30, 2026 and cases pending as of June 30, 2026") match `data/manifest/idb.yaml` exactly ([screenshot](../docs/evidence/phase-02/fjc-civil-idb-landing.png)).
- Ran the image (`git_sha 9763506`) with the full `data/build` mounted read-only; `/health` and `/version` respond in Chrome; `/app/data` holds only `build/`.
- MCP Inspector v2.8.0 over stdio: `server_info` returns `data_status: ready` and `datasets: {official_tables: ready, idb_civil: ready}` ([screenshot](../docs/evidence/phase-02/inspector-server-info-datasets.png)). The Inspector's "Add servers" menu didn't respond to clicks, so the container was checked over HTTP by `make docker-test` instead of in the Inspector.
- `docs/data-profile.md` and `docs/methodology/idb.md` rendered on GitHub (PR branch): 22 and 6 tables render, every internal link resolves ([screenshot](../docs/evidence/phase-02/data-profile-by-fiscal-year.jpg)).

**Found and fixed during the phase:**
- DuckDB rejected the raw file (invalid UTF-8, then 638 rows with 47–48 fields); added the normalize pass.
- Two YAML labels with unquoted commas ("Yes, type unknown", "Rent, lease and ejectment") became stray keys; the codebook's strict validation caught them.
- `COLUMNS(*)` inside a function expands to one call per column in DuckDB; the row hash and checksum needed `*COLUMNS(*)`. The first build took 7 minutes; restricting sequencing to cases with a record in the window brought it to 72 s.
- TCPA (485) misfiled under Consumer Credit; the C-2 comparison showed it (+1,349 / −1,410).

**For the deck:** "10.96 million records → 3.8 million in scope in 84 seconds; terminations match the official tables exactly for ten straight years; 202,463 earplug cases filed directly in one district in one year."

## Open issues

1. **Domain expert review** of the codebook YAML (15 fields, 102 NOS codes; 12 NOS placements are marked `unverified`) and of `data_breaks.yaml`.
2. **Release reproducibility:** the pinned release can only be re-downloaded until the FJC's next quarterly update (likely November 2026). Options: submit it to the Wayback Machine (an outward action, not done), or publish our build artifacts with the submission.
3. **Pending counts for past dates** are reconstructions; FY2017 is 7.2% above C-1. Phase 4 reconciliation should own the explanation (and the pending rule, now in `profile.py`).
4. Criminal, appellate and bankruptcy IDB remain stretch.
5. The Inspector's "Add servers" menu didn't open under automation; the container was verified by `make docker-test`, not in the Inspector UI.
