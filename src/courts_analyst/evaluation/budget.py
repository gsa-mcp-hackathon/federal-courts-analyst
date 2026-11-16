"""Spending control for paid model runs: a price table and a hard budget.

Every paid answerer charges each API response to a shared :class:`Budget`
and checks it **before** each request. Once a run has spent its limit, no
further request is sent; the remaining questions are recorded as
``answerer_failure: budget exhausted`` instead of silently costing money.
The overshoot is bounded by the requests already in flight (one per worker).

Prices are USD per million tokens, list prices checked 2026-09-27:
Anthropic from the Claude API reference (cache write 1.25× input, cache read
0.1× input); OpenAI from https://developers.openai.com/api/docs/pricing
(for gpt-5.4-mini two readings disagreed, and the higher one is used so the
budget over-counts rather than under-counts). Raw token counts are recorded
with every answer, so costs can be recomputed if a price changes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float


PRICES: dict[str, Price] = {
    # Anthropic
    "claude-sonnet-5": Price(
        input=2.00, output=10.00, cache_read=0.20, cache_write=2.50
    ),
    "claude-opus-5": Price(input=5.00, output=25.00, cache_read=0.50, cache_write=6.25),
    "claude-haiku-4-5": Price(
        input=1.00, output=5.00, cache_read=0.10, cache_write=1.25
    ),
    # OpenAI (cache writes aren't billed separately; reasoning is in output)
    "gpt-5.6-sol": Price(input=2.00, output=10.00, cache_read=0.20, cache_write=2.00),
    "gpt-5.4-mini": Price(input=1.50, output=9.00, cache_read=0.15, cache_write=1.50),
}


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Cost of one response. ``input_tokens`` excludes cached tokens."""
    p = PRICES[model]
    return (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_read_tokens * p.cache_read
        + cache_write_tokens * p.cache_write
    ) / 1_000_000


class BudgetExceeded(RuntimeError):
    """The run has spent its limit; no further requests are sent."""


class Budget:
    """A thread-safe spending limit shared by every worker of one run."""

    def __init__(self, limit_usd: float) -> None:
        if limit_usd <= 0:
            raise ValueError("budget must be positive")
        self.limit_usd = limit_usd
        self._spent = 0.0
        self._requests = 0
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        with self._lock:
            return self._spent

    @property
    def requests(self) -> int:
        with self._lock:
            return self._requests

    def check(self) -> None:
        """Call before every request."""
        with self._lock:
            if self._spent >= self.limit_usd:
                raise BudgetExceeded(
                    f"budget exhausted: ${self._spent:.4f} of ${self.limit_usd:.2f}"
                )

    def charge(self, usd: float) -> None:
        with self._lock:
            self._spent += usd
            self._requests += 1
