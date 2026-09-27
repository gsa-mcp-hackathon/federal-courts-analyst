# data/

Build inputs and outputs. Downloads and builds are gitignored; the manifests
are committed.

| Path | Contents | Produced by |
| --- | --- | --- |
| `manifest/tables.yaml` | **Committed.** Every official table edition in scope: landing page, xlsx/PDF URLs, sha256 pins | `make data-discover` (URLs), `make data-tables` (pins) |
| `raw/tables/<edition>/` | Downloaded uscourts.gov files, byte-identical to the pins | `make data-tables` |
| `build/courts.duckdb` | The analytical store the server reads (read-only) | `make data-tables` |
| `build/parquet/` | Parquet copies of the catalog tables | `make data-tables` |
| `build/tables-report.json` | Row counts, observation checksum, cross-check result, fetch summary | `make data-tables` |
| `manifest/idb.yaml` | **Committed.** The pinned FJC civil IDB release: URL, sha256, size, Last-Modified, ETag, codebook | `make data-idb` (pins) |
| `raw/idb/` | `cv88on.zip` and the codebook PDF, byte-identical to the pins | `make data-idb` |
| `build/idb.duckdb` | Civil IDB records, decoded, **no party names** (read-only for the server) | `make data-idb` |
| `build/idb-report.json` | Counts, record checksum, timings, normalization repairs | `make data-idb` |
| `private/idb_parties.parquet` | IDB party names (PII), keyed by record id. Never mounted into the server or committed | `make data-idb` |

CI never downloads anything. `tests/fixtures/tables/` holds every file the
catalog parses (about 2 MB), so the test suite builds the complete catalog
offline. `tests/fixtures/idb/cv_sample.zip` is a 4,182-record stratified
sample of the IDB with synthetic party names ([methodology](../docs/methodology/idb.md)). See [docs/data-sources.md](../docs/data-sources.md) and
[ADR 0006](../docs/adr/0006-official-tables-ingestion.md).
