"""Column schema of the civil IDB text file.

Every release header must match a known schema exactly: an added, missing or
reordered column fails the build with the difference spelled out, rather than
shifting values into the wrong fields. A new FJC layout means adding an entry
to :data:`SCHEMAS` after reading the new codebook.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["key", "code", "date", "int", "text", "party", "judge", "unused"]


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    role: Role
    field: str | None = None
    """Codebook field that decodes it (``codebook/<field>.yaml``)."""


CIVIL_1988_ON: tuple[Column, ...] = (
    Column("CIRCUIT", "code", "circuit"),
    Column("DISTRICT", "code", "district"),
    Column("OFFICE", "key"),
    Column("DOCKET", "key"),
    Column("ORIGIN", "code", "origin"),
    Column("FILEDATE", "date"),
    Column("FDATEUSE", "date"),
    Column("JURIS", "code", "juris"),
    Column("NOS", "code", "nos"),
    Column("TITL", "text"),
    Column("SECTION", "text"),
    Column("SUBSECT", "text"),
    Column("RESIDENC", "text"),
    Column("JURY", "code", "jury"),
    Column("CLASSACT", "code", "classact"),
    Column("DEMANDED", "int"),
    Column("FILEJUDG", "judge"),
    Column("FILEMAG", "judge"),
    Column("COUNTY", "text"),
    Column("ARBIT", "code", "arbit"),
    Column("MDLDOCK", "text"),
    Column("PLT", "party"),
    Column("DEF", "party"),
    Column("TRANSDAT", "date"),
    Column("TRANSOFF", "text"),
    Column("TRANSDOC", "text"),
    Column("TRANSORG", "text"),
    Column("TERMDATE", "date"),
    Column("TDATEUSE", "date"),
    Column("TRCLACT", "code", "trclact"),
    Column("TERMJUDG", "judge"),
    Column("TERMMAG", "judge"),
    Column("PROCPROG", "code", "procprog"),
    Column("DISP", "code", "disp"),
    Column("NOJ", "code", "noj"),
    Column("AMTREC", "int"),
    Column("JUDGMENT", "code", "judgment"),
    Column("DJOINED", "unused"),
    Column("PRETRIAL", "unused"),
    Column("TRIBEGAN", "unused"),
    Column("TRIALEND", "unused"),
    Column("TRMARB", "code", "arbit"),
    Column("PROSE", "code", "prose"),
    Column("IFP", "code", "ifp"),
    Column("STATUSCD", "code", "statuscd"),
    Column("TAPEYEAR", "int"),
)
"""Layout of ``cv88on.txt`` as of the 2023-10-25 codebook (46 columns)."""

SCHEMAS: dict[str, tuple[Column, ...]] = {"civil-1988-on": CIVIL_1988_ON}


class SchemaError(ValueError):
    """The file header doesn't match any known schema."""


def match_schema(header: list[str]) -> tuple[str, tuple[Column, ...]]:
    """Return the schema whose columns equal ``header`` exactly, or raise."""
    for name, cols in SCHEMAS.items():
        if [c.name for c in cols] == header:
            return name, cols
    known = [c.name for c in CIVIL_1988_ON]
    added = [h for h in header if h not in known]
    missing = [k for k in known if k not in header]
    detail = []
    if added:
        detail.append(f"unknown columns {added}")
    if missing:
        detail.append(f"missing columns {missing}")
    if not detail:
        detail.append("same columns in a different order")
    raise SchemaError(
        "IDB header matches no known schema: " + "; ".join(detail) + ". Read the "
        "release's codebook and add a schema to pipeline/idb/schema.py."
    )
