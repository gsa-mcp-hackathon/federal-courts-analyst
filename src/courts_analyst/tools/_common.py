"""What every tool shares: the data connection, the cohort store, error
mapping and the elicitation helper.

Tools stay thin (ADR 0002): validate → call one core function → return its
``Result``. A :class:`~courts_analyst.core.errors.CoreError` becomes a
``ToolError`` whose text says what went wrong and what to call instead, so an
agent sees an actionable message, never a stack trace.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import mcp_types
from fastmcp import Context
from fastmcp.exceptions import ToolError

from courts_analyst.config import settings
from courts_analyst.core.cohorts import CohortStore
from courts_analyst.core.db import Database
from courts_analyst.core.desk.store import DeskStore
from courts_analyst.core.errors import CoreError
from courts_analyst.core.results import Choice, Clarification

P = ParamSpec("P")
R = TypeVar("R")

READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,  # with the same idempotency_key
    "openWorldHint": False,
}
"""Request desk writes (ADR 0013): they add sandbox records, never change or
delete official data."""

_lock = threading.Lock()
_dbs: dict[tuple[Path, Path], Database] = {}
_stores: dict[Path | None, CohortStore] = {}
_desks: dict[Path | None, DeskStore] = {}


def get_db() -> Database:
    """The shared read-only connection for the current settings."""
    key = (settings.resolved_duckdb_path, settings.resolved_idb_path)
    with _lock:
        if key not in _dbs:
            _dbs[key] = Database(*key)
        return _dbs[key]


def get_store() -> CohortStore:
    key = settings.cohort_store_path
    with _lock:
        if key not in _stores:
            _stores[key] = CohortStore(key)
        return _stores[key]


def get_desk() -> DeskStore:
    """The request desk store for the current settings (opened on first use)."""
    key = settings.desk_store_path
    with _lock:
        if key not in _desks:
            _desks[key] = DeskStore(key)
        return _desks[key]


def tool_error(err: CoreError) -> ToolError:
    text = err.message
    if err.suggested_next:
        text += " Next: " + "; ".join(err.suggested_next) + "."
    return ToolError(f"[{err.code}] {text}")


def core_errors(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Turn core errors into helpful tool errors."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except CoreError as err:
            raise tool_error(err) from err

    return wrapper


# ── Elicitation (ADR 0001: three paths, one Clarification model) ────────────

ELICIT_KEY = "clarify"


def _client_can_elicit(ctx: Context) -> bool:
    try:
        params = ctx.session.client_params
    except (RuntimeError, AttributeError):
        return False
    caps = getattr(params, "capabilities", None)
    return bool(caps is not None and getattr(caps, "elicitation", None) is not None)


def _schema(c: Clarification) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "choice": {
                "type": "string",
                "title": c.question,
                "oneOf": [{"const": ch.value, "title": ch.label} for ch in c.choices],
                **({"default": c.default} if c.default else {}),
            }
        },
        "required": ["choice"],
    }


def _modern_answer(ctx: Context, c: Clarification) -> str | None:
    responses = ctx.input_responses or {}
    resp = responses.get(ELICIT_KEY)
    if isinstance(resp, mcp_types.ElicitResult) and resp.action == "accept":
        value = (resp.content or {}).get("choice")
        if isinstance(value, str) and value in {ch.value for ch in c.choices}:
            return value
    return None


async def ask(
    ctx: Context | None, c: Clarification
) -> str | mcp_types.InputRequiredResult | None:
    """Ask the user to pick one of ``c.choices``.

    Returns the chosen value; an ``InputRequiredResult`` to send back (modern
    clients: the client asks the user and retries the call with the answer);
    or ``None`` when the client can't be asked, or the user declined, so the
    tool returns a structured ``needs_clarification`` result instead.
    """
    if ctx is None or not _client_can_elicit(ctx):
        return None
    if ctx._is_modern_protocol():
        if ctx.input_responses is not None:
            return _modern_answer(ctx, c)
        return mcp_types.InputRequiredResult(
            input_requests={
                ELICIT_KEY: mcp_types.ElicitRequest(
                    params=mcp_types.ElicitRequestFormParams(
                        message=c.question, requested_schema=_schema(c)
                    )
                )
            }
        )
    result = await ctx.elicit(
        c.question,
        response_type={ch.value: {"title": ch.label} for ch in c.choices},
    )
    if result.action == "accept" and isinstance(result.data, str):
        return result.data
    return None


# ── Confirming a write (ADR 0013: every desk write is confirmed first) ──────

_CONFIRM_CHOICES = [
    Choice(value="yes", label="Yes, write it"),
    Choice(value="no", label="No, don't"),
]


async def confirmed(
    ctx: Context | None, confirm: bool, question: str
) -> bool | mcp_types.InputRequiredResult:
    """Whether the user agreed to a write. ``confirm=True`` means the caller
    already asked; otherwise ask by elicitation where the client can. A
    client that can't be asked gets a preview and calls again with
    ``confirm=True``."""
    if confirm:
        return True
    c = Clarification(
        parameter="confirm",
        question=question,
        choices=_CONFIRM_CHOICES,
        default="no",
    )
    answer = await ask(ctx, c)
    if isinstance(answer, mcp_types.InputRequiredResult):
        return answer
    return answer == "yes"
