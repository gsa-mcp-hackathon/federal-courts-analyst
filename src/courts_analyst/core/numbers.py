"""Display rounding that matches the published tables.

The judiciary's tables are produced in Excel, which rounds halves away from
zero (458.5 → 459, 20.25 → 20.3). Python's ``round`` rounds halves to even
(458.5 → 458), which would disagree with the printed PDF. Every comparison or
display of a published figure goes through :func:`round_half_up`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(value: float, decimals: int = 0) -> float:
    """Round like the published tables: halves go away from zero.

    Uses the shortest decimal representation of ``value`` (``repr``), so a
    stored 4.05 rounds to 4.1 even though its binary value is 4.04999….
    """
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def fmt(value: float) -> str:
    """A published value for text: thousands separators, no trailing ``.0``."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,}"
