"""What the request desk records and returns (ADR 0013).

A request is created only when a user picks one of three options under an
answer: ask the statistics office why a figure changed, save a verified
copy, or get notified if the cited numbers change. Everything here lives in
the sandbox desk store, never in the official catalog.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Option = Literal["ask_office", "verified_copy", "notify"]
Role = Literal[
    "congressional_staff", "journalist", "researcher", "public", "statistics_office"
]
RequestStatus = Literal[
    "received",
    "verified",
    "watching",
    "waiting_for_office",
    "office_responded",
    "published",
]
InquiryStatus = Literal["waiting_for_office", "office_responded"]
Outcome = Literal["confirmed", "corrected"]
Route = Literal["ao_statistics", "fjc_idb"]
UpdateKind = Literal[
    "received",
    "verified",
    "watching",
    "inquiry_filed",
    "inquiry_joined",
    "office_responded",
    "published",
    "figure_revised",
]
GateProblemCode = Literal[
    "empty",
    "unknown_figure",
    "wrong_value",
    "uncited_number",
    "edition_label",
    "mixed_editions",
    "advocacy",
]

OPTION_LABELS: dict[str, str] = {
    "ask_office": "Ask the statistics office why this changed",
    "verified_copy": "Save a verified copy",
    "notify": "Notify me if these numbers change",
}
ROLE_LABELS: dict[str, str] = {
    "congressional_staff": "Congressional staff",
    "journalist": "Journalist",
    "researcher": "Researcher",
    "public": "Member of the public",
    "statistics_office": "Statistics office (simulated)",
}
ROUTE_LABELS: dict[str, str] = {
    "ao_statistics": "AO Statistics Division (uscourts.gov Contact Us)",
    "fjc_idb": "Federal Judicial Center (IDBonline@fjc.gov)",
}
SANDBOX_NOT_SENT = "Sandbox: recorded here, not sent."
OFFICE_LABEL = "Response entered by the simulated statistics office (sandbox)"


class Actor(BaseModel):
    """Who is calling. Demo accounts only: no real identity is collected."""

    account_id: str
    name: str
    role: Role
    staff: bool = False


class CitationIn(BaseModel):
    """One official figure an answer quotes."""

    measure: str = Field(
        description="Measure id, e.g. weighted_civil_filings_per_judgeship."
    )
    court: str = Field(default="US", description="US or a court code such as FL-N.")
    fiscal_year: int = Field(ge=1990, le=2030)
    edition: str = Field(description="Edition id, e.g. JFF-2025 or JB-2020.")
    value: float = Field(description="The value as quoted in the answer.")


class InquiryTarget(BaseModel):
    """The figure whose revision the asker wants explained."""

    measure: str
    court: str = "US"
    fiscal_year: int = Field(ge=1990, le=2030)


class CheckedCitation(CitationIn):
    """A citation the gate matched to the catalog."""

    measure_label: str
    table_code: str
    latest_value: float
    latest_edition: str
    revised: bool = Field(description="Editions print different values for it.")
    historical: bool = Field(
        default=False,
        description="Quoted as an earlier edition's value, in a sentence that says "
        "so; left out of the consistency check.",
    )


class GateProblem(BaseModel):
    """Why the gate refused an answer, and what to do instead."""

    code: GateProblemCode
    message: str
    number: str | None = Field(default=None, description="The number as written.")
    fix: str | None = None


class GateReport(BaseModel):
    """The verification gate's verdict on one answer."""

    passed: bool
    problems: list[GateProblem] = Field(default_factory=list)
    citations: list[CheckedCitation] = Field(default_factory=list)
    edition_basis: list[str] = Field(
        default_factory=list, description="Editions the answer's figures come from."
    )
    numbers_checked: int = 0


class UpdateView(BaseModel):
    """One entry in the asker's My requests inbox."""

    id: int
    kind: UpdateKind
    text: str
    created_at: str
    read: bool


class ResponseView(BaseModel):
    outcome: Outcome
    text: str
    entered_by: str
    created_at: str
    label: str = OFFICE_LABEL


class InquiryView(BaseModel):
    """One question to the statistics office about one revision."""

    id: int
    measure: str
    measure_label: str
    court: str
    court_name: str
    fiscal_year: int
    from_edition: str
    from_value: float
    to_edition: str
    to_value: float
    route: Route
    route_label: str
    status: InquiryStatus
    waiting_requests: int = Field(description="Requests attached to this inquiry.")
    created_at: str
    response: ResponseView | None = None
    delivery: str = SANDBOX_NOT_SENT


class AnswerView(BaseModel):
    version: int
    text: str
    citations: list[CheckedCitation]
    edition_basis: list[str]
    verified_at: str
    stamp: str = Field(description="The line to quote with the answer.")


class RequestView(BaseModel):
    id: int
    option: Option
    option_label: str
    question: str
    asker_name: str
    asker_role: Role
    status: RequestStatus
    created_at: str
    updated_at: str
    answer: AnswerView | None = None
    inquiry: InquiryView | None = None
    updates: list[UpdateView] = Field(default_factory=list)
    unread: int = 0
    needs_reverification: bool = False
    published: bool = False


class DeskOutcome(BaseModel):
    """What a desk write did. ``preview`` means nothing was written yet."""

    written: bool
    preview: bool = False
    message: str
    request: RequestView | None = None
    inquiry: InquiryView | None = None
    gate: GateReport | None = None


class RequestList(BaseModel):
    requests: list[RequestView]
    unread_total: int


class InquiryQueue(BaseModel):
    """The statistics office's queue, one row per revision."""

    inquiries: list[InquiryView]


class Eligibility(BaseModel):
    """Whether a figure's revision can be sent to the statistics office."""

    eligible: bool
    reason: str
    measure: str
    court: str
    fiscal_year: int
    from_edition: str | None = None
    from_value: float | None = None
    to_edition: str | None = None
    to_value: float | None = None
    existing_inquiry: int | None = None


class LibraryEntryView(BaseModel):
    id: int
    request_id: int
    question: str
    answer: AnswerView
    inquiry: InquiryView | None = None
    published_at: str
    needs_reverification: bool = Field(
        description="A newer edition revised a figure this answer cites."
    )


class LibraryResults(BaseModel):
    entries: list[LibraryEntryView]
    query: str | None = None


class AuditEventView(BaseModel):
    id: int
    at: str
    actor: str
    tool: str
    record: str
    before: str | None
    after: str | None


class AuditLog(BaseModel):
    events: list[AuditEventView]


class StalenessReport(BaseModel):
    citations_checked: int
    library_entries_flagged: int
    updates_created: int
