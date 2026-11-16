"""Load parsed tables into DuckDB and Parquet, and derive the revision log.

Tables: ``source_file``, ``table_def``, ``measure_def``, ``court``,
``edition``, ``observation``, ``footnote``, ``format_check``.
Views: ``revision`` (every published value of a measure/court/year across
editions, in publication order) and table ``revision_log`` (only the figures
whose displayed value changed between editions).

Revisions are compared at the *displayed* precision of the two values: a PDF
that prints 355 and a workbook that stores 355.12 with a 0-decimal format are
the same published figure, not a revision.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import yaml

from courts_analyst.core.courts import COURTS
from courts_analyst.pipeline.tables.families import FAMILIES
from courts_analyst.pipeline.tables.records import (
    SERIES_TITLES,
    Footnote,
    Observation,
    SourceFile,
)

MEASURES_YAML = Path(__file__).parents[2] / "core" / "data" / "measures.yaml"

# JB is the first publication of a fiscal year's figures; JFF repeats and
# revises them. Same-date editions are ordered by this rank.
SERIES_RANK = {"JB": 0, "FJCS": 1, "STFJ": 2, "JFF": 3, "FCMS": 4}

SCHEMA = """
CREATE TABLE source_file (
    file_id VARCHAR PRIMARY KEY, family VARCHAR, url VARCHAR, landing_url VARCHAR,
    sha256 VARCHAR, fetched_at VARCHAR, series VARCHAR, table_code VARCHAR,
    edition VARCHAR, period_end DATE, format VARCHAR, title VARCHAR,
    parsed BOOLEAN
);
CREATE TABLE edition (
    edition VARCHAR PRIMARY KEY, series VARCHAR, series_title VARCHAR,
    period_end DATE, pub_order INTEGER
);
CREATE TABLE table_def (
    family VARCHAR PRIMARY KEY, series VARCHAR, table_code VARCHAR,
    title VARCHAR, description VARCHAR, row_kind VARCHAR
);
CREATE TABLE measure_def (
    measure_id VARCHAR PRIMARY KEY, label VARCHAR, definition VARCHAR,
    unit VARCHAR, weighted BOOLEAN, denominator VARCHAR, decimals INTEGER
);
CREATE TABLE court (
    code VARCHAR PRIMARY KEY, name VARCHAR, level VARCHAR, circuit VARCHAR,
    citation VARCHAR, state VARCHAR
);
CREATE TABLE footnote (
    footnote_id VARCHAR PRIMARY KEY, file_id VARCHAR, marker VARCHAR, text VARCHAR
);
CREATE TABLE observation (
    obs_id VARCHAR PRIMARY KEY, file_id VARCHAR, edition VARCHAR, table_code VARCHAR,
    measure_id VARCHAR, court VARCHAR, fiscal_year INTEGER, period_end DATE,
    value DOUBLE, decimals INTEGER, footnote_ids VARCHAR[], cell_ref VARCHAR,
    raw VARCHAR
);
CREATE TABLE format_check (
    edition VARCHAR, table_code VARCHAR, measure_id VARCHAR, court VARCHAR,
    fiscal_year INTEGER, xlsx_value DOUBLE, pdf_value DOUBLE, pdf_raw VARCHAR,
    agrees BOOLEAN
);
"""

REVISION_VIEW = """
CREATE VIEW revision AS
WITH o AS (
    SELECT ob.*, e.pub_order,
           ROW_NUMBER() OVER w AS nth,
           LAG(ob.value) OVER w AS prior_value,
           LAG(ob.decimals) OVER w AS prior_decimals,
           LAG(ob.edition) OVER w AS prior_edition
    FROM observation ob JOIN edition e USING (edition)
    WHERE ob.value IS NOT NULL
    WINDOW w AS (PARTITION BY measure_id, court, fiscal_year ORDER BY e.pub_order)
)
SELECT measure_id, court, fiscal_year, edition, table_code, value, decimals,
       pub_order, nth = 1 AS first_published, prior_edition, prior_value,
       CASE WHEN prior_value IS NULL THEN NULL
            ELSE ROUND(value, LEAST(decimals, prior_decimals))
               - ROUND(prior_value, LEAST(decimals, prior_decimals)) END AS delta,
       CASE WHEN prior_value IS NULL THEN FALSE
            ELSE ROUND(value, LEAST(decimals, prior_decimals))
              <> ROUND(prior_value, LEAST(decimals, prior_decimals)) END AS revised,
       file_id, cell_ref, raw
FROM o
"""

REVISION_LOG = """
CREATE TABLE revision_log AS
WITH changed AS (
    SELECT DISTINCT measure_id, court, fiscal_year FROM revision WHERE revised
),
chain AS (
    SELECT r.* FROM revision r JOIN changed USING (measure_id, court, fiscal_year)
),
agg AS (
    SELECT measure_id, court, fiscal_year,
           arg_min(edition, pub_order) AS first_edition,
           arg_min(value, pub_order) AS first_value,
           arg_min(decimals, pub_order) AS first_decimals,
           arg_max(edition, pub_order) AS latest_edition,
           arg_max(value, pub_order) AS latest_value,
           arg_max(decimals, pub_order) AS latest_decimals,
           COUNT(*) AS n_editions,
           SUM(CASE WHEN revised THEN 1 ELSE 0 END) AS n_revisions,
           list(edition ORDER BY pub_order) AS editions,
           list(value ORDER BY pub_order) AS values
    FROM chain GROUP BY ALL
)
SELECT *,
       ROUND(latest_value, LEAST(first_decimals, latest_decimals))
     - ROUND(first_value, LEAST(first_decimals, latest_decimals)) AS delta
FROM agg
ORDER BY measure_id, court, fiscal_year
"""


def load_measures() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = yaml.safe_load(MEASURES_YAML.read_text())
    return data


def build_database(
    db_path: Path,
    sources: list[SourceFile],
    observations: list[Observation],
    footnotes: list[Footnote],
    format_checks: Iterable[dict[str, Any]] = (),
    parquet_dir: Path | None = None,
) -> dict[str, int]:
    """Write a fresh DuckDB file (atomic replace). Returns row counts."""
    measures = load_measures()
    unknown = {o.measure_id for o in observations} - set(measures)
    if unknown:
        raise ValueError(f"measures missing from measures.yaml: {sorted(unknown)}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(SCHEMA)
        parsed_ids = {o.file_id for o in observations}
        _insert(
            con,
            "source_file",
            [
                (
                    s.file_id,
                    _family_of(s),
                    s.url,
                    s.landing_url,
                    s.sha256,
                    s.fetched_at,
                    s.series.value,
                    s.table_code,
                    s.edition,
                    s.period_end,
                    s.format,
                    s.title,
                    s.file_id in parsed_ids,
                )
                for s in sources
            ],
        )
        editions = sorted(
            {(s.edition, s.series.value, s.period_end) for s in sources},
            key=lambda e: (e[2], SERIES_RANK[e[1]], e[0]),
        )
        _insert(
            con,
            "edition",
            [
                (ed, series, SERIES_TITLES[s_enum], end, i)
                for i, (ed, series, end) in enumerate(editions, start=1)
                for s_enum in [next(s.series for s in sources if s.edition == ed)]
            ],
        )
        _insert(
            con,
            "table_def",
            [
                (
                    f.key,
                    f.series.value,
                    f.table_code,
                    f.title,
                    f.description,
                    f.row_kind,
                )
                for f in FAMILIES.values()
            ],
        )
        _insert(
            con,
            "measure_def",
            [
                (
                    mid,
                    m["label"],
                    " ".join(str(m["definition"]).split()),
                    m["unit"],
                    bool(m["weighted"]),
                    m.get("denominator"),
                    int(m["decimals"]),
                )
                for mid, m in measures.items()
            ],
        )
        _insert(
            con,
            "court",
            [
                (c.code, c.name, c.level.value, c.circuit, c.citation, c.state)
                for c in COURTS.values()
            ],
        )
        _insert(
            con,
            "footnote",
            [(f.footnote_id, f.file_id, f.marker, f.text) for f in footnotes],
        )
        src_by_id = {s.file_id: s for s in sources}
        _insert(
            con,
            "observation",
            [
                (
                    obs_id(o),
                    o.file_id,
                    src_by_id[o.file_id].edition,
                    src_by_id[o.file_id].table_code,
                    o.measure_id,
                    o.court,
                    o.fiscal_year,
                    o.period_end,
                    o.value,
                    o.decimals,
                    list(o.footnote_ids),
                    o.cell_ref,
                    o.raw,
                )
                for o in observations
            ],
        )
        checks = list(format_checks)
        if checks:
            _insert(
                con,
                "format_check",
                [
                    (
                        c["edition"],
                        c["table_code"],
                        c["measure_id"],
                        c["court"],
                        c["fiscal_year"],
                        c["xlsx_value"],
                        c["pdf_value"],
                        c["pdf_raw"],
                        c["agrees"],
                    )
                    for c in checks
                ],
            )
        con.execute(REVISION_VIEW)
        con.execute(REVISION_LOG)
        counts = {
            t: int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])  # type: ignore[index]
            for t in (
                "source_file",
                "edition",
                "observation",
                "footnote",
                "measure_def",
                "revision_log",
                "format_check",
            )
        }
        if parquet_dir is not None:
            parquet_dir.mkdir(parents=True, exist_ok=True)
            for t in (
                "source_file",
                "edition",
                "observation",
                "footnote",
                "revision_log",
            ):
                dest = parquet_dir / f"{t}.parquet"
                con.execute(
                    f"COPY (SELECT * FROM {t} ORDER BY ALL) TO '{dest}' "
                    "(FORMAT PARQUET)"
                )
        con.execute("CHECKPOINT")
    finally:
        con.close()
    tmp.replace(db_path)
    return counts


def _insert(
    con: duckdb.DuckDBPyConnection, table: str, rows: Iterable[tuple[Any, ...]]
) -> None:
    """Bulk insert through newline-delimited JSON.

    ``executemany`` probes for numpy/pandas on every value it converts; with
    neither installed each probe is a failed import that searches sys.path
    again, which made a 30k-row load take minutes.
    """
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False) as f:
        for row in rows:
            f.write(json.dumps(dict(zip(cols, row, strict=True)), default=str) + "\n")
        path = f.name
    try:
        types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {table}").fetchall()}
        spec = "{" + ", ".join(f"'{c}': '{t}'" for c, t in types.items()) + "}"
        con.execute(
            f"INSERT INTO {table} SELECT * FROM read_json(?, "
            f"format = 'newline_delimited', columns = {spec})",
            [path],
        )
    finally:
        Path(path).unlink(missing_ok=True)


def obs_id(o: Observation) -> str:
    key = f"{o.file_id}|{o.measure_id}|{o.court}|{o.fiscal_year}"
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]


def _family_of(s: SourceFile) -> str:
    return next(
        (
            f.key
            for f in FAMILIES.values()
            if f.series == s.series and f.table_code == s.table_code
        ),
        "",
    )


def content_checksum(observations: list[Observation]) -> str:
    """Order-independent sha256 over every observation (reproducibility check)."""
    rows = sorted(
        json.dumps(
            {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in o.model_dump().items()
            },
            sort_keys=True,
        )
        for o in observations
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


__all__ = ["build_database", "content_checksum", "load_measures", "obs_id"]
