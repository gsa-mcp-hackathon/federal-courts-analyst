"""Data ingestion: the uscourts.gov table scraper (P1) and the FJC IDB loader (P2).

Pipelines write to DATA_DIR (data/raw for downloads, data/build for DuckDB and
Parquet). They run offline from the server; the server only reads their output.
"""
