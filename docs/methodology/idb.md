# Methodology: the civil Integrated Database (IDB)

This covers Phase 2: how the server loads the Federal Judicial Center's civil
IDB, decodes it, keeps party names out of reach, and checks the result against
the official tables. The generated [data profile](../data-profile.md) shows
what the current build contains. Design decisions are in
[ADR 0007](../adr/0007-idb-ingestion.md).

## Source

| | |
| --- | --- |
| Dataset | [Civil Cases Filed, Terminated, and Pending from SY 1988 to Present](https://www.fjc.gov/research/idb/civil-cases-filed-terminated-and-pending-sy-1988-present) |
| File | `cv88on.zip` (tab-delimited text, 330 MB zipped, 2.0 GB unzipped, 10,960,173 records) |
| Release | Last-Modified 26 Aug 2026; "cases terminated in SY 1988 through June 30, 2026 and cases pending as of June 30, 2026" |
| Codebook | [Civil Codebook 1988 Forward](https://www.fjc.gov/sites/default/files/idb/codebooks/Civil%20Codebook%201988%20Forward%2010252023.pdf) (25 Oct 2023) |
| Pins | [`data/manifest/idb.yaml`](../../data/manifest/idb.yaml): sha256, size, Last-Modified, ETag |

We use the cumulative text file rather than the per-year SAS datasets on the
same page, so the build needs no SAS reader and runs as one streaming load.

**Releases change in place.** The FJC replaces `cv88on.zip` each quarter under
the same URL. The manifest pins the release we built from; `fetch` refuses a
different one (`ReleaseChangedError`) unless run with `--accept-new-release`,
which re-pins it. The Wayback Machine holds some earlier releases (March 2025,
December 2025, May 2026) but not this one, so a pinned build is reproducible
from origin only until the FJC's next release. The `@fulldata` checks use
ranges and official-table comparisons, not exact counts, so they survive a new
release.

## Build

`make data-idb` (about 85 seconds from an empty cache on a laptop: ~10 s
download, ~28 s normalize, ~45 s load):

1. **Fetch** streams the zip to `data/raw/idb/`, resuming with `Range` and
   `If-Range` after an interruption. A pinned file already on disk means no
   request at all.
2. **Normalize** streams the zip member into clean UTF-8 (below).
3. **Load** reads it into DuckDB with every column as text, then builds typed,
   decoded tables in `data/build/idb.duckdb` (atomic replace).
4. **Profile** regenerates [`docs/data-profile.md`](../data-profile.md).

A build report with counts, timings and a record checksum goes to
`data/build/idb-report.json`. Two builds of the same release give the same
checksum (`3805976:3f4c19a9…` for this release).

### Normalization

The delivered text needs three repairs. Each is counted and reported;
nothing is dropped.

| Problem | Records | Repair |
| --- | ---: | --- |
| Not valid UTF-8 (Latin-1 bytes in party names) | 23 bytes | Decode as Latin-1 |
| Control bytes (NUL, 0x1C…) inside party names | 53 bytes | Replace with a space |
| A party name quoted with a tab inside it, shifting later columns | 638 rows (tape years 2005–2011) | Re-split that row honouring double quotes; fail with the line number if it still has the wrong number of fields |

The header must match a known schema exactly (46 columns in codebook order).
An added, missing or reordered column fails the build and names the
difference.

## Records vs cases

The IDB is **one record per termination**, plus one record per pending case.
A case that is terminated, reopened under the same docket number and filing
date, and terminated again appears twice. In our scope there are 32,513 such
repeat records (27,460 of them in S.D. W. Va., mostly MDL cases statistically
closed and later closed again).

We tested three counting rules against the official Table C-1:

- **Every terminated record** reproduces C-1 terminations **exactly**, for all
  ten years FY2016–FY2025. So repeat terminations are counted terminations.
- **One row per case** (case key = district, office, docket, filing date)
  matches C-1 filings within 0.31% in every year; counting every record
  overcounts filings by up to 0.7%.
- The plan's "keep the latest record per case" would have lost about 22,000
  FY2017 terminations, so it is used for filings and case attributes only.

The database therefore has:

| Object | Grain | Use for |
| --- | --- | --- |
| `idb_civil_record` | one row per record | everything; the base table |
| `idb_civil` (view) | one row per case: its latest record (`is_latest`) | filings, cohorts, case attributes |
| `idb_civil_terminations` (view) | one row per terminated record | terminations, dispositions, time to disposition |

`record_seq` numbers a case's records in termination order over the **whole**
release, including records before the scope, so a reopened case keeps its
history. `prev_termination_date_ao` is the previous record's termination date.

### Pending cases

The IDB doesn't record when a case was reopened, so a pending count for a past
date has to be reconstructed. The rule in the profile (to be owned by the P4
measures registry): a record is pending on date *D* if it was filed (AO date)
by *D*, not terminated by *D*, and, for a repeat record, its previous
termination was on or before *D*. This lands within 0.7% of C-1 in nine of ten
years. FY2017 is +7.2%: about 22,700 S.D. W. Va. records terminated in FY2017
were terminated again later, and the reopening (which the AO counted after
September 30, 2017) isn't dated in the IDB. The `reopened-without-date` data
break records this; Phase 4 reconciliation should explain it.

## Scope

A build covers every record of a case **active at any time in FY2015–FY2025**:
filed (AO date) by September 30, 2025, and either still pending at the release
or terminated (AO date) on or after October 1, 2014. That is 3,805,976 records
for 3,774,979 cases. It includes cases filed before FY2015 that were still open
(needed for pending counts) and FY2026 terminations of cases filed by FY2025.
`--fy-from` and `--fy-to` change the window.

## Fiscal years and dates

- **Fiscal year** = October 1 to September 30, named for the year it ends
  (`core.fiscal.fiscal_year`; SQL `year(d + INTERVAL 3 MONTH)`; a property test
  keeps them equal).
- `filing_fy` and `termination_fy` use the **"date used by AO"** fields
  (`FDATEUSE`, `TDATEUSE`), which place a case in the year the AO counted it.
  They are always the first of a month. The codebook warns that cohorts built
  on actual dates won't match published tables.
- `days_to_disposition` uses the actual `FILEDATE` and `TERMDATE`. For a
  repeat record it runs from the original filing date.
- For terminated records, `TAPEYEAR` equals `termination_fy` in every record of
  this release; the build warns if that ever stops being true.

## Decoding

Each coded field has a hand-transcribed YAML file under
[`pipeline/idb/codebook/`](../../src/courts_analyst/pipeline/idb/codebook/),
one per field, for domain-expert review. Loading validates them (unique codes,
a label for every code, ordered validity dates, every district mapped to a
canonical court in its circuit).

- `idb_civil_record` carries each field as `<name>_code` plus a `<name>` label.
- Codes the codebook lists as missing (usually `-8`; `0` for `JUDGMENT`)
  become NULL. `IFP = -8` means "not IFP", so it is decoded, not nulled.
- A code not in the codebook becomes `UNKNOWN(<code>)`, is counted in
  `idb_unknown_code`, and is never dropped. This release has none.
- Five nature-of-suit codes that are no longer in the codebook still occur in
  11 in-scope records (444, 610, 620, 650, 730). They are labelled from Table
  C-2 row names and marked `discontinued`.
- Codes valid only part of the time are in `code_validity`; a record whose code
  falls outside its range is listed in `codes_outside_validity`. Only origin 13
  has a range (from July 1, 2016), and no record violates it.

### Derived columns

| Column | Rule |
| --- | --- |
| `court`, `circuit` | canonical codes (`FL-N`, `CIR-11`) from the district and circuit codebooks |
| `is_mdl_direct_filed` | origin 13, MDL case filed directly in the MDL district (valid from July 1, 2016) |
| `is_mdl_transferred` | origin 6, transferred in by the Judicial Panel on Multidistrict Litigation; exclusive with the above by construction |
| `nos_category`, `nos_group`, `nos_line` | the nature of suit's place in Table C-2 (below) |
| `jurisdiction_group` | `us` (U.S. plaintiff or defendant) or `private` |
| `procedural_stage` | before or after issue joined (codebook groups) |
| `disposition_group` | transferred or remanded, dismissed, judgment (codebook headings) |
| `is_class_action`, `is_ifp` | CLASSACT = 1; IFP = FP |

### Nature of suit and Table C-2

`nos_category` (C-2's four top-level totals), `nos_group` (the next level) and
`nos_line` (the finest C-2 row) come from the JB-2024 Table C-2 layout. Checked
against its FY2024 column, every category and group is within 0.6% except
three small groups that differ by a handful of cases (RICO +15, environmental
+6, tax suits −5):

| C-2 row | Official FY2024 | IDB FY2024 cases | Diff |
| --- | ---: | ---: | ---: |
| Contract Actions | 29,102 | 29,070 | −0.11% |
| Real Property Actions | 4,787 | 4,778 | −0.19% |
| Tort Actions | 80,982 | 80,829 | −0.19% |
| Actions Under Statutes | 176,025 | 176,057 | +0.02% |
| Personal Injury/Product Liability | 54,192 | 54,079 | −0.21% |
| Civil Rights | 45,781 | 45,758 | −0.05% |
| Prisoner Petitions | 49,182 | 49,340 | +0.32% |
| Consumer Credit | 8,731 | 8,724 | −0.08% |
| Other Statutory Actions | 10,282 | 10,228 | −0.53% |

The check caught one placement error: the Telephone Consumer Protection Act
(NOS 485) first sat under Consumer Credit, which put that row 1,349 over and
Other Statutory Actions 1,410 under. C-2 counts it as another statute. Twelve
codes are still marked `unverified` in the YAML because they're too small to
confirm their row this way.

## Party names (PII)

The IDB includes the first-listed plaintiff and defendant. They are needed for
nothing the server does, so:

- They go to `data/private/idb_parties.parquet`, keyed by `record_id`, and
  are dropped from every table in `idb.duckdb`. The server only ever gets
  `data/build` mounted, and `data/private` is in `.gitignore` and
  `.dockerignore`.
- Tests check that no table or view has a party column, that no text cell
  matches a party name, that `idb_parties` doesn't exist in the database, and
  that no server-side package (`core`, `tools`, `api`, …) names the file. The
  container test mounts a built `data/build` and confirms `data/private` is
  absent.
- The committed test sample uses synthetic names (`PLAINTIFF 000123`).

**Judges.** The public file leaves the four judge and magistrate-judge columns
blank (Judicial Conference policy). The loader fails with `PolicyError` if any
is ever populated, and drops the columns.

## Validation against official tables

National totals, IDB (this release) vs the first-published Table C-1
(JB-*FY*) from the Phase 1 catalog:

| FY | Filed (C-1) | Filed (IDB cases) | Diff | Terminated (C-1) | Terminated (IDB records) | Pending (C-1) | Pending (IDB) | Diff |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FY2016 | 291,851 | 290,951 | −0.31% | 271,649 | 271,649 | 361,566 | 362,837 | +0.35% |
| FY2017 | 267,769 | 267,610 | −0.06% | 289,901 | 289,901 | 339,131 | 363,601 | +7.22% |
| FY2018 | 282,936 | 282,245 | −0.24% | 276,311 | 276,311 | 372,820 | 370,296 | −0.68% |
| FY2019 | 297,877 | 297,093 | −0.26% | 311,900 | 311,900 | 357,566 | 355,867 | −0.48% |
| FY2020 | 470,581 | 470,332 | −0.05% | 271,256 | 271,256 | 556,366 | 555,341 | −0.18% |
| FY2021 | 344,567 | 344,390 | −0.05% | 271,625 | 271,625 | 629,588 | 628,495 | −0.17% |
| FY2022 | 274,771 | 274,705 | −0.02% | 308,326 | 308,326 | 596,136 | 595,228 | −0.15% |
| FY2023 | 339,731 | 339,965 | +0.07% | 293,677 | 293,677 | 642,013 | 641,834 | −0.03% |
| FY2024 | 290,896 | 290,734 | −0.06% | 396,635 | 396,635 | 536,766 | 536,252 | −0.10% |
| FY2025 | 303,563 | 303,597 | +0.01% | 407,539 | 407,539 | 432,923 | 432,527 | −0.09% |

Small filing differences are expected: the IDB is a 2026 snapshot with records
corrected since each table was published. Phase 4 reconciliation explains the
variance per district and year.

**The concept's MDL claim holds:** 202,463 cases filed in N.D. Fla. in FY2020
carry origin 13 (direct-filed MDL), 202,362 of them in MDL 2885 (3M Combat
Arms earplugs), out of 470,332 national filings that year.

## Tests

CI never downloads the IDB. `tests/fixtures/idb/cv_sample.zip` (150 KB, 4,182
records) is a deterministic, stratified sample in the FJC's own format: 3
cases per district and termination year, every nature-of-suit, origin and
disposition code, 150 N.D. Fla. FY2020 direct-filed MDL cases, 150 reopened
cases, 150 pending cases, the discontinued codes, and cases just outside the
window. Every record of a sampled case is kept. `make data-idb-sample`
rebuilds it, byte-identical.

`@fulldata` tests (`make test-full`) check the full build: rows per year in
range, unknown-code rate under 0.5% per field, C-1 terminations exact, C-1
filings within 0.5%, C-2 FY2024 groups within 1%, and the N.D. Fla. surge.

## Known limitations

- Pending counts for past dates are reconstructions (see above).
- The codebook describes the fields as of 2023; its district list prints Alaska
  as "7-", which is the literal code in the data.
- `DEMANDED` and `AMTREC` are unreliable by the codebook's own warning; they
  are loaded as `demanded_thousands` and `amount_received_thousands` but no
  measure should use them without caveats.
- The IDB's nature-of-suit history is recoded in places (for example code 448
  appears on records from 1966, although C-2 says collection began in 2011).
  Before our window; recorded in `data_breaks`.

## Sources

- FJC, [Integrated Database](https://www.fjc.gov/research/idb) and the civil
  dataset page (linked above), accessed 26 Sep 2026.
- FJC, Civil Codebook 1988 Forward (25 Oct 2023), linked above.
- FJC, [IDB Research Guide](https://www.fjc.gov/sites/default/files/IDB-Research-Guide.pdf).
- Administrative Office, [Table C-2, Judicial Business 2024](https://www.uscourts.gov/data-news/data-tables/2024/09/30/judicial-business/c-2)
  (`jb_c2_0930.2024.xlsx`), for the nature-of-suit hierarchy and the FY2024 check.
- Administrative Office, Table C-1, Judicial Business 2016–2025 (Phase 1
  catalog), for the national checks.
- Internet Archive CDX API, for which IDB releases are archived.
