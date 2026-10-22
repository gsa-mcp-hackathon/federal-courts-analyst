"""The request desk over REST (ADR 0013): the three options under an answer,
My requests, the public library, and the statistics office's staff routes.

Same envelopes as the MCP tools (the core's guarded functions), never
cached. Public callers pick a demo account (``X-Desk-Account``); no real
identity is collected. Staff routes need ``X-Desk-Staff-Token`` to match
``DESK_STAFF_TOKEN``; with no token configured the staff side is off. Writes
share a per-client rate limit.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StringConstraints

from courts_analyst.api.common import error_response
from courts_analyst.config import settings
from courts_analyst.core.desk import service as desk
from courts_analyst.core.desk.errors import DeskForbiddenError
from courts_analyst.core.desk.models import (
    ROLE_LABELS,
    Actor,
    CitationIn,
    InquiryTarget,
    Option,
    Outcome,
)
from courts_analyst.core.errors import CoreError
from courts_analyst.http_security import RateLimit
from courts_analyst.tools._common import get_db, get_desk

router = APIRouter(prefix="/desk", tags=["request desk"])

DEMO_ACCOUNTS: dict[str, Actor] = {
    a.account_id: a
    for a in (
        Actor(account_id="priya", name="Priya Shah", role="congressional_staff"),
        Actor(account_id="sam", name="Sam Ortega", role="journalist"),
        Actor(account_id="rae", name="Rae Kim", role="researcher"),
        Actor(account_id="alex", name="Alex Doe", role="public"),
    )
}
"""Sandbox sign-in: pick one. Invented names, no real people."""

STAFF = Actor(
    account_id="office",
    name="Statistics office (simulated)",
    role="statistics_office",
    staff=True,
)

NO_STORE = {"cache-control": "no-store"}

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Key = Annotated[str | None, Field(default=None, max_length=80)]
AccountHeader = Annotated[str | None, Header(alias="x-desk-account", max_length=40)]
StaffHeader = Annotated[str | None, Header(alias="x-desk-staff-token", max_length=200)]


class SubmitBody(BaseModel):
    option: Option
    question: Annotated[Text, StringConstraints(max_length=2000)]
    answer_text: Annotated[Text, StringConstraints(max_length=8000)]
    citations: list[CitationIn] = Field(max_length=60)
    inquiry: InquiryTarget | None = Field(
        default=None, description="Required for 'ask_office': the revised figure."
    )
    idempotency_key: Key = None


class ResponseBody(BaseModel):
    outcome: Outcome
    text: Annotated[Text, StringConstraints(max_length=4000)]
    idempotency_key: Key = None


class PublishBody(BaseModel):
    idempotency_key: Key = None


# ── identity, rate limit, envelopes ──────────────────────────────────────────


def _public(account: str | None) -> Actor:
    actor = DEMO_ACCOUNTS.get(account or "")
    if actor is None:
        raise DeskForbiddenError(
            "Pick a demo account first (X-Desk-Account).", ["GET /api/desk/accounts"]
        )
    return actor


def _staff(token: str | None) -> Actor:
    want = settings.desk_staff_token
    if want is None:
        raise DeskForbiddenError(
            "The staff side is off: set DESK_STAFF_TOKEN to enable it."
        )
    if not token or not secrets.compare_digest(token, want.get_secret_value()):
        raise DeskForbiddenError("Staff token missing or wrong.")
    return STAFF


class _WriteLimiter(RateLimit):
    def __init__(self, per_minute: int) -> None:
        super().__init__(app=None, per_minute=per_minute)  # type: ignore[arg-type]


_limiter: _WriteLimiter | None = None


def _limited(request: Request) -> Response | None:
    global _limiter
    per_minute = settings.http_ask_rate_limit_per_minute
    if per_minute <= 0:
        return None
    if _limiter is None or _limiter.capacity != per_minute:
        _limiter = _WriteLimiter(per_minute)
    wait = _limiter._take(_limiter._key(request.scope))
    if not wait:
        return None
    return JSONResponse(
        {"error": "rate_limited", "retry_after_seconds": int(wait) + 1},
        status_code=429,
        headers={"retry-after": str(int(wait) + 1)},
    )


async def _call(fn: Any, *args: Any, **kwargs: Any) -> Response:
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except CoreError as err:
        resp = error_response(err)
        resp.headers.update(NO_STORE)
        return resp
    return JSONResponse(result.model_dump(mode="json"), headers=NO_STORE)


async def _as(who: Any, fn: Any, *args: Any, **kwargs: Any) -> Response:
    """Resolve the caller (identity errors are envelopes too), then call."""
    try:
        actor = who()
    except CoreError as err:
        return error_response(err)
    return await _call(fn, get_db(), get_desk(), actor, *args, **kwargs)


# ── public ───────────────────────────────────────────────────────────────────


@router.get("/accounts", summary="Demo accounts to sign in with (sandbox)")
async def accounts() -> Response:
    return JSONResponse(
        {
            "accounts": [
                {
                    "id": a.account_id,
                    "name": a.name,
                    "role": a.role,
                    "role_label": ROLE_LABELS[a.role],
                }
                for a in DEMO_ACCOUNTS.values()
            ],
            "staff_enabled": settings.desk_staff_token is not None,
        },
        headers=NO_STORE,
    )


@router.get(
    "/eligibility",
    summary="Whether a figure's revision can go to the statistics office",
)
async def eligibility(
    measure: Annotated[str, Query(max_length=64, pattern=r"^[a-z0-9_]+$")],
    fiscal_year: Annotated[int, Query(ge=1990, le=2030)],
    court: Annotated[str, Query(max_length=16, pattern=r"^[A-Z0-9-]+$")] = "US",
) -> Response:
    return await _call(desk.inquiry_eligibility, get_db(), measure, court, fiscal_year)


@router.post("/requests", summary="One click on an option under an answer")
async def submit(
    request: Request, body: SubmitBody, x_desk_account: AccountHeader = None
) -> Response:
    if (limited := _limited(request)) is not None:
        return limited
    return await _as(
        lambda: _public(x_desk_account),
        desk.submit_option,
        body.option,
        body.question,
        body.answer_text,
        body.citations,
        body.inquiry,
        body.idempotency_key,
    )


@router.get("/requests", summary="My requests, newest first")
async def mine(x_desk_account: AccountHeader = None) -> Response:
    return await _as(lambda: _public(x_desk_account), desk.my_requests)


@router.get("/requests/{request_id}", summary="One of my requests")
async def one(request_id: int, x_desk_account: AccountHeader = None) -> Response:
    return await _as(lambda: _public(x_desk_account), desk.get_request, request_id)


@router.post("/requests/{request_id}/read", summary="Mark a request's updates read")
async def read(request_id: int, x_desk_account: AccountHeader = None) -> Response:
    return await _as(lambda: _public(x_desk_account), desk.mark_read, request_id)


@router.get("/library", summary="Approved answers (public library)")
async def library(
    q: Annotated[str | None, Query(max_length=300)] = None,
    measure: Annotated[str | None, Query(max_length=64)] = None,
    court: Annotated[str | None, Query(max_length=16)] = None,
    fiscal_year: Annotated[int | None, Query(ge=1990, le=2030)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> Response:
    return await _call(
        desk.find_published_answers,
        get_db(),
        get_desk(),
        q,
        measure,
        court,
        fiscal_year,
        limit,
    )


# ── staff (the simulated statistics office) ──────────────────────────────────


@router.get("/staff/inquiries", summary="The statistics office's inquiry queue")
async def staff_inquiries(x_desk_staff_token: StaffHeader = None) -> Response:
    return await _as(lambda: _staff(x_desk_staff_token), desk.inquiry_queue)


@router.get("/staff/requests", summary="All requests (staff)")
async def staff_requests(
    status: Annotated[str | None, Query(max_length=32)] = None,
    x_desk_staff_token: StaffHeader = None,
) -> Response:
    return await _as(lambda: _staff(x_desk_staff_token), desk.all_requests, status)


@router.post(
    "/staff/inquiries/{inquiry_id}/response",
    summary="Record the office's response to an inquiry",
)
async def staff_respond(
    request: Request,
    inquiry_id: int,
    body: ResponseBody,
    x_desk_staff_token: StaffHeader = None,
) -> Response:
    if (limited := _limited(request)) is not None:
        return limited
    return await _as(
        lambda: _staff(x_desk_staff_token),
        desk.record_official_response,
        inquiry_id,
        body.outcome,
        body.text,
        body.idempotency_key,
    )


@router.post(
    "/staff/requests/{request_id}/publish",
    summary="Approve a verified answer into the library",
)
async def staff_publish(
    request: Request,
    request_id: int,
    body: PublishBody | None = None,
    x_desk_staff_token: StaffHeader = None,
) -> Response:
    if (limited := _limited(request)) is not None:
        return limited
    return await _as(
        lambda: _staff(x_desk_staff_token),
        desk.publish_answer,
        request_id,
        body.idempotency_key if body else None,
    )


@router.get("/staff/audit", summary="Every desk write, newest first")
async def staff_audit(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    x_desk_staff_token: StaffHeader = None,
) -> Response:
    return await _as(lambda: _staff(x_desk_staff_token), desk.audit_log, limit)


@router.post(
    "/staff/check-staleness",
    summary="Compare saved citations with the catalog now",
)
async def staff_check(x_desk_staff_token: StaffHeader = None) -> Response:
    try:
        _staff(x_desk_staff_token)
    except CoreError as err:
        return error_response(err)
    return await _call(desk.check_staleness, get_db(), get_desk())
