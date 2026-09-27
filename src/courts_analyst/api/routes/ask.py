"""The agent: ``POST /api/ask`` streams one turn as server-sent events;
``POST /api/ask/{turn_id}/clarify`` answers a ``clarify`` event, and the
same stream carries on."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

from courts_analyst.agent.loop import TURNS, Agent
from courts_analyst.agent.providers import make_provider
from courts_analyst.api import sse
from courts_analyst.config import settings
from courts_analyst.http_security import RateLimit

router = APIRouter(tags=["agent"])


class AskRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


class ClarifyAnswer(BaseModel):
    clarify_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]
    choice: str | None = Field(
        default=None, max_length=100, description="A choice's value; null declines."
    )


def default_agent() -> Agent:
    return Agent(
        make_provider(settings.agent_model),
        courtlistener=settings.agent_courtlistener,
        close_provider=True,
    )


class _AskLimiter(RateLimit):
    """The per-client token bucket, used as a check instead of middleware."""

    def __init__(self, per_minute: int) -> None:
        super().__init__(app=None, per_minute=per_minute)  # type: ignore[arg-type]


_limiter: _AskLimiter | None = None


def _ask_wait(request: Request) -> float:
    global _limiter
    per_minute = settings.http_ask_rate_limit_per_minute
    if per_minute <= 0:
        return 0.0
    if _limiter is None or _limiter.capacity != per_minute:
        _limiter = _AskLimiter(per_minute)
    return _limiter._take(_limiter._key(request.scope))


@router.post(
    "/ask",
    summary="Ask the agent; the answer streams as server-sent events",
    response_class=StreamingResponse,
)
async def ask(request: Request, body: AskRequest) -> Response:
    wait = _ask_wait(request)
    if wait:
        return JSONResponse(
            {"error": "rate_limited", "retry_after_seconds": int(wait) + 1},
            status_code=429,
            headers={"retry-after": str(int(wait) + 1)},
        )
    factory: Callable[[], Agent] = getattr(
        request.app.state, "agent_factory", default_agent
    )
    agent = factory()
    return StreamingResponse(
        sse.stream(agent.run(body.question)),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.post(
    "/ask/{turn_id}/clarify",
    summary="Answer a clarify event; the turn's stream resumes",
    status_code=202,
)
async def clarify(turn_id: str, body: ClarifyAnswer) -> Response:
    turn = TURNS.get(turn_id)
    if turn is None:
        return JSONResponse(
            {"error": "unknown_turn", "message": "No such turn in progress."},
            status_code=404,
        )
    if not turn.answer(body.clarify_id, body.choice):
        return JSONResponse(
            {
                "error": "not_waiting",
                "message": "That clarification was already answered or has expired.",
            },
            status_code=409,
        )
    return JSONResponse({"status": "accepted"}, status_code=202)
