"""Typed errors the core raises. Adapters map them to protocol errors.

Every error carries a machine-readable ``code``, a message written for the
person (or agent) who asked, and ``suggested_next`` hints, so an MCP client or
REST caller gets something actionable rather than a stack trace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from courts_analyst.core.results import Decline


class CoreError(Exception):
    """Base class. ``code`` is stable; the message is for humans."""

    code = "core_error"

    def __init__(self, message: str, suggested_next: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.suggested_next = suggested_next or []


class DataUnavailableError(CoreError):
    """A dataset the request needs hasn't been built (run ``make data``)."""

    code = "data_unavailable"


class UnknownCourtError(CoreError, ValueError):
    """A court name that matches no court, or more than one."""

    code = "unknown_court"


class UnknownMeasureError(CoreError):
    code = "unknown_measure"


class UnknownEditionError(CoreError):
    code = "unknown_edition"


class OutOfScopeError(CoreError):
    """The period or court isn't covered by any published table we hold."""

    code = "out_of_scope"


class NotPublishedError(CoreError):
    """The tables don't publish this combination (for example weighted
    filings for a territorial court)."""

    code = "not_published"


class UnknownHandleError(CoreError):
    code = "unknown_handle"


class InvalidCohortError(CoreError):
    code = "invalid_cohort"


class DeclinedError(CoreError):
    """A request the server won't answer by policy (judge rankings, party
    names, tiny cohorts). ``reason`` is a
    :data:`~courts_analyst.core.results.DeclineReason`. Guarded core functions
    turn it into a ``declined`` result (see ``core/guardrails``)."""

    code = "declined"

    def __init__(
        self,
        message: str,
        reason: str,
        suggested_next: list[str] | None = None,
        decline: Decline | None = None,
    ):
        super().__init__(message, suggested_next)
        self.reason = reason
        self.decline = decline


class MixedEditionsError(CoreError):
    """A series would combine values from inconsistent editions (for example
    first-published Judicial Business values with revised JFF values)."""

    code = "mixed_editions"


class PolicyViolationError(CoreError):
    """A result broke a guardrail invariant (a bug). Raised so the result
    never leaves the server: guardrails fail closed."""

    code = "policy_violation"


class QueryTimeoutError(CoreError):
    """A query ran past the server's time limit."""

    code = "timeout"


class OutputTooLargeError(CoreError):
    """A result is larger than the server's output budget."""

    code = "output_too_large"
