"""Deterministic, stratified sample of the civil IDB for tests and CI.

The sample is written in the FJC's own format (a zip holding one CRLF,
tab-delimited text file with the release header), so CI runs the same
normalize → load path as the full build. Every record of a selected case is
kept, including records outside the FY window, so sequencing, scope and
dedup behave as they do on the full file.

Selection is by ``md5(case key)`` rank within each stratum; no randomness:

- 3 cases per district × (termination FY or pending)
- 3 cases per nature-of-suit code, 2 per origin and disposition code
- 150 N.D. Fla. direct-filed MDL cases from FY2020 (the 3M earplug surge)
- 50 other direct-filed MDL cases and 50 MDL transfers
- 150 cases with more than one record (reopened and re-terminated)
- 150 pending cases
- every in-scope record carrying a code missing from the codebook's current
  list (discontinued nature-of-suit codes)
- 25 cases just outside the window on each side

Party names are replaced by synthetic ones (``PLAINTIFF 000123``).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import duckdb

from courts_analyst.pipeline.idb.codebook import load_codebook
from courts_analyst.pipeline.idb.load import SQL_FY, _date, _stage
from courts_analyst.pipeline.idb.normalize import normalize_zip

ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def build_sample(
    zip_path: Path,
    member: str,
    out_zip: Path,
    workdir: Path,
    *,
    fy_from: int,
    fy_to: int,
) -> int:
    """Write the sample zip to ``out_zip``; return the number of records."""
    tsv = workdir / "idb-sample-source.tsv"
    try:
        _, cols = normalize_zip(zip_path, member, tsv)
        con = duckdb.connect()
        con.execute("SET enable_progress_bar = false")
        _stage(con, tsv, cols)
    finally:
        tsv.unlink(missing_ok=True)
    names = [c.name for c in cols]
    con.execute(_selection_sql(fy_from, fy_to))
    rows = con.execute(
        f"""SELECT {", ".join(f"s.{n}" for n in names)}, k.n
            FROM stage s
            JOIN picked k ON k.key = s.DISTRICT || '-' || s.OFFICE || '-'
                                     || s.DOCKET || '-' || s.FILEDATE
            ORDER BY k.n, s.TAPEYEAR, s.TDATEUSE NULLS LAST, s.TERMDATE,
                     md5(concat_ws('|', {", ".join(f"s.{n}" for n in names)}))"""
    ).fetchall()
    con.close()

    plt, dfn = names.index("PLT"), names.index("DEF")
    buf = io.StringIO(newline="")
    buf.write("\t".join(names) + "\r\n")
    for row in rows:
        values = ["" if v is None else str(v) for v in row[:-1]]
        n = int(row[-1])
        values[plt] = f"PLAINTIFF {n:06d}"
        values[dfn] = f"DEFENDANT {n:06d}"
        buf.write("\t".join(values) + "\r\n")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo(member, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with zipfile.ZipFile(out_zip, "w") as zf:
        zf.writestr(info, buf.getvalue().encode("latin-1"), compresslevel=9)
    return len(rows)


def _selection_sql(fy_from: int, fy_to: int) -> str:
    fd, td = _date("FDATEUSE"), _date("TDATEUSE")
    nos = load_codebook()["nos"].codes
    discontinued = ", ".join(f"'{c.code}'" for c in nos if c.discontinued)

    def top(src: str, where: str, n: int) -> str:
        return (
            f"SELECT key FROM {src} WHERE {where} "
            f"QUALIFY row_number() OVER (ORDER BY h) <= {n}"
        )

    return f"""
    CREATE TEMP TABLE picked AS
    WITH b AS (
        SELECT DISTRICT || '-' || OFFICE || '-' || DOCKET || '-' || FILEDATE AS key,
               DISTRICT, NOS, ORIGIN, DISP, STATUSCD,
               {SQL_FY.format(d=fd)} AS ffy,
               CASE WHEN TDATEUSE IS NOT NULL THEN {SQL_FY.format(d=td)} END AS tfy
        FROM stage
    ),
    k AS (
        SELECT *, md5(key) AS h,
               count(*) OVER (PARTITION BY key) AS nrec,
               ffy <= {fy_to} AND (tfy IS NULL OR tfy >= {fy_from}) AS in_scope
        FROM b
    ),
    s AS (SELECT * FROM k WHERE in_scope),
    strata AS (
        SELECT key FROM s QUALIFY row_number() OVER (
            PARTITION BY DISTRICT, coalesce(tfy, 0) ORDER BY h) <= 3
        UNION SELECT key FROM s QUALIFY row_number() OVER (
            PARTITION BY NOS ORDER BY h) <= 3
        UNION SELECT key FROM s QUALIFY row_number() OVER (
            PARTITION BY ORIGIN ORDER BY h) <= 2
        UNION SELECT key FROM s QUALIFY row_number() OVER (
            PARTITION BY DISP ORDER BY h) <= 2
        UNION {top("s", "DISTRICT = '29' AND ORIGIN = '13' AND ffy = 2020", 150)}
        UNION {top("s", "ORIGIN = '13' AND DISTRICT <> '29'", 50)}
        UNION {top("s", "ORIGIN = '6'", 50)}
        UNION {top("s", "nrec > 1", 150)}
        UNION {top("s", "STATUSCD = 'S'", 150)}
        UNION SELECT key FROM s WHERE NOS IN ({discontinued})
        UNION {top("k", f"tfy = {fy_from - 1}", 25)}
        UNION {top("k", f"ffy = {fy_to + 1}", 25)}
    )
    SELECT key, row_number() OVER (ORDER BY md5(key)) AS n
    FROM (SELECT DISTINCT key FROM strata)
    """
