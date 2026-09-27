"""Official figures: one figure, a series, a comparison, the revision log."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from courts_analyst.api.common import cached_json, envelope, error_response
from courts_analyst.core import catalog
from courts_analyst.core.errors import CoreError
from courts_analyst.core.official import (
    OfficialFigure,
    compare_courts,
    get_official_figure,
    official_series,
)
from courts_analyst.core.results import Result, clarify
from courts_analyst.tools._common import get_db
from courts_analyst.tools._vocab import AMBIGUOUS

router = APIRouter(tags=["figures"])

FiscalYear = Annotated[int, Query(ge=1990, le=2030)]
Edition = Annotated[str, Query(max_length=32, pattern=r"^[A-Za-z0-9_-]+$")]
Code = Annotated[str, Query(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


@router.get("/figures", summary="One official figure (same as get_official_figure)")
@envelope
def figure(
    request: Request,
    measure: Code,
    fiscal_year: FiscalYear,
    court: Code = "US",
    edition: Edition = "latest",
    period_ending: Code = "september_30",
) -> Result[OfficialFigure]:
    if measure in AMBIGUOUS:
        # REST can't elicit: return the choices, as a non-eliciting MCP client
        # gets them.
        return clarify(AMBIGUOUS[measure], OfficialFigure)
    return get_official_figure(
        get_db(),
        measure,
        court,
        fiscal_year,
        edition,
        period_ending,  # type: ignore[arg-type]
    )


@router.get(
    "/figures/{measure}/{court}/series",
    summary="A measure over several years, never mixing vintages",
)
@envelope
def series(
    request: Request,
    measure: str,
    court: str,
    fy_from: Annotated[int, Query(alias="from", ge=1990, le=2030)],
    fy_to: Annotated[int, Query(alias="to", ge=1990, le=2030)],
    edition: Edition | None = None,
    allow_mixed: bool = False,
) -> Result:  # type: ignore[type-arg]
    return official_series(
        get_db(), measure, court, fy_from, fy_to, edition, allow_mixed
    )


@router.get("/compare", summary="Rank courts on one measure (same as compare_courts)")
@envelope
def compare(
    request: Request,
    measure: Code,
    fiscal_year: FiscalYear,
    courts: Annotated[list[str] | None, Query(max_length=120)] = None,
    edition: Edition = "latest",
    top_n: Annotated[int | None, Query(ge=1, le=120)] = None,
    order: Literal["desc", "asc"] = "desc",
) -> Result:  # type: ignore[type-arg]
    wanted = [c for part in courts or [] for c in part.split(",") if c] or None
    return compare_courts(get_db(), measure, fiscal_year, wanted, edition, top_n, order)


@router.get("/revisions", summary="Figures that changed between editions")
async def revisions(
    request: Request, measure: Code | None = None, court: Code | None = None
) -> Response:
    try:
        rows = catalog.revisions(get_db(), measure, court)
    except CoreError as err:
        return error_response(err)
    return cached_json(
        request, {"revisions": [r.model_dump(mode="json") for r in rows]}
    )
