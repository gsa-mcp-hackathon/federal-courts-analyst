"""Pydantic schema for benchmark questions (``eval/questions/*.yaml``).

One item is a question plus everything needed to score an answer to it
deterministically: the figures (value **and** edition) a correct answer must
report, the behaviour it must show (answer, ask, or decline), rule-based
claims over its text and structured tool outputs, and the tools it should
call. Expected figures point at a catalog cell (:class:`CellRef`) so a test
can check every expected value against the official tables.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Suite = Literal["engine", "e2e", "explanation", "tool_selection", "adversarial"]
Split = Literal["dev", "test", "test2"]
Behavior = Literal["answer", "clarify", "decline"]

SUITES: tuple[Suite, ...] = (
    "engine",
    "e2e",
    "explanation",
    "tool_selection",
    "adversarial",
)

HELD_OUT_PERCENT = 30
"""Share of items assigned to the held-out ``test`` split (by hash of the id)."""

_ID = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
EDITION_ID = re.compile(r"^(JB|JFF|FCMS|STFJ|FJCS)-\d{4}$")


def assign_split(item_id: str) -> Split:
    """Deterministic split: the same id lands in the same split on any machine.

    Uses SHA-256 (not Python's salted ``hash``) of the id, so adding, removing
    or reordering other items never moves an item between splits.
    """
    digest = hashlib.sha256(f"split:{item_id}".encode()).hexdigest()
    return "test" if int(digest[:8], 16) % 100 < HELD_OUT_PERCENT else "dev"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CellRef(_Strict):
    """A published figure in the official tables catalog."""

    measure: str
    court: str = "US"
    fiscal_year: int
    edition: str

    @model_validator(mode="after")
    def _edition_format(self) -> CellRef:
        if not EDITION_ID.match(self.edition):
            raise ValueError(f"edition must look like JB-2020: {self.edition!r}")
        return self


class RankingRef(_Strict):
    """The top-N courts on a measure in one edition (recomputed by a test)."""

    measure: str
    fiscal_year: int
    edition: str
    top_n: int = Field(ge=1, le=20)
    order: Literal["desc", "asc"] = "desc"


class ExpectedFigure(_Strict):
    """One number a correct answer must report."""

    value: float
    edition: str | list[str] | None = Field(
        default=None,
        description=(
            "Edition the answer must attribute the value to; a list when the same "
            "printed value appears in several editions (any of them is right); "
            "None = any edition."
        ),
    )
    tolerance: float = Field(
        default=0.0, ge=0, description="Absolute tolerance, in the value's unit."
    )
    tolerance_pct: float | None = Field(
        default=None, ge=0, description="Relative tolerance in percent (engine suite)."
    )
    label: str | None = None
    ref: CellRef | None = None

    @model_validator(mode="after")
    def _ref_matches(self) -> ExpectedFigure:
        for ed in self.editions:
            if not EDITION_ID.match(ed):
                raise ValueError(f"edition must look like JB-2020: {ed!r}")
        if self.ref and self.editions and self.ref.edition not in self.editions:
            raise ValueError("ref.edition is not one of the expected editions")
        return self

    @property
    def editions(self) -> list[str]:
        if self.edition is None:
            return []
        return [self.edition] if isinstance(self.edition, str) else list(self.edition)

    def allowed_error(self) -> float:
        rel = abs(self.value) * (self.tolerance_pct or 0.0) / 100
        return max(self.tolerance, rel)


class EngineQuery(_Strict):
    """What the IDB engine must compute for an ``engine`` item."""

    measure: Literal[
        "civil_cases_filed", "civil_cases_terminated", "civil_cases_pending"
    ]
    court: str = "US"
    fiscal_year: int


ClaimKind = Literal[
    "mentions", "not_mentions", "field", "tool_called", "tool_not_called"
]
FieldOp = Literal["eq", "in", "contains", "exists", "gte", "lte"]


class Claim(_Strict):
    """A rule checked against the answer, never by an LLM.

    - ``mentions`` / ``not_mentions``: case-insensitive phrases in the final
      text. ``any`` = at least one; ``all`` = every one.
    - ``field``: a dotted ``path`` into any structured tool output (``[]``
      steps into lists), compared with ``op``/``value``.
    - ``tool_called`` / ``tool_not_called``: by tool name.
    """

    id: str
    kind: ClaimKind
    any: list[str] | None = None
    all: list[str] | None = None
    path: str | None = None
    op: FieldOp = "eq"
    value: Any = None
    tool: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Claim:
        if self.kind in {"mentions", "not_mentions"} and not (self.any or self.all):
            raise ValueError(f"claim {self.id}: {self.kind} needs `any` or `all`")
        if self.kind == "field" and not self.path:
            raise ValueError(f"claim {self.id}: field claims need `path`")
        if self.kind in {"tool_called", "tool_not_called"} and not self.tool:
            raise ValueError(f"claim {self.id}: {self.kind} needs `tool`")
        return self


class Expected(_Strict):
    """What a correct answer looks like."""

    behavior: Behavior = "answer"
    figures: list[ExpectedFigure] = Field(default_factory=list)
    figures_mode: Literal["all", "any"] = Field(
        default="all",
        description=(
            "'all': every figure must be reported (for example both editions of "
            "an ambiguous question); 'any': one is enough."
        ),
    )
    must_mention_revision: bool = False
    ranking: list[str] | None = Field(
        default=None, description="Court codes a top-N answer must name, in order."
    )
    ranking_ref: RankingRef | None = None
    engine: EngineQuery | None = None


class QuestionItem(_Strict):
    """One benchmark question."""

    id: str
    suite: Suite
    question: str = Field(min_length=10)
    expected: Expected = Field(default_factory=Expected)
    claims: list[Claim] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    acceptable_tools: list[str] = Field(
        default_factory=list,
        description="Other tools that may be called without counting as wrong.",
    )
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    split: Split | None = Field(
        default=None,
        description=(
            "Leave unset (dev/test assigned by hash). "
            "'test2' may be set explicitly for any id to mark it as the fresh "
            "held-out split; any other explicit value must still match assign_split."
        ),
    )

    @model_validator(mode="after")
    def _consistent(self) -> QuestionItem:
        if not _ID.match(self.id):
            raise ValueError(f"id must be lowercase-kebab: {self.id!r}")
        if (
            self.split is not None
            and self.split != "test2"
            and self.split != assign_split(self.id)
        ):
            raise ValueError(
                f"{self.id}: split {self.split!r} doesn't match the hash assignment"
            )
        ids = [c.id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: duplicate claim ids")
        e = self.expected
        if self.suite == "engine" and (e.engine is None or not e.figures):
            raise ValueError(f"{self.id}: engine items need `engine` and `figures`")
        if self.suite == "tool_selection" and not self.expected_tools:
            raise ValueError(f"{self.id}: tool_selection items need expected_tools")
        if (
            self.suite == "adversarial"
            and e.behavior == "answer"
            and not (self.claims or e.figures)
        ):
            raise ValueError(f"{self.id}: an adversarial 'answer' item needs checks")
        if (
            self.suite == "e2e"
            and e.behavior == "answer"
            and not (e.figures or e.ranking or self.claims)
        ):
            raise ValueError(f"{self.id}: e2e items need figures, ranking or claims")
        if self.suite == "explanation" and not self.claims:
            raise ValueError(f"{self.id}: explanation items need claims")
        if e.ranking_ref and e.ranking and len(e.ranking) != e.ranking_ref.top_n:
            raise ValueError(f"{self.id}: ranking length != ranking_ref.top_n")
        return self

    @property
    def resolved_split(self) -> Split:
        return self.split or assign_split(self.id)
