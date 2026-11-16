"""Why a figure changed between two years (same as explain_change)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from courts_analyst.api.common import envelope
from courts_analyst.core.explain import ChangeExplanation, explain_change
from courts_analyst.core.results import Result
from courts_analyst.tools._common import get_db

router = APIRouter(tags=["explain"])

Code = Annotated[str, Query(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


@router.get("/explain-change", summary="Decompose a change between two fiscal years")
@envelope
def explain(
    request: Request,
    measure: Code,
    court: Code = "US",
    fy_from: Annotated[int, Query(alias="from", ge=1990, le=2030)] = 2019,
    fy_to: Annotated[int, Query(alias="to", ge=1990, le=2030)] = 2020,
) -> Result[ChangeExplanation]:
    return explain_change(get_db(), measure, court, fy_from, fy_to)
