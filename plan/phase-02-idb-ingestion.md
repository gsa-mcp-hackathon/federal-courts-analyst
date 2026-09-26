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
- [ ] `pipeline/idb/fetch.py`: download civil IDB files from fjc.gov, record URL, release date and sha256 in `data/manifest/idb.yaml`
- [ ] Support resuming large downloads; don't commit raw files

### Load
- [ ] Stream the delimited files into DuckDB (`read_csv` with explicit types; no pandas for full loads)
- [ ] Build lookup tables from the codebook (hand-transcribed YAML under `pipeline/idb/codebook/`, reviewed by the domain expert)
- [ ] Build `idb_civil` view with decoded labels and derived columns; move party names to `idb_parties`
- [ ] Record `data_breaks` entries (for example origin code 13 starts Jul 2016; any NOS code additions; COVID-era reporting notes)

### Subset for the repo
- [ ] `make data-idb-sample` produces a small, deterministic fixture (for example ~5,000 cases stratified by district, FY, NOS, including N.D. Fla. 3M earplug MDL cases) at `tests/fixtures/idb_sample.parquet`, with party names replaced by synthetic values
- [ ] A reproducible subset build for judges: civil FY2015–FY2025 only, with a single command

### Sanity profiling
- [ ] `docs/data-profile.md` generated automatically: rows per FY, per district, null rates, code distributions, unknown-code counts

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

- [ ] `make data-idb` builds the full civil subset from raw files in a documented time
- [ ] The committed fixture supports all later unit and integration tests without the full data
- [ ] Party names are unreachable from `idb_civil` (test enforced)
- [ ] Data profile and data-break registry exist in `docs/`

## Risks

- File sizes and format changes across releases → loader is driven by a per-release schema map; fail loudly on unknown columns.
- Codebook transcription errors → domain-expert review plus the unknown-code rate test.
- IDB counts won't exactly match official tables → expected; that's what P4 reconciliation explains.
