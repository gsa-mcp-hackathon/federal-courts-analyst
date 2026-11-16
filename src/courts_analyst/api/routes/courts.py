"""Courts: the registry and a court profile (judgeship context)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from courts_analyst.api.common import cached_json, envelope
from courts_analyst.core.cohorts import (
    CohortAnalysis,
    CohortSpec,
    analyze_cohort,
    find_cases,
)
from courts_analyst.core.courts import COURTS
from courts_analyst.core.judgeships import JudgeshipContext, judgeship_context
from courts_analyst.core.reconcile import Reconciliation, reconcile_figure
from courts_analyst.core.results import Result
from courts_analyst.tools._common import get_db, get_store

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
        return _unknown(court)
    response: Response = await _profile(
        request=request, court=court, fiscal_year=fiscal_year
    )
    return response


@envelope
def _profile(
    request: Request, court: str, fiscal_year: int | None
) -> Result[JudgeshipContext]:
    return judgeship_context(get_db(), court, fiscal_year)


FiscalYear = Annotated[int, Query(ge=2015, le=2030)]


@router.get(
    "/courts/{court}/case-mix",
    summary="Share of civil cases filed by case-type group (find_cases + "
    "analyze_cohort share_by_nos_group)",
    response_model=None,
)
async def case_mix(request: Request, court: str, fiscal_year: FiscalYear) -> Response:
    if court not in COURTS:
        return _unknown(court)
    response: Response = await _case_mix(
        request=request, court=court, fiscal_year=fiscal_year
    )
    return response


@envelope
def _case_mix(request: Request, court: str, fiscal_year: int) -> Result[CohortAnalysis]:
    store = get_store()
    spec = CohortSpec(
        courts=None if court == "US" else [court],
        fy_from=fiscal_year,
        fy_to=fiscal_year,
    )
    found = find_cases(get_db(), store, spec)
    if found.status != "ok" or found.data is None:
        return found  # type: ignore[return-value]
    return analyze_cohort(get_db(), store, found.data.handle, "share_by_nos_group")


@router.get(
    "/courts/{court}/reconcile",
    summary="An official count rebuilt from IDB records (same as reconcile)",
    response_model=None,
)
async def reconciliation(
    request: Request,
    court: str,
    fiscal_year: FiscalYear,
    measure: Annotated[
        str, Query(pattern=r"^civil_cases_(filed|terminated|pending)$")
    ] = ("civil_cases_filed"),
) -> Response:
    if court not in COURTS:
        return _unknown(court)
    response: Response = await _reconcile(
        request=request, court=court, fiscal_year=fiscal_year, measure=measure
    )
    return response


@envelope
def _reconcile(
    request: Request, court: str, fiscal_year: int, measure: str
) -> Result[Reconciliation]:
    return reconcile_figure(get_db(), measure, court, fiscal_year)


def _unknown(court: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": "unknown_court",
            "message": f"Unknown court {court!r}.",
            "suggested_next": ["GET /api/courts for the codes"],
        },
        status_code=404,
    )
