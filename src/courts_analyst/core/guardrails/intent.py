"""Request screening: judge-level, party-name and advocacy requests.

MCP tools never see the user's words, so over MCP these policies are
structural (no tool takes a judge or a party, and the data has neither) plus
the server's instructions. Wherever the server *does* get free text (the
glossary lookup, and the agent and REST API in Phase 7), :func:`screen`
classifies it with a small set of patterns. The patterns are measured
against the whole question bank (``tests/test_judge_declines.py``): they must
catch every judge-ranking and party-name item and flag none of the ordinary
questions.

Advocacy isn't declined: the server answers with neutral, sourced facts, and
:func:`screen` returns guidance saying so. :func:`advocacy_phrases` checks the
server's own generated sentences never argue for an outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from courts_analyst.core.guardrails.policy import config, policy_decline
from courts_analyst.core.results import Decline

Intent = Literal["judge_level", "pii", "advocacy"]

# "judge" but not "judgeship(s)", "judgement", "judged".
_J = r"(?:magistrate\s+|district\s+|bankruptcy\s+|senior\s+|chief\s+)?judges?(?![a-z])"
_RANKING = (
    r"(?:rank(?:s|ed|ing)?|fastest|slowest|quickest|best|worst|harshest|"
    r"lenient|reversal\s+rates?|reversed|overturned|productive|efficient)"
)
_JUDGE = [
    re.compile(_RANKING + r"\b[^.?!]{0,60}?\b" + _J, re.I),
    re.compile(r"\b" + _J + r"[^.?!]{0,60}?\b" + _RANKING, re.I),
    re.compile(r"\bwhich\s+" + _J, re.I),
    re.compile(r"\bwho\s+(?:is|are|was)\s+the\s+" + _J, re.I),
    # "by judge", "individual judges"; not "per judge" (loosely, per judgeship).
    re.compile(r"\b(?:by|individual|specific|particular)\s+" + _J, re.I),
    re.compile(r"\bcompar\w*\s+(?:the\s+)?" + _J + r"(?!\s+(?:count|numbers?))", re.I),
    re.compile(r"\bjudge[-\s]shop", re.I),
    re.compile(r"\b" + _J + r"\s+(?:assigned|assignment|profiles?|caseloads?)", re.I),
    # "Judge Alsup's", "Judge Rodney Gilstrap": a title followed by a name.
    re.compile(r"\bJudge\s+[A-Z][a-z]+"),
]
_PARTY = (
    r"(?:plaintiffs?|defendants?|part(?:y|ies)|litigants?|petitioners?|"
    r"respondents?|claimants?|pro\s+se\s+\w+|people|companies|who)"
)
_PII = [
    re.compile(
        r"\b(?:names?|identit(?:y|ies)|identify|contact|address(?:es)?)\b[^.?!]{0,40}?"
        r"\b" + _PARTY,
        re.I,
    ),
    re.compile(r"\b" + _PARTY + r"[’']?\s*names?\b", re.I),
    re.compile(
        r"\b(?:list|show|give|tell)\s+(?:me\s+)?(?:all\s+)?(?:of\s+)?(?:the\s+)?"
        r"(?:plaintiffs|defendants|parties|litigants)\b",
        re.I,
    ),
    re.compile(r"\bwho\s+(?:sued|was\s+sued|filed\s+(?:the|this|that))\b", re.I),
]
_ADVOCACY = [
    re.compile(r"\bshould\s+(?:congress|the\s+senate|lawmakers|we|they)\b", re.I),
    re.compile(
        r"\b(?:prove|argue|make\s+the\s+case|persuade|convince|justify)\b"
        r"[^.?!]{0,80}\b(?:needs?|should|deserves?|more)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:persuasive|op-?ed|advocacy|lobby(?:ing)?|talking\s+points)\b", re.I
    ),
    re.compile(
        r"\b(?:does|do)\b[^.?!]{0,50}\bneed\s+(?:more|additional|new)\s+"
        r"(?:judges|judgeships)\b",
        re.I,
    ),
]


@dataclass(frozen=True)
class Screening:
    """What :func:`screen` found. ``decline`` is set for judge and party
    requests; ``guidance`` for advocacy (answer, but neutrally)."""

    intent: Intent | None
    decline: Decline | None = None
    guidance: str | None = None
    matched: str | None = None


def _first(patterns: list[re.Pattern[str]], text: str) -> str | None:
    for p in patterns:
        if m := p.search(text):
            return m.group(0)
    return None


def screen(text: str) -> Screening:
    """Classify a request. Judge-level wins over party names, which win over
    advocacy."""
    if hit := _first(_JUDGE, text):
        return Screening("judge_level", policy_decline("judge_level"), matched=hit)
    if hit := _first(_PII, text):
        return Screening("pii", policy_decline("pii"), matched=hit)
    if hit := _first(_ADVOCACY, text):
        p = config()["policies"]["advocacy"]
        return Screening(
            "advocacy",
            guidance=" ".join(p["message"].split())
            + " "
            + " ".join(p["alternative"].split()),
            matched=hit,
        )
    return Screening(None)


_ARGUING = re.compile(
    r"\b(?:should|must|ought\s+to)\s+(?:create|add|authorize|get|receive|have|be\s+given)"
    r"|\bneeds?\s+(?:more|additional|new)\s+(?:judges|judgeships)"
    r"|\b(?:we|I)\s+(?:recommend|suggest|urge|believe)"
    r"|\b(?:deserves?|overworked|understaffed|in\s+crisis|clearly\s+needs)\b",
    re.I,
)


def advocacy_phrases(text: str) -> list[str]:
    """Phrases in the server's own text that argue for an outcome."""
    return [m.group(0) for m in _ARGUING.finditer(text)]
