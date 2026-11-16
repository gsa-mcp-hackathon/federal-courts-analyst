"""Shared helpers for detecting wxO infrastructure errors.

Imported by both :mod:`wxo_agent` (to tag tool calls at extraction time) and
:mod:`scoring.score` (to catch older records where the error was embedded in
the tool output rather than in ``ToolCall.error``).
"""

from __future__ import annotations

import re

_INFRA_ERROR_PATTERNS = re.compile(
    r"failed to execute function|connection refused",
    re.IGNORECASE,
)


def is_infra_error(text: str) -> bool:
    """Return True when *text* signals a wxO infrastructure error."""
    return bool(_INFRA_ERROR_PATTERNS.search(text))
