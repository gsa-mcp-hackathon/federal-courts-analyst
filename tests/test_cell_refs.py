"""Every observation points at the exact cell or PDF line it was read from."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import duckdb
import openpyxl
import pdfplumber

from courts_analyst.pipeline.tables.grid import _lines, _page_words

from .conftest import FIXTURE_RAW

_XLSX_REF = re.compile(r"^(?P<sheet>.+)!(?P<cell>[A-Z]{1,3}\d+)$")
_PDF_REF = re.compile(r"^p(?P<page>\d+):line(?P<line>\d+):col(?P<col>\d+)$")


def _path(url: str, edition: str) -> Path:
    return FIXTURE_RAW / edition / url.rsplit("/", 1)[-1]


@cache
def _workbook(path: Path) -> openpyxl.Workbook:
    return openpyxl.load_workbook(path, data_only=True)


@cache
def _pdf_lines(path: Path, page: int) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return [
            " ".join(w.text for w in ln)
            for ln in _lines(_page_words(pdf.pages[page - 1]))
        ]


def test_every_observation_has_a_resolvable_ref(con: duckdb.DuckDBPyConnection) -> None:
    rows = con.execute(
        """
        SELECT o.cell_ref, o.raw, o.value, s.url, s.edition, s.format
        FROM observation o JOIN source_file s USING (file_id)
        """
    ).fetchall()
    assert rows
    bad: list[str] = []
    for ref, raw, value, url, edition, fmt in rows:
        path = _path(url, edition)
        if fmt == "xlsx":
            m = _XLSX_REF.match(ref)
            if not m:
                bad.append(ref)
                continue
            cell = _workbook(path)[m["sheet"]][m["cell"]].value
            ok = (
                float(cell) == value
                if isinstance(cell, int | float) and value is not None
                else str(cell).strip() == str(raw).strip()
            )
        else:
            m = _PDF_REF.match(ref)
            if not m:
                bad.append(ref)
                continue
            line = _pdf_lines(path, int(m["page"]))[int(m["line"]) - 1]
            ok = raw in line.split()
        if not ok:
            bad.append(f"{edition} {ref} {raw!r}")
    assert bad == [], bad[:10]
