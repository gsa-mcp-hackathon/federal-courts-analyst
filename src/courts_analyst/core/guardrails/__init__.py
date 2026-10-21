"""Guardrails: the conclusions the server won't draw, applied in one place.

Every core function that returns data is decorated with :func:`guarded`,
which runs :func:`apply_policies` on its result and turns a policy
:class:`~courts_analyst.core.errors.DeclinedError` into a structured
``declined`` result. MCP tools and the REST API call the same functions, so
the policies apply identically everywhere; ``REGISTRY`` lets a test assert
that no data-returning function skips them.

Policies (one module each):

========================  =================================================
``small_cells``           n < 10 withheld, n < 30 cautioned; complementary
                          suppression so withheld cells can't be recovered
``vintage``               never mix editions in one series silently
``periods``               statistical vs fiscal years; periods not held
``intent``                judge-level, party-name and advocacy requests;
                          neutral wording of the server's own sentences
``pii``                   output scanner over hashed party names (fail closed)
========================  =================================================

``apply_policies`` also checks invariants on every result: inferred
explanations carry ``inferred_not_official``, revised figures carry
``revised_figure``, and results stay inside the output budget. An invariant
the core code broke is a bug; the result is refused, never returned.
"""

from __future__ import annotations

import functools
import json
import logging
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

from pydantic import BaseModel

from courts_analyst.core.courts import COURTS, court_aliases
from courts_analyst.core.db import Database
from courts_analyst.core.errors import (
    DataUnavailableError,
    DeclinedError,
    OutputTooLargeError,
    PolicyViolationError,
)
from courts_analyst.core.guardrails import pii
from courts_analyst.core.guardrails.intent import advocacy_phrases
from courts_analyst.core.guardrails.periods import period_caveats
from courts_analyst.core.guardrails.policy import (
    MAX_RESULT_BYTES,
    SMALL_CELL_SUPPRESS,
    policy_decline,
)
from courts_analyst.core.provenance import series_title
from courts_analyst.core.results import Caveat, Decline, Result, decline

log = logging.getLogger("courts_analyst.guardrails")

P = ParamSpec("P")
R = TypeVar("R", bound=Result[Any])

REGISTRY: dict[str, Callable[..., Any]] = {}
"""Every guarded core function, by ``module.name``."""

_NUMERIC_WHEN_SUPPRESSED = ("value", "n", "share", "ci_low", "ci_high", "breakdown")
_NEUTRAL_FIELDS = ("statement", "headline")


@dataclass(frozen=True)
class PolicyContext:
    """What the policies know about the call."""

    function: str
    db: Database | None = None


# ── invariants over the serialised result ────────────────────────────────────


def _walk(obj: Any) -> typing.Iterator[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _check_cells(payload: dict[str, Any]) -> None:
    for d in _walk(payload.get("data")):
        withheld = d.get("status") == "suppressed" or d.get("suppressed") is True
        if withheld:
            leaked = [k for k in _NUMERIC_WHEN_SUPPRESSED if d.get(k) is not None]
            if leaked:
                raise PolicyViolationError(
                    f"A suppressed cell still carries {', '.join(leaked)}."
                )
        elif {"n", "value", "status"} <= d.keys():
            n = d.get("n")
            if (
                isinstance(n, int)
                and n < SMALL_CELL_SUPPRESS
                and d["value"] is not None
            ):
                raise PolicyViolationError(
                    f"A statistic on {n} cases was not withheld (small-cell rule)."
                )


def _ensure(result: Result[Any], code: str, message: str) -> None:
    if not any(w.code == code for w in result.warnings):
        result.warnings.append(Caveat(code=code, message=message))


def _check_labels(result: Result[Any], payload: dict[str, Any]) -> None:
    if any(d.get("basis") == "inferred" for d in _walk(payload.get("data"))):
        _ensure(
            result,
            "inferred_not_official",
            "Part of this explanation is our inference (basis 'inferred'), not an "
            "official statement; label it as inference.",
        )
    revised = [p for p in result.provenance if p.revision_status == "revised"]
    if revised:
        _ensure(
            result,
            "revised_figure",
            "A figure here was revised between editions; name the edition you quote.",
        )
    for w in period_caveats(p.period for p in result.provenance):
        _ensure(result, w.code, w.message)
    by_measure: dict[str, set[str]] = {}
    for p in result.provenance:
        if p.source == "official_table" and p.edition and series_title(p.edition):
            by_measure.setdefault(p.definition, set()).add(p.edition.split("-")[0])
    if any(len(s) > 1 for s in by_measure.values()) and not any(
        w.code == "mixed_editions" for w in result.warnings
    ):
        raise PolicyViolationError(
            "Values of one measure from Judicial Business and JFF were combined "
            "without a mixed_editions warning."
        )


def _check_neutral(payload: dict[str, Any]) -> None:
    for d in _walk(payload.get("data")):
        for key in _NEUTRAL_FIELDS:
            text = d.get(key)
            if isinstance(text, str) and (bad := advocacy_phrases(text)):
                raise PolicyViolationError(
                    f"Server text argues for an outcome ({bad[0]!r}); it must stay "
                    "neutral."
                )


# ── PII scanner ──────────────────────────────────────────────────────────────


def _scanner(db: Database) -> pii.Scanner:
    path = db.pii_index_path
    if path is None:
        raise pii.PiiIndexError("no PII index configured")
    index = pii.load_index(path)
    cached: pii.Scanner | None = getattr(db, "_pii_scanner", None)
    if cached is None or cached.index is not index:
        names = [c.name for c in COURTS.values()] + [
            c.citation for c in COURTS.values() if c.citation
        ]
        aliases = [a for code in COURTS for a in court_aliases(code)]
        footnotes = [r[0] for r in db.rows("SELECT text FROM cat.footnote")]
        extra = " | ".join(names + aliases + footnotes)
        cached = pii.Scanner(index, extra, boundaries=names)
        db._pii_scanner = cached  # type: ignore[attr-defined]
    return cached


def _scan(
    result: Result[Any], payload: dict[str, Any], ctx: PolicyContext
) -> Decline | None:
    db = ctx.db
    try:
        if db is None or not db.has_idb:
            return None  # no party data is loaded anywhere
    except DataUnavailableError:
        return None  # no data at all (a glossary lookup before `make data`)
    try:
        hits = _scanner(db).hits(payload)
    except pii.PiiIndexError as exc:
        if any(p.source == "idb_derived" for p in result.provenance):
            log.error(
                "pii scanner unavailable; withholding", extra={"function": ctx.function}
            )
            return policy_decline(
                "pii_scanner",
                "The result was withheld because the server's party-name scanner "
                f"isn't available ({exc}); rebuild the IDB with `make data-idb`.",
            )
        return None
    if hits:
        log.warning(
            "pii scanner withheld a result",
            extra={
                "function": ctx.function,
                "matches": [pii.fingerprint(h) for h in hits[:5]],
            },
        )
        return policy_decline("pii_scanner")
    return None


def party_names_in(db: Database | None, text: str) -> bool:
    """Whether ``text`` holds a party name from the IDB index, for checks that
    must run before something is stored (the request desk). Fails closed: with
    the IDB loaded but its index missing, the answer is yes."""
    try:
        if db is None or not db.has_idb:
            return False
    except DataUnavailableError:
        return False
    try:
        return bool(_scanner(db).hits({"text": text}))
    except pii.PiiIndexError:
        return True


# ── entry point ──────────────────────────────────────────────────────────────


def data_type(result: Result[Any]) -> type[BaseModel]:
    """The ``T`` of a ``Result[T]`` instance."""
    ann = type(result).model_fields["data"].annotation
    args = [a for a in typing.get_args(ann) if a is not type(None)]
    if len(args) == 1 and isinstance(args[0], type):
        return args[0]
    raise TypeError(f"Result without a concrete data type: {ann}")


def apply_policies(result: R, ctx: PolicyContext) -> R:
    """Run every policy on ``result``. Returns it (with any added warnings),
    or a ``declined`` result of the same type; raises when an invariant is
    broken or the output budget is exceeded."""
    if result.status != "ok":
        return result
    payload = result.model_dump(mode="json")
    _check_cells(payload)
    _check_labels(result, payload)
    _check_neutral(payload)
    size = len(json.dumps(payload, separators=(",", ":")))
    if size > MAX_RESULT_BYTES:
        raise OutputTooLargeError(
            f"The result is {size:,} bytes, over the {MAX_RESULT_BYTES:,}-byte "
            "budget. Narrow the request (fewer courts, years or groups).",
        )
    if (withheld := _scan(result, payload, ctx)) is not None:
        return decline(withheld, data_type(result))  # type: ignore[return-value]
    seen: set[tuple[str, str]] = set()
    unique = []
    for w in result.warnings:
        if (w.code, w.message) not in seen:
            seen.add((w.code, w.message))
            unique.append(w)
    result.warnings[:] = unique
    return result


def _return_type(fn: Callable[..., Any]) -> type[BaseModel]:
    hint = typing.get_type_hints(fn)["return"]
    meta = getattr(hint, "__pydantic_generic_metadata__", None)
    if meta and meta.get("args"):
        t = meta["args"][0]
        if isinstance(t, type) and issubclass(t, BaseModel):
            return t
    raise TypeError(f"{fn.__qualname__} must be annotated -> Result[Model]")


def guarded(fn: Callable[P, R]) -> Callable[P, R]:
    """Run the guardrail policies on ``fn``'s result and register it."""
    name = f"{fn.__module__}.{fn.__name__}"

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        db = next(
            (a for a in (*args, *kwargs.values()) if isinstance(a, Database)), None
        )
        ctx = PolicyContext(function=name, db=db)
        try:
            result = fn(*args, **kwargs)
        except DeclinedError as err:
            d = err.decline or Decline(
                reason=err.reason,
                message=err.message,
                policy="Server policy.",
            )
            return decline(d, _return_type(fn))  # type: ignore[return-value]
        return apply_policies(result, ctx)

    wrapper.__guarded__ = True  # type: ignore[attr-defined]
    REGISTRY[name] = wrapper
    return wrapper


def is_guarded(fn: Any) -> bool:
    return bool(getattr(fn, "__guarded__", False))


__all__ = [
    "REGISTRY",
    "PolicyContext",
    "apply_policies",
    "guarded",
    "is_guarded",
    "party_names_in",
]
