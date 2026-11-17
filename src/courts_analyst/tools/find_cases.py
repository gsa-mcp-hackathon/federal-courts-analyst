"""`find_cases`: define a cohort of IDB civil cases and get its handle."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field, ValidationError

from courts_analyst.core.cohorts import CohortSpec, CohortSummary, find_cases, refine
from courts_analyst.core.enums import (
    CourtCode,
    DispositionGroup,
    JurisdictionGroup,
    NosCategory,
    NosCode,
    NosGroup,
    OriginGroup,
    ProSeGroup,
)
from courts_analyst.core.errors import InvalidCohortError
from courts_analyst.core.results import Result
from courts_analyst.tools._common import READ_ONLY, core_errors, get_db, get_store

DESCRIPTION = """\
Use this when the question needs case-level filters the published tables \
don't have: a case type (nature of suit), origin (for example directly filed \
MDL cases), jurisdiction, disposition, pro se status, class actions or an MDL \
docket, for FY2015–FY2025 civil cases in the FJC Integrated Database. \
"How many employment discrimination cases were filed in N.D. Ill. in FY2024?"

Never guess a nature-of-suit code: for a case type in words ("patent"), get \
the code from explain_term first, then check case_types in the result.

Not for published totals without filters (use get_official_figure: it is \
authoritative) or for rankings (compare_courts).

Returns a cohort handle (coh_…), the count, the label of each \
nature-of-suit code filtered on (case_types) and a small preview (by fiscal \
year, top courts, top case types, MDL share); never case rows or party names. \
Pass the handle to analyze_cohort for medians, outcome rates and trends, or \
to sample_dockets for example dockets. To narrow a cohort, call again with \
parent_handle and the extra filters.

Example: courts=['FL-N'], fy_from=2020, fy_to=2020, origins=['mdl_direct'] → \
202,463 cases, handle coh_1385a2b1481d."""


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="find_cases",
        description=DESCRIPTION,
        annotations={"title": "Find cases (cohort)", **READ_ONLY},
    )
    @core_errors
    async def find_cases_tool(
        fy_from: Annotated[
            int, Field(ge=2015, le=2025, description="First fiscal year.")
        ],
        fy_to: Annotated[int, Field(ge=2015, le=2025, description="Last fiscal year.")],
        courts: Annotated[
            list[CourtCode] | None,
            Field(description="Districts or circuits; omit for all districts."),
        ] = None,
        basis: Annotated[
            Literal["filed", "terminated"],
            Field(description="Cases filed in those years, or terminations in them."),
        ] = "filed",
        nos_codes: Annotated[
            list[NosCode] | None,
            Field(
                description="Nature-of-suit codes the user gave or explain_term "
                "returned, never guessed: e.g. ['442'] employment discrimination, "
                "['830'] patent."
            ),
        ] = None,
        nos_groups: Annotated[
            list[NosGroup] | None,
            Field(description="Table C-2 groups, e.g. ['Civil Rights']."),
        ] = None,
        nos_categories: list[NosCategory] | None = None,
        origins: Annotated[
            list[OriginGroup] | None,
            Field(description="e.g. ['mdl_direct'] for directly filed MDL cases."),
        ] = None,
        exclude_mdl: Annotated[
            bool, Field(description="Drop MDL cases (direct and transferred).")
        ] = False,
        jurisdictions: list[JurisdictionGroup] | None = None,
        dispositions: list[DispositionGroup] | None = None,
        pro_se: list[ProSeGroup] | None = None,
        class_action: bool | None = None,
        mdl_docket: Annotated[
            str | None,
            Field(pattern=r"^\d{1,5}$", description="MDL docket number, e.g. '2885'."),
        ] = None,
        parent_handle: Annotated[
            str | None,
            Field(
                pattern=r"^coh_[0-9a-f]{12}$",
                description="Refine this cohort: its filters plus the ones given.",
            ),
        ] = None,
    ) -> Result[CohortSummary]:
        given = {
            k: v
            for k, v in {
                "fy_from": fy_from,
                "fy_to": fy_to,
                "courts": courts,
                "basis": basis,
                "nos_codes": nos_codes,
                "nos_groups": nos_groups,
                "nos_categories": nos_categories,
                "origins": origins,
                "exclude_mdl": exclude_mdl,
                "jurisdictions": jurisdictions,
                "dispositions": dispositions,
                "pro_se": pro_se,
                "class_action": class_action,
                "mdl_docket": mdl_docket,
            }.items()
            if v is not None
            and not (k == "exclude_mdl" and v is False)
            and not (k == "basis" and v == "filed" and parent_handle)
        }
        if parent_handle:
            return refine(get_db(), get_store(), parent_handle, given)
        try:
            spec = CohortSpec.model_validate(given)
        except ValidationError as exc:
            raise InvalidCohortError("; ".join(e["msg"] for e in exc.errors())) from exc
        return find_cases(get_db(), get_store(), spec)
