"""explain_term: definitions of terms, measures and nature-of-suit codes.

Looks in three places, in order: the reviewed glossary
(``core/data/glossary.yaml``), the measures registry, and the IDB codebook's
nature-of-suit codes ("nature of suit 442", "NOS 830", "442"). Anything else
gets fuzzy "did you mean" suggestions rather than a guess.
"""

from __future__ import annotations

import difflib
import re
from functools import cache
from importlib import resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from courts_analyst.core.enums import nos_entry
from courts_analyst.core.measures import registry
from courts_analyst.core.provenance import Provenance
from courts_analyst.core.results import Caveat, Result, ok

_NOS = re.compile(r"^(?:nature[\s-]+of[\s-]+suit|nos)?\s*(?:code\s*)?#?(\d{3})$", re.I)


class TermDefinition(BaseModel):
    term: str
    kind: Literal["glossary", "measure", "nature_of_suit"]
    definition: str
    source: str
    related: list[str] = Field(default_factory=list)
    measure_id: str | None = None
    nos_code: str | None = None
    nos_group: str | None = None
    nos_category: str | None = None


class TermLookup(BaseModel):
    """A definition, or suggestions when the term wasn't recognised."""

    query: str
    found: bool
    definition: TermDefinition | None = None
    did_you_mean: list[str] = Field(default_factory=list)


@cache
def glossary() -> list[dict[str, Any]]:
    text = resources.files("courts_analyst.core").joinpath("data/glossary.yaml")
    entries: list[dict[str, Any]] = yaml.safe_load(text.read_text())
    return entries


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9.]+", " ", s.lower()).split())


@cache
def _index() -> dict[str, TermDefinition]:
    out: dict[str, TermDefinition] = {}
    for e in glossary():
        d = TermDefinition(
            term=e["term"],
            kind="glossary",
            definition=" ".join(str(e["definition"]).split()),
            source=str(e["source"]),
            related=list(e.get("related", [])),
            measure_id=e.get("see_also") if e.get("see_also") in registry() else None,
        )
        for name in [e["term"], *e.get("aliases", [])]:
            out.setdefault(_norm(str(name)), d)
    for m in registry().values():
        d = TermDefinition(
            term=m.label,
            kind="measure",
            definition=m.definition,
            source="Tables " + ", ".join(m.tables),
            measure_id=m.id,
        )
        for name in (m.label, m.id, m.id.replace("_", " ")):
            out.setdefault(_norm(name), d)
    return out


def _nos(code: str) -> TermDefinition | None:
    e = nos_entry(code)
    if e is None:
        return None
    note = " (discontinued code)" if e.get("discontinued") else ""
    return TermDefinition(
        term=f"Nature of suit {code}",
        kind="nature_of_suit",
        definition=f"{e['label']}{note}. Table C-2 places it under {e['group']} "
        f"({e['category']}).",
        source="FJC IDB Civil Codebook (NOS); JB-2024 Table C-2",
        nos_code=code,
        nos_group=str(e["group"]),
        nos_category=str(e["category"]),
        related=["nature of suit"],
    )


def explain_term(term: str) -> Result[TermLookup]:
    """Define a term, measure or nature-of-suit code; suggest when unsure."""
    q = term.strip()
    key = _norm(q)
    found: TermDefinition | None = None
    if m := _NOS.match(q.strip()):
        found = _nos(m.group(1))
    if found is None:
        found = _index().get(key)
    warnings: list[Caveat] = []
    suggestions: list[str] = []
    if found is None:
        names = list(_index())
        close = difflib.get_close_matches(key, names, n=5, cutoff=0.6)
        close += [n for n in names if key and key in n and n not in close][:5]
        seen: dict[str, None] = {}
        for c in close:
            seen.setdefault(_index()[c].term, None)
        suggestions = list(seen)[:5]
        warnings.append(
            Caveat(
                code="out_of_scope",
                severity="info",
                message=f"No definition for {q!r}."
                + (f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""),
            )
        )
    data = TermLookup(
        query=q, found=found is not None, definition=found, did_you_mean=suggestions
    )
    prov = Provenance(
        source="derived",
        definition="Glossary entry, measure definition or codebook label.",
        note=found.source if found else None,
    )
    return ok(data, [prov], warnings)
