"""Typed errors of the request desk. Adapters map them by ``code``."""

from __future__ import annotations

from courts_analyst.core.errors import CoreError


class DeskForbiddenError(CoreError):
    """The caller's role can't do this (a public user calling a staff action,
    or someone else's request)."""

    code = "forbidden"


class DeskNotFoundError(CoreError):
    """No request, inquiry or account with that id."""

    code = "not_found"


class InvalidTransitionError(CoreError):
    """The record isn't in a status that allows this step."""

    code = "invalid_transition"


class NotEligibleError(CoreError):
    """The step isn't allowed for this figure or request (for example an
    inquiry about a revision that a published note already explains)."""

    code = "not_eligible"
