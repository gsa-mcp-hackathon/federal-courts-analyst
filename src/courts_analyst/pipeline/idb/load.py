"""Load the normalized civil IDB into ``idb.duckdb``.

Tables (all without party names):

``idb_release``         the release built from (URL, sha256, dates, scope, counts)
``idb_civil_raw``       in-scope records as delivered, typed; never queried by tools
``idb_civil_record``    one decoded row per record, with derived columns
``code_<field>``        one lookup table per codebook field
``code_validity``       codes that are only valid for part of the period
``data_breaks``         the registry in ``data_breaks.yaml``
``idb_unknown_code``    every code not in the codebook, with its record count

Views:

``idb_civil``               one row per case (its latest record): filings, cohorts
``idb_civil_terminations``  one row per terminated record: terminations

Party names go to a separate Parquet file outside the database
(``parties_path``). Nothing that opens ``idb.duckdb`` can reach them.

**Records vs cases.** The IDB has one record per termination. A case that is
terminated, reopened under the same docket number and filing date, and
terminated again has two records. Counting every terminated record reproduces
the official Table C-1 terminations exactly; counting one row per case gives
filings. ``record_seq`` orders a case's records and ``is_latest`` marks the
last one. See ``docs/methodology/idb.md``.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from courts_analyst.pipeline.idb.codebook import (
    Field_,
    load_codebook,
    load_data_breaks,
)
from courts_analyst.pipeline.idb.manifest import IdbManifest
from courts_analyst.pipeline.idb.normalize import NormalizeStats
from courts_analyst.pipeline.idb.schema import Column

# Output name of each decoded column. ``idb_civil_record`` carries the code as
# ``<name>_code`` and its label as ``<name>``.
DECODED: dict[str, str] = {
    "ORIGIN": "origin",
    "JURIS": "jurisdiction",
    "NOS": "nos",
    "JURY": "jury_demand",
    "CLASSACT": "class_action_alleged",
    "ARBIT": "arbitration_at_filing",
    "TRCLACT": "class_action_ruling",
    "PROCPROG": "procedural_progress",
    "DISP": "disposition",
    "NOJ": "nature_of_judgment",
    "JUDGMENT": "judgment_for",
    "TRMARB": "arbitration_at_termination",
    "PROSE": "pro_se",
    "IFP": "fee_status",
    "STATUSCD": "status",
}

log = logging.getLogger("courts_analyst.pipeline.idb")

SQL_FY = "year({d} + INTERVAL 3 MONTH)"
"""Federal fiscal year of a DATE in SQL; mirrors ``core.fiscal.fiscal_year``."""


class PolicyError(RuntimeError):
    """The release violates a data policy we rely on (e.g. judge codes present)."""


@dataclass
class IdbBuildResult:
    counts: dict[str, int]
    checksum: str
    release_rows: int
    unknown_codes: dict[str, dict[str, int]]
    warnings: list[str] = field(default_factory=list)


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _date(col: str) -> str:
    return f"strptime({col}, '%m/%d/%Y')::DATE"


def build_idb(
    tsv: Path,
    cols: tuple[Column, ...],
    db_path: Path,
    parties_path: Path,
    manifest: IdbManifest,
    stats: NormalizeStats,
    *,
    fy_from: int | None = None,
    fy_to: int | None = None,
) -> IdbBuildResult:
    """Build ``db_path`` (atomic replace) and ``parties_path`` from ``tsv``."""
    fy_from = fy_from or manifest.fy_from
    fy_to = fy_to or manifest.fy_to
    codebook = load_codebook()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    warnings: list[str] = []

    def step(name: str, fn: Callable[[], object]) -> None:
        t0 = time.monotonic()
        fn()
        log.info("%s: %.1fs", name, time.monotonic() - t0)

    try:
        con.execute("SET enable_progress_bar = false")
        step("stage", lambda: _stage(con, tsv, cols))
        release_rows = _scalar(con, "SELECT count(*) FROM stage")
        if release_rows != stats.rows:
            raise RuntimeError(
                f"DuckDB read {release_rows} rows, normalizer wrote {stats.rows}"
            )
        _check_policy(con, cols)
        warnings += _check_consistency(con)
        _write_codes(con, codebook)
        _write_breaks(con)
        step("raw", lambda: _raw(con, cols, fy_from, fy_to))
        step("parties", lambda: _export_parties(con, parties_path))
        con.execute("ALTER TABLE idb_civil_raw DROP COLUMN plt")
        con.execute("ALTER TABLE idb_civil_raw DROP COLUMN def")
        step("decode", lambda: _record(con, codebook))
        _views(con)
        unknown = _unknown_codes(con, cols, codebook)
        warnings += _check_courts(con)
        _release(con, manifest, stats, fy_from, fy_to, release_rows)
        con.execute("DROP TABLE stage")
        counts = {
            t: _scalar(con, f"SELECT count(*) FROM {t}")
            for t in (
                "idb_civil_raw",
                "idb_civil_record",
                "idb_civil",
                "idb_civil_terminations",
                "data_breaks",
                "code_validity",
            )
        }
        checksum = content_checksum(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    tmp.replace(db_path)
    return IdbBuildResult(counts, checksum, release_rows, unknown, warnings)


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


# ── Stage ────────────────────────────────────────────────────────────────────
def _stage(con: duckdb.DuckDBPyConnection, tsv: Path, cols: tuple[Column, ...]) -> None:
    """Every release row, all text, exactly as normalized (temporary)."""
    spec = "{" + ", ".join(f"{_q(c.name)}: 'VARCHAR'" for c in cols) + "}"
    con.execute(
        f"""
        CREATE TEMP TABLE stage AS
        SELECT * FROM read_csv({_q(str(tsv))}, delim = '\t', header = true,
            quote = '', escape = '', new_line = '\\n', strict_mode = true,
            columns = {spec})
        """
    )


def _check_policy(con: duckdb.DuckDBPyConnection, cols: tuple[Column, ...]) -> None:
    judge = [c.name for c in cols if c.role == "judge"]
    filled = " + ".join(f"count({c})" for c in judge)
    n = _scalar(con, f"SELECT {filled} FROM stage")
    if n:
        raise PolicyError(
            f"{n} judge or magistrate-judge codes are populated ({', '.join(judge)}). "
            "The public IDB leaves them blank and this server must never carry "
            "judge identifiers; stop and review before loading this release."
        )


def _check_consistency(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Status, termination date and tape year must agree; report any that don't."""
    sql = f"""
        SELECT
          count(*) FILTER (WHERE STATUSCD = 'S' AND (TDATEUSE IS NOT NULL
                                                    OR TAPEYEAR <> '2099')),
          count(*) FILTER (WHERE STATUSCD = 'L' AND TDATEUSE IS NULL),
          count(*) FILTER (WHERE STATUSCD = 'L' AND TDATEUSE IS NOT NULL
                  AND TAPEYEAR::INTEGER >= 1993
                  AND {SQL_FY.format(d=_date("TDATEUSE"))} <> TAPEYEAR::INTEGER),
          count(*) FILTER (WHERE FDATEUSE IS NULL)
        FROM stage
    """
    row = con.execute(sql).fetchone()
    assert row is not None
    labels = [
        "pending records with a termination date or tape year other than 2099",
        "terminated records without a termination date",
        "terminated records whose tape year isn't their termination fiscal year",
        "records without an AO filing date",
    ]
    return [f"{n} {label}" for n, label in zip(row, labels, strict=True) if n]


# ── Lookups ──────────────────────────────────────────────────────────────────
def _write_codes(con: duckdb.DuckDBPyConnection, codebook: dict[str, Field_]) -> None:
    for name, f in codebook.items():
        con.execute(
            f"""CREATE TABLE code_{name} (
                code VARCHAR PRIMARY KEY, label VARCHAR NOT NULL, grp VARCHAR,
                category VARCHAR, line VARCHAR, court VARCHAR, valid_from DATE,
                valid_to DATE, discontinued BOOLEAN, unverified BOOLEAN,
                note VARCHAR)"""
        )
        con.executemany(
            f"INSERT INTO code_{name} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    c.code,
                    c.label,
                    c.group,
                    c.category,
                    c.line,
                    c.court,
                    c.valid_from,
                    c.valid_to,
                    c.discontinued,
                    c.unverified,
                    c.note,
                )
                for c in f.codes
            ],
        )
    con.execute(
        """CREATE TABLE code_validity (
            field VARCHAR, code VARCHAR, valid_from DATE, valid_to DATE,
            note VARCHAR)"""
    )
    rows = [
        (name, c.code, c.valid_from, c.valid_to, c.note)
        for name, f in codebook.items()
        for c in f.codes
        if c.valid_from or c.valid_to
    ]
    if rows:
        con.executemany("INSERT INTO code_validity VALUES (?, ?, ?, ?, ?)", rows)


def _write_breaks(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE data_breaks (
            id VARCHAR PRIMARY KEY, field VARCHAR, codes VARCHAR[], date DATE,
            kind VARCHAR, summary VARCHAR, detail VARCHAR, source VARCHAR)"""
    )
    con.executemany(
        "INSERT INTO data_breaks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                b.id,
                b.field,
                list(b.codes),
                b.date,
                b.kind,
                b.summary,
                b.detail,
                b.source,
            )
            for b in load_data_breaks()
        ],
    )


# ── Raw (typed, in scope) ────────────────────────────────────────────────────
def _raw(
    con: duckdb.DuckDBPyConnection, cols: tuple[Column, ...], fy_from: int, fy_to: int
) -> None:
    """Typed, in-scope records, with record ids and per-case sequence numbers.

    Scope: every record of a case active at any time in FY ``fy_from`` through
    ``fy_to``: filed (AO date) by the end of ``fy_to`` and either still pending
    or terminated (AO date) on or after the start of ``fy_from``. Sequence
    numbers are computed over *all* of a case's records, including earlier
    ones outside the scope, so a reopened case keeps its history.
    """
    typed = []
    for c in cols:
        if c.role in ("judge", "unused"):
            continue
        col = c.name.lower()
        if c.role == "date":
            typed.append(f"{_date(c.name)} AS {col}")
        elif c.role == "int":
            typed.append(f"CAST({c.name} AS INTEGER) AS {col}")
        else:
            typed.append(f"{c.name} AS {col}")
    start, end = f"DATE '{fy_from - 1}-10-01'", f"DATE '{fy_to}-09-30'"
    con.execute(
        f"""
        CREATE TABLE idb_civil_raw AS
        WITH keys AS (
            SELECT DISTINCT DISTRICT, OFFICE, DOCKET, FILEDATE FROM stage
            WHERE TAPEYEAR >= '{fy_from}'
        ),
        t AS (
            SELECT {", ".join(typed)},
                   md5(concat_ws('|', *COLUMNS(*))) AS row_hash
            FROM stage SEMI JOIN keys USING (DISTRICT, OFFICE, DOCKET, FILEDATE)
        ),
        s AS (
            SELECT t.*,
                   district || '-' || office || '-' || docket || '-'
                       || strftime(filedate, '%Y%m%d') AS case_key,
                   row_number() OVER w AS record_seq,
                   count(*) OVER (PARTITION BY district, office, docket, filedate)
                       AS n_records,
                   lag(tdateuse) OVER w AS prev_tdateuse
            FROM t
            WINDOW w AS (PARTITION BY district, office, docket, filedate
                         ORDER BY tdateuse NULLS LAST, termdate NULLS LAST,
                                  tapeyear, row_hash)
        )
        SELECT case_key || '#' || record_seq AS record_id, * EXCLUDE (row_hash)
        FROM s
        WHERE fdateuse <= {end} AND (tdateuse IS NULL OR tdateuse >= {start})
        ORDER BY record_id
        """
    )


def _export_parties(con: duckdb.DuckDBPyConnection, parties_path: Path) -> None:
    """Party names to their own Parquet file, keyed by record id (PII)."""
    parties_path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""COPY (SELECT record_id, plt AS plaintiff, def AS defendant
                  FROM idb_civil_raw ORDER BY record_id)
            TO {_q(str(parties_path))} (FORMAT parquet)"""
    )


# ── Decoded records ──────────────────────────────────────────────────────────
def _decode(col: str, f: Field_, alias: str) -> str:
    """SQL for a label column: NULL when missing, UNKNOWN(<code>) when not coded."""
    missing = ", ".join(_q(m) for m in f.missing)
    is_missing = f"r.{col} IS NULL" + (f" OR r.{col} IN ({missing})" if missing else "")
    return (
        f"CASE WHEN {is_missing} THEN NULL "
        f"ELSE coalesce({alias}.label, 'UNKNOWN(' || r.{col} || ')') END"
    )


def _code(col: str, f: Field_) -> str:
    if not f.missing:
        return f"r.{col}"
    missing = ", ".join(_q(m) for m in f.missing)
    return f"CASE WHEN r.{col} IN ({missing}) THEN NULL ELSE r.{col} END"


def _record(con: duckdb.DuckDBPyConnection, codebook: dict[str, Field_]) -> None:
    joins: list[str] = []
    exprs: list[str] = []
    field_of = {"TRMARB": "arbit"}  # both arbitration columns share one codebook
    for column in ("CIRCUIT", "DISTRICT", *DECODED):
        name = field_of.get(column, column.lower())
        alias = f"j_{column.lower()}"
        joins.append(
            f"LEFT JOIN code_{name} {alias} ON {alias}.code = r.{column.lower()}"
        )
    for column, out in DECODED.items():
        f = codebook[field_of.get(column, column.lower())]
        col, alias = column.lower(), f"j_{column.lower()}"
        exprs.append(f"{_code(col, f)} AS {out}_code")
        exprs.append(f"{_decode(col, f, alias)} AS {out}")

    fy_file = SQL_FY.format(d="r.fdateuse")
    fy_term = SQL_FY.format(d="r.tdateuse")
    con.execute(
        f"""
        CREATE TABLE idb_civil_record AS
        SELECT
            r.record_id, r.case_key, r.record_seq, r.n_records,
            r.record_seq = r.n_records AS is_latest,
            r.record_seq > 1 AS is_repeat_record,
            r.prev_tdateuse AS prev_termination_date_ao,
            j_district.court AS court,
            j_circuit.court AS circuit,
            r.district AS district_code, r.circuit AS circuit_code,
            r.office, r.docket,
            r.filedate AS filing_date, r.fdateuse AS filing_date_ao,
            {fy_file} AS filing_fy,
            r.termdate AS termination_date, r.tdateuse AS termination_date_ao,
            CASE WHEN r.tdateuse IS NOT NULL THEN {fy_term} END AS termination_fy,
            r.tapeyear AS tape_year,
            {", ".join(exprs)},
            j_origin.grp AS origin_group,
            coalesce(r.origin = '13', FALSE) AS is_mdl_direct_filed,
            coalesce(r.origin = '6', FALSE) AS is_mdl_transferred,
            j_juris.grp AS jurisdiction_group,
            j_nos.category AS nos_category,
            j_nos.grp AS nos_group,
            j_nos.line AS nos_line,
            j_procprog.grp AS procedural_stage,
            j_disp.grp AS disposition_group,
            j_prose.grp AS pro_se_group,
            coalesce(r.classact = '1', FALSE) AS is_class_action,
            coalesce(r.ifp = 'FP', FALSE) AS is_ifp,
            nullif(r.mdldock, '-8') AS mdl_docket,
            CASE WHEN r.demanded >= 0 THEN r.demanded END AS demanded_thousands,
            CASE WHEN r.amtrec >= 0 THEN r.amtrec END AS amount_received_thousands,
            nullif(r.county, '-8') AS county_code,
            r.transdat AS transfer_date,
            CASE WHEN r.termdate IS NOT NULL THEN r.termdate - r.filedate END
                AS days_to_disposition,
            list_filter([
                CASE WHEN r.origin IS NOT NULL
                      AND (r.filedate < j_origin.valid_from
                           OR r.filedate > j_origin.valid_to) THEN 'origin' END
            ], x -> x IS NOT NULL) AS codes_outside_validity
        FROM idb_civil_raw r
        {" ".join(joins)}
        ORDER BY r.record_id
        """
    )


def _views(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE VIEW idb_civil AS
           SELECT * FROM idb_civil_record WHERE is_latest"""
    )
    con.execute(
        """CREATE VIEW idb_civil_terminations AS
           SELECT * FROM idb_civil_record WHERE status_code = 'L'"""
    )


# ── Checks and summaries ─────────────────────────────────────────────────────
def _unknown_codes(
    con: duckdb.DuckDBPyConnection,
    cols: tuple[Column, ...],
    codebook: dict[str, Field_],
) -> dict[str, dict[str, int]]:
    """Codes present in scope but absent from the codebook, per column."""
    con.execute(
        "CREATE TABLE idb_unknown_code (field VARCHAR, col VARCHAR, code VARCHAR, "
        "records BIGINT)"
    )
    out: dict[str, dict[str, int]] = {}
    for c in cols:
        if c.role != "code" or c.field is None:
            continue
        f = codebook[c.field]
        col = c.name.lower()
        missing = ", ".join(_q(m) for m in f.missing) or "NULL"
        rows = con.execute(
            f"""SELECT r.{col}, count(*) FROM idb_civil_raw r
                LEFT JOIN code_{c.field} k ON k.code = r.{col}
                WHERE r.{col} IS NOT NULL AND r.{col} NOT IN ({missing})
                  AND k.code IS NULL
                GROUP BY 1 ORDER BY 1"""
        ).fetchall()
        if rows:
            out[c.name] = {str(code): int(n) for code, n in rows}
            con.executemany(
                "INSERT INTO idb_unknown_code VALUES (?, ?, ?, ?)",
                [(c.field, c.name, code, n) for code, n in rows],
            )
    return out


def _check_courts(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Every record maps to a district, and the district is in its circuit."""
    from courts_analyst.core.courts import COURTS

    warnings = []
    unmapped = _scalar(con, "SELECT count(*) FROM idb_civil_record WHERE court IS NULL")
    if unmapped:
        warnings.append(f"{unmapped} records have a district code with no court")
    pairs = con.execute(
        "SELECT DISTINCT court, circuit FROM idb_civil_record WHERE court IS NOT NULL"
    ).fetchall()
    bad = [(d, c) for d, c in pairs if COURTS[d].circuit != c]
    if bad:
        warnings.append(
            f"district/circuit pairs that disagree with the registry: {bad}"
        )
    return warnings


def _release(
    con: duckdb.DuckDBPyConnection,
    m: IdbManifest,
    stats: NormalizeStats,
    fy_from: int,
    fy_to: int,
    release_rows: int,
) -> None:
    con.execute(
        """CREATE TABLE idb_release (
            dataset VARCHAR, url VARCHAR, sha256 VARCHAR, size BIGINT,
            last_modified VARCHAR, etag VARCHAR, codebook_url VARCHAR,
            codebook_sha256 VARCHAR, coverage VARCHAR, schema VARCHAR,
            fy_from INTEGER, fy_to INTEGER, release_rows BIGINT,
            repaired_rows INTEGER, control_bytes INTEGER, non_ascii_bytes INTEGER,
            built_at VARCHAR)"""
    )
    con.execute(
        "INSERT INTO idb_release VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?)",
        [
            m.dataset,
            m.data.url,
            m.data.sha256,
            m.data.size,
            m.data.last_modified,
            m.data.etag,
            m.codebook.url,
            m.codebook.sha256,
            m.coverage,
            stats.schema,
            fy_from,
            fy_to,
            release_rows,
            len(stats.repaired_rows),
            stats.control_bytes,
            stats.non_ascii_bytes,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ],
    )


def content_checksum(con: duckdb.DuckDBPyConnection) -> str:
    """Order-independent checksum of every decoded record (count + xor of md5s)."""
    row = con.execute(
        """SELECT count(*), bit_xor(md5_number(concat_ws('|', *COLUMNS(*))))
           FROM (SELECT COLUMNS(*)::VARCHAR FROM idb_civil_record)"""
    ).fetchone()
    assert row is not None
    n, x = row
    return f"{n}:{int(x or 0):032x}"


def write_report(
    result: IdbBuildResult, path: Path, extra: dict[str, Any] | None = None
) -> None:
    """Machine-readable build report for reproducibility checks."""
    data: dict[str, Any] = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": result.counts,
        "record_checksum": result.checksum,
        "release_rows": result.release_rows,
        "unknown_codes": result.unknown_codes,
        "warnings": result.warnings,
        **(extra or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
