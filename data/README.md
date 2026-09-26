# data/

Build inputs and outputs. Everything here is gitignored except this README and
committed manifests (added in P1/P2).

| Path | Contents | Produced by |
| --- | --- | --- |
| `raw/` | Downloaded uscourts.gov tables and FJC IDB files, untouched | `make data` (P1, P2) |
| `build/` | `courts.duckdb` and Parquet outputs | `make data` |

CI never downloads these; tests use small committed fixtures under `tests/fixtures/`.
