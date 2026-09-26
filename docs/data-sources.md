# Data sources and methodology: official tables catalog

This covers Phase 1: how the server gets the judiciary's published caseload
tables, turns them into an edition-aware catalog, and checks the result.
The generated [revision log](revision-log.md) lists every figure that changed
between editions.

## What's in the catalog

Six uscourts.gov tables, every edition that reports fiscal years 2016–2025
(the 12 months ending September 30). That's 60 table editions, 117 files and
about 32,600 published values.

| Family | Table | Series | Rows | What it holds |
| --- | --- | --- | --- | --- |
| `jb_x1a` | X-1A | Judicial Business (JB) | 91 districts + total | Weighted and unweighted filings per authorized judgeship |
| `jff_6.2` | 6.2 | Judicial Facts and Figures (JFF) | fiscal years | The same measures as a national multi-year series |
| `jb_c1` | C-1 | JB | districts, circuits, total | Civil cases filed, terminated, pending (U.S. and private) |
| `jb_c5` | C-5 | JB | districts, circuits, total | Civil disposition counts and median months by method |
| `jff_6.1` | 6.1 | JFF | fiscal years | Civil + criminal cases filed, terminated, pending; judgeships including territorial courts |
| `jff_6.3` | 6.3 | JFF | fiscal years | Median months to disposition, civil and criminal |

An **edition** is a publication (`JB-2020`, `JFF-2023`), not a data year:
JFF-2023 Table 6.2 reports FY2019–FY2023 plus 2015, 2010, 2005, 1995 and 1990,
so one fiscal year appears in many editions. Editions are ordered by
publication: for the same September 30, Judicial Business comes first (it is
the first publication of that year's figures) and Judicial Facts and Figures
repeats or revises them.

Measure definitions are in
[`measures.yaml`](../src/courts_analyst/pipeline/tables/measures.yaml) and
come from the tables' own notes.

## How files are found

uscourts.gov lists every edition of a table on
`https://www.uscourts.gov/data-table-numbers/<table>` (paginated; for example
[`x-1a`](https://www.uscourts.gov/data-table-numbers/x-1a) and
[`62`](https://www.uscourts.gov/data-table-numbers/62)). Each edition has a
landing page, such as
[`/data-news/data-tables/2020/09/30/judicial-business/x-1a`](https://www.uscourts.gov/data-news/data-tables/2020/09/30/judicial-business/x-1a),
which links the xlsx and PDF files.

File locations are **not** predictable. The same table lives under
`/sites/default/files/data_tables/` (2016–2023), `/sites/default/files/2025-01/`
(2024) and `/sites/default/files/document/` (2025). So discovery always reads
the landing page's links and never builds URLs from a pattern.

`python -m courts_analyst.pipeline.tables discover` writes the result to
[`data/manifest/tables.yaml`](../data/manifest/tables.yaml), which is
committed. `fetch` fills in each file's sha256. Everything after that runs
from the manifest and the local cache, offline.

| Editions | Formats |
| --- | --- |
| JB-2016 (X-1A, C-1, C-5) | PDF only |
| JB-2017 to JB-2025, all JFF 2016–2025 | xlsx and PDF |

## Fetching politely

uscourts.gov sits behind Akamai. A burst of requests (we sent about 180 HEAD
requests in a minute while exploring) gets the whole IP blocked with HTTP 503
for 15–20 minutes, browsers included. The fetcher therefore:

- sends one request at a time, at least 2 seconds apart;
- retries 429/5xx with exponential backoff (20 s doubling, capped at 5 min);
- never re-requests a file whose sha256 already matches the manifest;
- revalidates unpinned files with `If-Modified-Since`;
- raises `EditionChangedError` if a pinned (published) file's bytes change,
  leaving the local copy untouched;
- as a last resort, fetches the Internet Archive's unmodified copy
  (`web.archive.org/web/2026id_/<url>`). The sha256 pin proves those are the
  same bytes, and the build report lists every file that came from the mirror.
  The Phase 1 build used none.

## Parsing: by label, not by position

Columns move between editions. X-1A 2016 lists Civil, Criminal, Hearings,
Total; X-1A 2025 lists Total first. JFF 6.2 puts weighted before unweighted,
X-1A the reverse. C-1 had four columns per group until 2022 (pending at the
start of the year, commenced, terminated, pending at the end) and three from
2023. So every parser reads the printed **header path** of each column
("Weighted Filings per Judgeship › Civil") and maps it to a measure with a
rule. A required measure that no header maps to, or two columns claiming the
same measure, fails the build (`HeaderDriftError`) instead of dropping data.

- **xlsx** (preferred: exact values). Header paths come from the header rows,
  expanding merged cells. The number format gives the displayed precision.
- **PDF** (JB-2016, and every PDF as a cross-check). Columns come from the
  x-positions of the numbers in data rows, so each page, including shifted
  continuation pages, gets its own columns. Header words attach to the column
  zone they sit over. Group headers span blocks of columns: split at the
  midpoints between group labels, or, where labels aren't evenly spread (C-5),
  the adjacent blocks that best fit the label centres and repeat the same leaf
  pattern. Small plain digits set against a word (JB-2016 prints the footnote
  marker after "Sept. 30, 2015" as a raised "1") become footnote markers.

Every value keeps the text as printed, its displayed decimals, its footnotes
and a `cell_ref` to the exact spreadsheet cell (`Table X-1A.!G6`) or PDF
page, line and column (`p1:line7:col7`). A test resolves every one of them.

## Rounding

The tables are produced in Excel, which rounds halves **away from zero**
(458.5 prints as 459). Python's `round` rounds halves to even (458.5 → 458).
Comparing the two gave 174 false mismatches between xlsx and PDF on the first
run, all of them exact halves. Every display and comparison now uses
`core.numbers.round_half_up`; DuckDB's `ROUND` already behaves that way.

## Checks

| Check | Result (2026-09-26) |
| --- | --- |
| xlsx vs PDF, every value both formats print | 29,422 values compared, **0 mismatches** |
| Golden figures ([`official_figures.yaml`](../tests/golden/official_figures.yaml)) | 56 values, each also matched against the PDF text independently of the parsers |
| Cell references | every observation resolves to its cell or PDF line |
| Completeness | every manifest edition parsed; no district missing from any X-1A, C-1 or C-5 edition |
| Reproducibility | two builds give the same row counts and the same observation checksum |

## Revisions: how they're detected

The `revision` view lines up every published value of a measure, court and
fiscal year in publication order. A figure counts as **revised** when a later
edition prints a different value at the precision both display: the JB-2020
workbook stores 553.95 and JFF-2020 prints 554; that's the same figure. The
`revision_log` table (and [revision-log.md](revision-log.md)) keeps only the
figures that changed.

## What the tables say about the weighted-filings revision

The catalog reproduces the revision the concept document describes. FY2020
weighted civil filings per judgeship were first published as **554**
(JB-2020, repeated in JFF-2020, 2021 and 2022) and printed as **322** from
JFF-2023 on. The same edition changed judgeships from 673 to 674 and
unweighted civil filings from 676 to 675. The catalog also shows that **every
fiscal year from 2016 on** was revised downward at some point, for example
FY2021 434 → 318 and FY2025 414 → 372 (JB-2025 vs JFF-2025).

What the notes printed with the tables say, verbatim in the catalog's
`footnote` table:

- **JFF Table 6.2 notes are identical in every edition, 2016 through 2025.**
  They say a methodology change means years *before 2015* may not match
  earlier editions, and that weighted filings from 2000 on use case weights
  the FJC developed in 2016. Nothing in them changed in 2023, the edition
  that revised FY2019–FY2022.
- **X-1A notes** describe the case weights as the March 2016 system (JB-2016),
  the "2015 district court case weighting system" (JB-2017 to JB-2021) and the
  "2015 district court case weighting study conducted by the FJC" (JB-2022
  on). X-1A itself was not revised; each edition reports only its own year.

So no published note explains the 2023 revision. The concept document's
reading, that the drop mostly comes from directly filed MDL cases in
N.D. Florida (3M earplugs), is **our inference, not an official statement**,
and stays labelled that way until AO statistics staff confirm it.

## Sources

- uscourts.gov table listings and landing pages cited above; each file's URL
  and sha256 are in the manifest.
- Judicial Conference judgeship thresholds (430 and 600 weighted filings) as
  summarized in [CRS Insight IN12541](https://www.congress.gov/crs-product/IN12541),
  used only in measure definitions.
- The Internet Archive's Wayback Machine (`id_` raw snapshots and its CDX
  index) was used while uscourts.gov was rate-limiting us, to inspect file
  layouts. No file in the built catalog came from it.
