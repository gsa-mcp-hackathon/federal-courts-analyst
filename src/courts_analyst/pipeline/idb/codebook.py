"""The hand-transcribed IDB codebook (``codebook/*.yaml``) and data breaks.

One YAML file per coded field, transcribed from the FJC civil codebook and
reviewed field by field. Loading validates every file: each code has a label,
codes are unique within a field, validity ranges are ordered, and district
codes map to a canonical court. :func:`load_codebook` is what the loader and
the tests use.
"""

from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from courts_analyst.core.courts import COURTS

CODEBOOK_DIR = Path(__file__).with_name("codebook")
DATA_BREAKS_YAML = Path(__file__).with_name("data_breaks.yaml")


class Code(BaseModel):
    """One code of one field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    label: str = Field(min_length=1)
    group: str | None = None
    category: str | None = None
    line: str | None = None
    court: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    discontinued: bool = False
    unverified: bool = False
    note: str | None = None

    @field_validator("code", mode="before")
    @classmethod
    def _code_is_text(cls, v: object) -> object:
        # YAML reads 110 as an int; codes are compared as text.
        return str(v) if isinstance(v, int) else v

    @model_validator(mode="after")
    def _ordered_validity(self) -> Code:
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError(f"code {self.code}: valid_from after valid_to")
        if self.court is not None and self.court not in COURTS:
            raise ValueError(f"code {self.code}: unknown court {self.court!r}")
        return self


class Field_(BaseModel):
    """One coded IDB field and its codes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    column: str
    title: str
    description: str
    missing: tuple[str, ...] = ()
    codes: tuple[Code, ...]

    @model_validator(mode="after")
    def _unique_codes(self) -> Field_:
        seen: set[str] = set()
        for c in self.codes:
            if c.code in seen:
                raise ValueError(f"{self.field}: duplicate code {c.code!r}")
            seen.add(c.code)
        if overlap := seen & set(self.missing):
            raise ValueError(f"{self.field}: codes also listed as missing {overlap}")
        return self

    def by_code(self) -> dict[str, Code]:
        return {c.code: c for c in self.codes}


BreakKind = Literal["codebook", "new_code", "collection", "policy", "event", "method"]


class DataBreak(BaseModel):
    """A known discontinuity that a trend across ``date`` must account for."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    field: str | None
    codes: tuple[str, ...] = ()
    date: date
    kind: BreakKind
    summary: str
    detail: str
    source: str


@cache
def load_codebook(directory: Path = CODEBOOK_DIR) -> dict[str, Field_]:
    """Every coded field, keyed by field name, validated."""
    fields: dict[str, Field_] = {}
    for path in sorted(directory.glob("*.yaml")):
        f = Field_.model_validate(yaml.safe_load(path.read_text()))
        if f.field != path.stem:
            raise ValueError(f"{path.name}: field {f.field!r} must match file name")
        fields[f.field] = f
    return fields


@cache
def load_data_breaks(path: Path = DATA_BREAKS_YAML) -> tuple[DataBreak, ...]:
    """The data-break registry, validated; ids are unique."""
    items = yaml.safe_load(path.read_text())["breaks"]
    breaks = tuple(DataBreak.model_validate(b) for b in items)
    ids = [b.id for b in breaks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate data-break ids")
    return breaks
