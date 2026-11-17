"""explain_term: definitions of terms, measures and nature-of-suit codes.

Looks in three places, in order: the reviewed glossary
(``core/data/glossary.yaml``), the measures registry, and the IDB codebook's
nature-of-suit codes, by number ("nature of suit 442", "NOS 830", "442") or by
the case type in words ("patent cases", "employment discrimination", "ERISA"),
matched against the codebook labels. A case type returns every matching code
in ``nos_matches``, so a caller never has to guess one. Anything else gets
fuzzy "did you mean" suggestions rather than a guess.

The term is free text, so it is screened first (``core/guardrails/intent``):
a request to rank or name judges, or to name parties, is declined with the
policy and an alternative rather than looked up.
"""

from __future__ import annotations

import difflib
import re
from functools import cache
from importlib import resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from courts_analyst.core.db import Database
from courts_analyst.core.enums import _codebook, nos_entry
from courts_analyst.core.errors import DeclinedError
from courts_analyst.core.guardrails import guarded
from courts_analyst.core.guardrails.intent import screen
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


class NosMatch(BaseModel):
    code: str
    label: str
    group: str


class TermLookup(BaseModel):
    """A definition, or suggestions when the term wasn't recognised."""

    query: str
    found: bool
    definition: TermDefinition | None = None
    nos_matches: list[NosMatch] = Field(
        default_factory=list,
        description="Nature-of-suit codes whose label matches a case type given "
        "in words, best first: pass these to find_cases, never a guessed code.",
    )
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


# Words that say "cases of this type" rather than naming the type.
_FILLER = frozenset(
    [
        "a",
        "an",
        "and",
        "the",
        "of",
        "for",
        "in",
        "on",
        "to",
        "type",
        "types",
        "kind",
        "case",
        "cases",
        "suit",
        "suits",
        "lawsuit",
        "lawsuits",
        "action",
        "actions",
        "claim",
        "claims",
        "filing",
        "filings",
        "filed",
        "litigation",
        "matter",
        "matters",
        "nature",
        "federal",
        "civil",
        "class",
        "infringement",
        "violation",
        "violations",
        "dispute",
        "disputes",
    ]
)
# Common names the codebook labels don't use.
_ALIASES: dict[str, tuple[str, ...]] = {
    "discrimination": ("440", "441", "442", "443", "445", "446"),
    "employment discrimination": ("442",),
    "erisa": ("791",),
    "flsa": ("710",),
    "fmla": ("751",),
    "ada": ("445", "446"),
    "rico": ("470",),
    "tcpa": ("485",),
    "foia": ("895",),
    "apa": ("899",),
    "trade secret": ("880",),
    "trade secrets": ("880",),
    "habeas": ("463", "530", "535"),
    "intellectual property": ("820", "830", "835", "840", "880"),
    "ip": ("820", "830", "835", "840", "880"),
}


def _words(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", s.lower()):
        if w in _FILLER:
            continue
        out.append(
            w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        )
    return out


def _nos_by_label(q: str) -> tuple[list[NosMatch], str | None]:
    """Codes whose codebook label matches the case type ``q``, best first,
    and the Table C-2 group when ``q`` names one."""
    words = _words(q)
    if not words:
        return [], None
    entries = {str(c["code"]): c for c in _codebook("nos")}

    def match(code: str) -> NosMatch:
        e = entries[code]
        return NosMatch(code=code, label=str(e["label"]), group=str(e["group"]))

    def names_group(g: list[str]) -> bool:
        return g == words or (
            len(g) > 1 and g[-1] in ("right", "law") and g[:-1] == words
        )

    for e in entries.values():
        if names_group(_words(str(e["group"]))):
            group = str(e["group"])
            return [match(c) for c, x in entries.items() if x["group"] == group], group
    phrase = " ".join(words)
    alias = _ALIASES.get(phrase) or _ALIASES.get(_norm(q))
    scored: list[tuple[int, int, int, str]] = []
    for code, e in entries.items():
        label = _words(str(e["label"]))
        hits = sum(w in label for w in words)
        if alias and code in alias:
            hits = len(words)
        if hits:
            scored.append((0 if label == words else 1, -hits, len(label), code))
    if not scored:
        return [], None
    scored.sort()
    if scored[0][0] == 0:  # the label is exactly the case type asked about
        return [match(c) for *_, c in scored if -scored[0][1] == len(words)][:1] + [
            match(c) for e, h, _, c in scored[1:] if -h == len(words)
        ], None
    best = -scored[0][1]
    # Every word matched where possible; otherwise the codes matching the most.
    return [match(c) for _, h, _, c in scored if -h == best], None


@guarded
def explain_term(term: str, db: Database | None = None) -> Result[TermLookup]:
    """Define a term, measure or nature-of-suit code; suggest when unsure.

    ``db`` is only used by the output scanner (the term is echoed back)."""
    q = term.strip()
    screening = screen(q)
    if screening.decline is not None:
        raise DeclinedError(
            screening.decline.message,
            screening.decline.reason,
            decline=screening.decline,
        )
    key = _norm(q)
    found: TermDefinition | None = None
    if m := _NOS.match(q.strip()):
        found = _nos(m.group(1))
    if found is None:
        found = _index().get(key)
    matches: list[NosMatch] = []
    if found is None:
        matches, group = _nos_by_label(q)
        if group is not None:
            found = TermDefinition(
                term=group,
                kind="nature_of_suit",
                definition=f"A Table C-2 nature-of-suit group of {len(matches)} codes: "
                + ", ".join(f"{m.code} {m.label}" for m in matches)
                + f". find_cases takes it whole as nos_groups=['{group}'].",
                source="FJC IDB Civil Codebook (NOS); JB-2024 Table C-2",
                nos_group=group,
                related=["nature of suit"],
            )
        elif matches and (len(matches) == 1 or _words(matches[0].label) == _words(q)):
            found = _nos(matches[0].code)
        elif matches:
            found = TermDefinition(
                term=q,
                kind="nature_of_suit",
                definition="Several nature-of-suit codes match: "
                + ", ".join(f"{m.code} {m.label}" for m in matches)
                + ". Use the ones the user means; ask if it isn't clear.",
                source="FJC IDB Civil Codebook (NOS)",
                related=["nature of suit"],
            )
    warnings: list[Caveat] = []
    suggestions: list[str] = []
    if len(matches) > 1 and found is not None and found.nos_code is not None:
        warnings.append(
            Caveat(
                code="inexact_match",
                severity="info",
                message="Several nature-of-suit codes match: "
                + ", ".join(f"{m.code} {m.label}" for m in matches)
                + ". Pass the ones the user means to find_cases.",
            )
        )
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
        query=q,
        found=found is not None,
        definition=found,
        nos_matches=matches,
        did_you_mean=suggestions,
    )
    prov = Provenance(
        source="derived",
        definition="Glossary entry, measure definition or codebook label.",
        note=found.source if found else None,
    )
    return ok(data, [prov], warnings)
