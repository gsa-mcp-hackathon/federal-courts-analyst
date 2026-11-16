"""Which request statuses can follow which (ADR 0013).

``received → verified → waiting_for_office → office_responded → published``
for *Ask the statistics office*; *Save a verified copy* stops at
``verified``; *Notify me* stays ``watching``. Staff can publish any verified
answer. Anything else is an :class:`InvalidTransitionError`.
"""

from __future__ import annotations

from courts_analyst.core.desk.errors import InvalidTransitionError

ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("received", "verified"),
        ("received", "watching"),
        ("verified", "waiting_for_office"),
        ("verified", "office_responded"),
        ("waiting_for_office", "office_responded"),
        ("verified", "published"),
        ("watching", "published"),
        ("office_responded", "published"),
    }
)

STATUS_LABELS: dict[str, str] = {
    "received": "Received",
    "verified": "Verified answer saved",
    "watching": "Watching for changes",
    "waiting_for_office": "Waiting for statistics office",
    "office_responded": "Statistics office responded",
    "published": "Published to the library",
}


def check(current: str, new: str) -> None:
    """Raise unless ``current → new`` is allowed."""
    if (current, new) not in ALLOWED:
        raise InvalidTransitionError(
            f"A request that is '{STATUS_LABELS.get(current, current)}' can't move "
            f"to '{STATUS_LABELS.get(new, new)}'.",
            ["get the request to see its status"],
        )
