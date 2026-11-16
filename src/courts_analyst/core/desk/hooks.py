"""How the read tools see the desk without depending on it.

The adapters register how to reach the desk store at startup. ``revision_notes``
asks :func:`office_response_for` whether the statistics office has answered
an inquiry about a revision; with no store registered (the default, and in
read-only deployments) the answer is always no.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from courts_analyst.core.desk.store import DeskStore

_provider: Callable[[], DeskStore | None] | None = None


@dataclass(frozen=True)
class OfficeResponse:
    outcome: str
    text: str
    created_at: str


def set_store_provider(provider: Callable[[], DeskStore | None] | None) -> None:
    """Register how to reach the desk store. Called lazily, so registering at
    import time opens no file."""
    global _provider
    _provider = provider


def set_active_store(store: DeskStore | None) -> None:
    set_store_provider((lambda: store) if store is not None else None)


def active_store() -> DeskStore | None:
    return _provider() if _provider is not None else None


def office_response_for(measure: str, court: str, fy: int) -> OfficeResponse | None:
    store = active_store()
    if store is None:
        return None
    row = store.one(
        "SELECT r.outcome, r.text, r.created_at FROM response r "
        "JOIN inquiry i ON i.id = r.inquiry_id "
        "WHERE i.measure = ? AND i.court = ? AND i.fiscal_year = ? "
        "ORDER BY r.id DESC LIMIT 1",
        [measure, court, fy],
    )
    return OfficeResponse(str(row[0]), str(row[1]), str(row[2])) if row else None
