"""Which revisions can go to the statistics office, and where.

An inquiry is about one revision the catalog holds (measure, court, fiscal
year, first edition → latest edition), never free text. It is allowed only
when nothing published explains the revision: pending counts are restated by
every Judicial Business edition as a matter of routine (Table C-1), so those
aren't asked about.
"""

from __future__ import annotations

from courts_analyst.core.catalog import Revision, revisions
from courts_analyst.core.db import Database
from courts_analyst.core.desk.models import Eligibility, Route
from courts_analyst.core.guardrails.vintage import routinely_restated
from courts_analyst.core.measures import get_measure


def find_revision(db: Database, measure: str, court: str, fy: int) -> Revision | None:
    return next((r for r in revisions(db, measure, court) if r.fiscal_year == fy), None)


def route_for(source: str) -> Route:
    """Published tables go to the AO; figures computed from the IDB to the FJC."""
    return "fjc_idb" if source == "idb_derived" else "ao_statistics"


def eligibility(db: Database, measure: str, court: str, fy: int) -> Eligibility:
    get_measure(measure)  # unknown measure → a typed error
    rev = find_revision(db, measure, court, fy)
    base = {"measure": measure, "court": court, "fiscal_year": fy}
    if rev is None:
        return Eligibility(
            eligible=False,
            reason="This figure wasn't revised between editions, so there's nothing "
            "to ask about.",
            **base,
        )
    revision = {
        "from_edition": rev.first_edition,
        "from_value": rev.first_value,
        "to_edition": rev.latest_edition,
        "to_value": rev.latest_value,
    }
    if routinely_restated(measure):
        return Eligibility(
            eligible=False,
            reason="Judicial Business restates the prior year's pending count in "
            "the next edition's Table C-1; the revision is routine and explained.",
            **base,
            **revision,
        )
    return Eligibility(
        eligible=True,
        reason="The figure was revised between editions and no published note "
        "explains why.",
        **base,
        **revision,
    )
