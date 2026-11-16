"""The catalog as documents: what's loaded, one published table, the
revision log. Backs the ``courts://`` resources."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from courts_analyst.core.db import Database
from courts_analyst.core.errors import UnknownEditionError
from courts_analyst.core.numbers import round_half_up
from courts_analyst.core.provenance import series_title


class TableEdition(BaseModel):
    edition: str
    table_code: str
    title: str | None
    period_end: str
    url: str | None
    fiscal_years: list[int]
    observations: int


class CatalogOverview(BaseModel):
    editions: list[str]
    tables: list[TableEdition]
    measures: dict[str, str] = Field(description="measure id → label")
    revised_figures: int
    idb: dict[str, Any] | None = Field(
        default=None, description="The loaded IDB release, if any."
    )


def overview(db: Database) -> CatalogOverview:
    tables = [
        TableEdition(
            edition=e,
            table_code=t,
            title=title,
            period_end=str(pe),
            url=url,
            fiscal_years=sorted(fys),
            observations=n,
        )
        for e, t, title, pe, url, fys, n in db.rows(
            "SELECT s.edition, s.table_code, s.title, s.period_end, s.url, "
            "list(DISTINCT o.fiscal_year), count(o.obs_id) "
            "FROM cat.source_file s JOIN cat.observation o USING (file_id) "
            "JOIN cat.edition e ON e.edition = s.edition "
            "GROUP BY ALL ORDER BY min(e.pub_order), s.table_code"
        )
    ]
    measures = dict(db.rows("SELECT measure_id, label FROM cat.measure_def ORDER BY 1"))
    revised = db.one("SELECT count(*) FROM cat.revision_log")
    idb = None
    if db.has_idb:
        rows = db.dicts(
            "SELECT url, last_modified, coverage, fy_from, fy_to, release_rows "
            "FROM idb.idb_release LIMIT 1"
        )
        idb = {k: (str(v) if v is not None else None) for k, v in rows[0].items()}
    return CatalogOverview(
        editions=[
            r[0] for r in db.rows("SELECT edition FROM cat.edition ORDER BY pub_order")
        ],
        tables=tables,
        measures=measures,
        revised_figures=int(revised[0]) if revised else 0,
        idb=idb,
    )


class TableRow(BaseModel):
    measure: str
    court: str
    fiscal_year: int
    value: float | None
    cell_ref: str | None


class PublishedTable(BaseModel):
    edition: str
    series: str | None
    table_code: str
    title: str | None
    period_end: str
    url: str | None
    notes: list[str]
    rows: list[TableRow]


def published_table(db: Database, edition: str, table_code: str) -> PublishedTable:
    head = db.one(
        "SELECT file_id, title, period_end, url FROM cat.source_file "
        "WHERE edition = ? AND table_code = ? AND parsed ORDER BY format = 'xlsx' DESC "
        "LIMIT 1",
        [edition, table_code],
    )
    if head is None:
        have = [
            r[0]
            for r in db.rows(
                "SELECT DISTINCT table_code FROM cat.source_file WHERE edition = ? "
                "AND parsed ORDER BY 1",
                [edition],
            )
        ]
        raise UnknownEditionError(
            f"No table {table_code} in {edition}."
            + (f" Tables in {edition}: {', '.join(have)}." if have else "")
        )
    file_id, title, period_end, url = head
    rows = [
        TableRow(
            measure=m,
            court=c,
            fiscal_year=fy,
            value=None if v is None else round_half_up(v, d or 0),
            cell_ref=ref,
        )
        for m, c, fy, v, d, ref in db.rows(
            "SELECT measure_id, court, fiscal_year, value, decimals, cell_ref "
            "FROM cat.observation WHERE file_id = ? "
            "ORDER BY court, fiscal_year, measure_id",
            [file_id],
        )
    ]
    notes = [
        r[0]
        for r in db.rows("SELECT text FROM cat.footnote WHERE file_id = ?", [file_id])
    ]
    return PublishedTable(
        edition=edition,
        series=series_title(edition),
        table_code=table_code,
        title=title,
        period_end=str(period_end),
        url=url,
        notes=notes,
        rows=rows,
    )


class Revision(BaseModel):
    measure: str
    court: str
    fiscal_year: int
    first_edition: str
    first_value: float
    latest_edition: str
    latest_value: float
    delta: float
    editions: list[str]


def revisions(
    db: Database, measure: str | None = None, court: str | None = None
) -> list[Revision]:
    rows = db.rows(
        "SELECT measure_id, court, fiscal_year, first_edition, first_value, "
        "first_decimals, latest_edition, latest_value, latest_decimals, delta, "
        "editions "
        "FROM cat.revision_log WHERE (? IS NULL OR measure_id = ?) "
        "AND (? IS NULL OR court = ?) ORDER BY measure_id, court, fiscal_year",
        [measure, measure, court, court],
    )
    return [
        Revision(
            measure=m,
            court=c,
            fiscal_year=fy,
            first_edition=fe,
            first_value=round_half_up(fv, fd or 0),
            latest_edition=le,
            latest_value=round_half_up(lv, ld or 0),
            delta=delta,
            editions=list(eds),
        )
        for m, c, fy, fe, fv, fd, le, lv, ld, delta, eds in rows
    ]
