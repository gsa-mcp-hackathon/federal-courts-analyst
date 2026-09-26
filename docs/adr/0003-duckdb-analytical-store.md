# ADR 0003: DuckDB as the analytical store

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

We store two kinds of data:

1. **Official tables:** a few thousand small uscourts.gov tables, each in
   several editions (xlsx and PDF), which we normalize into long-format figures
   with provenance.
2. **FJC Integrated Database (civil, FY2015–FY2025):** millions of case records
   that we filter and aggregate by district, nature of suit, disposition and year.

Queries are read-only aggregations. The server has to run in a single container
on Databricks Apps, Code Engine or a laptop, with no database service to run.

## Decision

Use **DuckDB** (a single `courts.duckdb` file under `DATA_DIR/build`) with
Parquet as the interchange and archive format. Pipelines (`make data`) write the
file. The server opens it **read-only**.

Options we considered:

- **SQLite:** row-oriented, and slow for group-bys over millions of IDB rows.
- **Postgres:** a service to run and secure, for no gain on read-only data.
- **Databricks SQL / Unity Catalog:** a good fit for the Genie baseline (P10),
  but it would tie local development and CI to a workspace. We can publish the
  same Parquet there later.
- **pandas/Polars in memory:** fine for tables, but the full IDB doesn't fit
  comfortably, and ad-hoc SQL is easier to audit.

## Consequences

- One file to build, ship and checksum. `server_info.data_status` reports
  whether it exists.
- CI builds a tiny fixture DB from committed fixtures and never downloads the IDB.
- Read-only connections mean concurrent requests are safe, and the server can't
  corrupt its data.
- Only `core/` (through a small repository layer) and `pipeline/` touch DuckDB,
  never tools directly.
- The `duckdb` dependency sits in the `pipeline` group today. It moves into
  runtime dependencies in P4, when core starts querying.
