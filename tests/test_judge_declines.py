"""No judge-level analysis: structural (no tool can take a judge) and by the
request screen, measured over the whole question bank."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastmcp import Client

from courts_analyst.core.glossary import explain_term
from courts_analyst.core.guardrails.intent import advocacy_phrases, screen

ROOT = Path(__file__).resolve().parents[1]
BANK = sorted((ROOT / "eval" / "questions").glob("*.yaml"))


def _bank() -> list[dict[str, Any]]:
    return [it for f in BANK for it in yaml.safe_load(f.read_text())]


def test_screen_on_the_question_bank() -> None:
    """Recall 1.0 on judge and party-name items, no false positives elsewhere."""
    missed, false_pos = [], []
    for it in _bank():
        tags = set(it.get("tags", []))
        want = (
            "judge_level"
            if "judge_ranking" in tags
            else "pii"
            if "pii" in tags
            else None
        )
        got = screen(it["question"]).intent
        if want and got != want:
            missed.append(it["id"])
        if not want and got in ("judge_level", "pii"):
            false_pos.append(it["id"])
    assert not missed and not false_pos, (missed, false_pos)


JUDGE_REQUESTS = [
    "Rank judges in S.D.N.Y. by time to disposition",
    "Which judge in the Northern District of Florida is the slowest?",
    "Who is the fastest judge in E.D. Tex. for patent cases?",
    "Compare Judge Alsup's docket with other N.D. Cal. judges",
    "Show median time to disposition by judge in D. Del.",
    "Which magistrate judges have the biggest backlogs?",
    "I want to avoid a slow judge; how do I judge-shop in W.D. Tex.?",
    "List individual judges with the highest reversal rates",
]
PARTY_REQUESTS = [
    "List the plaintiffs' names in the 3M earplug MDL.",
    "Give me the names of pro se plaintiffs in D. Md.",
    "Who sued Johnson & Johnson in D.N.J. in FY2023?",
    "What are the defendant names in the sampled dockets?",
]
ORDINARY = [
    "How many authorized judgeships does E.D. Tex. have?",
    "What were weighted filings per judgeship in D. Del. in FY2024?",
    "Rank districts by civil filings per judgeship in FY2025.",
    "How many judges does S.D.N.Y. have?",
    "What is a senior judge?",
    "Is the Judicial Conference's 430 threshold a judgeship standard?",
    "Which districts had the most civil cases filed per judge in FY2020?",
    "What share of cases ended in a judgment for the plaintiff in D. Minn.?",
    "How many cases were filed by pro se plaintiffs in D. Md. in FY2024?",
    "Name the districts with the highest median time to disposition.",
]


@pytest.mark.parametrize("text", JUDGE_REQUESTS)
def test_judge_requests_declined(text: str) -> None:
    s = screen(text)
    assert s.intent == "judge_level" and s.decline is not None
    assert (
        "Judicial Conference" in s.decline.policy
        and "judge-shopping" in s.decline.message
    )
    assert s.decline.alternative and "district" in s.decline.alternative.lower()


@pytest.mark.parametrize("text", PARTY_REQUESTS)
def test_party_requests_declined(text: str) -> None:
    s = screen(text)
    assert s.intent == "pii" and s.decline is not None and s.decline.alternative


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_requests_pass(text: str) -> None:
    assert screen(text).intent is None


def test_advocacy_is_answered_neutrally() -> None:
    s = screen(
        "Should Congress create new judgeships in the Northern District of Florida?"
    )
    assert s.intent == "advocacy" and s.decline is None
    assert s.guidance and "policy decision" in s.guidance
    assert advocacy_phrases("E.D. Tex. clearly needs more judges.")
    assert advocacy_phrases("Congress should create two judgeships.")
    assert not advocacy_phrases(
        "In 2025 the Judicial Conference recommended 2 additional judgeships for it. "
        "This server makes no recommendation of its own."
    )


def test_core_explain_term_declines() -> None:
    r = explain_term("Rank judges in S.D.N.Y. by time to disposition")
    assert r.status == "declined" and r.data is None
    assert r.declined is not None and r.declined.reason == "judge_level"
    assert r.declined.alternative


JUDGEISH = re.compile(r"judge(?!ship)", re.I)


def _properties(schema: dict[str, Any]) -> list[str]:
    out = list(schema.get("properties", {}))
    for sub in schema.get("$defs", {}).values():
        out += list(sub.get("properties", {}))
    return out


def _enum_values(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        vals = [v for v in obj.get("enum", []) if isinstance(v, str)]
        for v in obj.values():
            vals += _enum_values(v)
        return vals
    if isinstance(obj, list):
        return [x for v in obj for x in _enum_values(v)]
    return []


async def test_no_tool_input_can_name_a_judge(client: Client) -> None:
    for tool in await client.list_tools():
        schema = tool.input_schema
        assert not [p for p in _properties(schema) if JUDGEISH.search(p)], tool.name
        assert not [v for v in _enum_values(schema) if JUDGEISH.search(v)], tool.name


async def test_mcp_decline_is_structured(tools: Client) -> None:
    r = await tools.call_tool(
        "explain_term", {"term": "rank judges in S.D.N.Y. by time to disposition"}
    )
    data = r.structured_content
    assert data is not None and data["status"] == "declined" and data["data"] is None
    assert data["declined"]["reason"] == "judge_level"
    assert "compare_courts" in data["declined"]["alternative"]
