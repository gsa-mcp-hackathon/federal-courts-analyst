"""Rule-based claim checks over the answer text and structured outputs."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from courts_analyst.core.courts import court_aliases, normalize_court_text
from courts_analyst.core.figures_text import REVISION_WORDS
from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.schema import Claim

_REVISION = REVISION_WORDS


_MARKUP = re.compile(r"\*+|__|`")
"""Markdown emphasis and code marks: "**7** additional" reads as "7 additional"."""


def _plain(text: str) -> str:
    from courts_analyst.evaluation.scoring.behavior import normalize_quotes

    return _MARKUP.sub("", normalize_quotes(text)).lower()


def _has(text: str, phrase: str) -> bool:
    return _plain(phrase) in _plain(text)


def resolve_path(obj: Any, path: str) -> Iterator[Any]:
    """Values at a dotted path; ``name[]`` steps into every list element."""
    parts = path.split(".")

    def walk(node: Any, i: int) -> Iterator[Any]:
        if i == len(parts):
            yield node
            return
        part = parts[i]
        many = part.endswith("[]")
        key = part[:-2] if many else part
        if key:
            if not isinstance(node, dict) or key not in node:
                return
            node = node[key]
        if many:
            if isinstance(node, list):
                for el in node:
                    yield from walk(el, i + 1)
        else:
            yield from walk(node, i + 1)

    yield from walk(obj, 0)


def _compare(actual: Any, op: str, value: Any) -> bool:
    try:
        if op == "exists":
            return actual is not None
        if op == "eq":
            return bool(actual == value)
        if op == "in":
            return actual in value
        if op == "contains":
            if isinstance(actual, str):
                return str(value).lower() in actual.lower()
            return value in actual
        if op == "gte":
            return bool(actual >= value)
        if op == "lte":
            return bool(actual <= value)
    except TypeError:
        return False
    raise ValueError(f"unknown op {op!r}")


def check_claim(claim: Claim, record: AnswerRecord) -> bool:
    text = record.final_text
    if claim.kind == "mentions":
        return all(_has(text, p) for p in claim.all or []) and (
            not claim.any or any(_has(text, p) for p in claim.any)
        )
    if claim.kind == "not_mentions":
        return not any(_has(text, p) for p in [*(claim.any or []), *(claim.all or [])])
    if claim.kind == "field":
        assert claim.path is not None
        return any(
            _compare(v, claim.op, claim.value)
            for out in record.structured_outputs
            for v in resolve_path(out, claim.path)
        )
    called = claim.tool in record.tools_called
    return called if claim.kind == "tool_called" else not called


def mentions_revision(record: AnswerRecord) -> bool:
    """The final text says the figure was revised between editions."""
    return bool(_REVISION.search(record.final_text))


def courts_mentioned_in_order(codes: list[str], text: str) -> tuple[bool, bool]:
    """(every court named, named in the given order) for a top-N answer."""
    norm = f" {normalize_court_text(text)} "
    positions: list[int] = []
    for code in codes:
        found = [
            norm.find(f" {alias} ")
            for alias in court_aliases(code)
            if len(alias) >= 4 and f" {alias} " in norm
        ]
        if not found:
            return False, False
        positions.append(min(found))
    return True, positions == sorted(positions)
