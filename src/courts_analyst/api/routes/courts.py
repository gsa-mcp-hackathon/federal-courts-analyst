"""Courts: the registry and a court profile (judgeship context)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from courts_analyst.api.common import cached_json, envelope
from courts_analyst.core.courts import COURTS
from courts_analyst.core.judgeships import JudgeshipContext, judgeship_context
from courts_analyst.core.results import Result
from courts_analyst.tools._common import get_db

router = APIRouter(tags=["courts"])


@router.get("/courts", summary="Every court and aggregate figures exist for")
async def courts(request: Request) -> Response:
    return cached_json(
        request,
        {
            "courts": [
                {
                    "code": c.code,
                    "name": c.name,
                    "citation": c.citation,
                    "level": c.level.value,
                    "circuit": c.circuit,
                    "state": c.state,
                }
                for c in COURTS.values()
            ]
        },
    )


@router.get(
    "/courts/{court}/profile",
    summary="Weighted filings against the Judicial Conference thresholds, and "
    "its latest recommendation (same as judgeship_context)",
    response_model=None,
)
async def profile(
    request: Request,
    court: str,
    fiscal_year: Annotated[int | None, Query(ge=1990, le=2030)] = None,
) -> Response:
    if court not in COURTS:
        return JSONResponse(
            {
                "error": "unknown_court",
                "message": f"Unknown court {court!r}.",
                "suggested_next": ["GET /api/courts for the codes"],
            },
            status_code=404,
        )
    response: Response = await _profile(
        request=request, court=court, fiscal_year=fiscal_year
    )
    return response


@envelope
def _profile(
    request: Request, court: str, fiscal_year: int | None
) -> Result[JudgeshipContext]:
    return judgeship_context(get_db(), court, fiscal_year)
