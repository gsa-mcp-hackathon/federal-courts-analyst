"""Build synthetic IDB records and zips for unit tests.

Defaults describe a plain federal-question contract case in D. Maine, filed
and terminated in FY2020. Override any column by its IDB name.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from courts_analyst.pipeline.idb.schema import CIVIL_1988_ON

COLUMNS = [c.name for c in CIVIL_1988_ON]

DEFAULTS: dict[str, str] = {
    "CIRCUIT": "1",
    "DISTRICT": "00",
    "OFFICE": "1",
    "DOCKET": "2000001",
    "ORIGIN": "1",
    "FILEDATE": "01/15/2020",
    "FDATEUSE": "01/01/2020",
    "JURIS": "3",
    "NOS": "190",
    "SECTION": "-8",
    "SUBSECT": "-8",
    "RESIDENC": "-8",
    "JURY": "N",
    "CLASSACT": "-8",
    "DEMANDED": "0",
    "COUNTY": "23005",
    "ARBIT": "-8",
    "MDLDOCK": "-8",
    "PLT": "ACME CORP",
    "DEF": "DOE",
    "TRANSOFF": "-8",
    "TRANSDOC": "-8",
    "TRANSORG": "-8",
    "TERMDATE": "06/10/2020",
    "TDATEUSE": "06/01/2020",
    "TRCLACT": "-8",
    "PROCPROG": "2",
    "DISP": "12",
    "NOJ": "0",
    "AMTREC": "0",
    "JUDGMENT": "0",
    "TRMARB": "-8",
    "PROSE": "0",
    "IFP": "-8",
    "STATUSCD": "L",
    "TAPEYEAR": "2020",
}


def row(**overrides: str) -> str:
    unknown = set(overrides) - set(COLUMNS)
    assert not unknown, unknown
    values = {**DEFAULTS, **overrides}
    return "\t".join(values.get(c, "") for c in COLUMNS)


def pending(**overrides: str) -> str:
    """A pending record (no termination, tape year 2099)."""
    base = {
        "TERMDATE": "",
        "TDATEUSE": "",
        "PROCPROG": "-8",
        "DISP": "-8",
        "NOJ": "-8",
        "AMTREC": "",
        "JUDGMENT": "-8",
        "STATUSCD": "S",
        "TAPEYEAR": "2099",
    }
    return row(**{**base, **overrides})


def write_zip(
    path: Path,
    rows: list[str],
    *,
    header: list[str] | None = None,
    raw: bytes | None = None,
) -> Path:
    """An IDB-format zip (CRLF, tab-delimited, member cv88on.txt)."""
    body = raw
    if body is None:
        lines = ["\t".join(header or COLUMNS), *rows]
        body = ("\r\n".join(lines) + "\r\n").encode("latin-1")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("cv88on.txt", body)
    return path
