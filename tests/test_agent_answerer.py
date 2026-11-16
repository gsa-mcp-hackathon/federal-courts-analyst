"""The agent as an eval answerer: the record the scorer sees, and issue #27
scored for real (the bank's ``adv-one-number-please`` item)."""

from __future__ import annotations

import pytest

from courts_analyst.agent.providers.scripted import ScriptedProvider, Step
from courts_analyst.agent.transcript import AgentAnswerer
from courts_analyst.evaluation.answerers import ANSWERERS, PAID
from courts_analyst.evaluation.bank import load_bank
from courts_analyst.evaluation.scoring.score import score_item

W2020 = {
    "measure": "weighted_civil_filings_per_judgeship",
    "court": "US",
    "fiscal_year": 2020,
}


def _item(item_id: str):  # type: ignore[no-untyped-def]
    return next(i for i in load_bank() if i.id == item_id)


def _answerer(steps: list[Step]) -> AgentAnswerer:
    return AgentAnswerer(provider=ScriptedProvider(steps, model="claude-sonnet-5"))


def test_registered_and_paid() -> None:
    assert {"agent", "agent-openai"} <= set(ANSWERERS)
    assert {"agent", "agent-openai"} <= PAID


async def test_record(server_data: None) -> None:
    a = _answerer([Step("", [("get_official_figure", W2020)]), Step("322 (JFF-2025).")])
    rec = await a.answer_async("q1", "FY2020 weighted civil filings per judgeship?")
    assert rec.answerer == "agent-sonnet-5"
    assert rec.tools_called == ["get_official_figure"]
    assert rec.tool_calls[0].output["data"]["value"] == 322
    assert rec.tool_calls[0].latency_s is not None
    assert rec.final_text.startswith("322 (JFF-2025).")
    assert [(f.value, f.edition) for f in rec.cited_figures] == [(322, "JFF-2025")]
    assert rec.model_requests == 2 and rec.error is None
    # The scripted provider reports tokens; the Sonnet price table applies.
    assert rec.cost_usd and rec.cost_usd > 0
    assert a.prompt_version


async def test_limits_become_answerer_errors(server_data: None) -> None:
    a = _answerer([Step("", [("server_info", {})]) for _ in range(20)])
    rec = await a.answer_async("q1", "What data?")
    assert rec.error == "stopped: max_model_turns"


@pytest.mark.parametrize(
    ("answer", "passes"),
    [
        # What Claude Sonnet actually said in both Phase 6 runs: the agent's
        # citation line now carries the revision.
        ("322 (JFF-2025).", True),
        ("322 (JFF-2025); first published as 554 (JB-2020).", True),
        ("I don't know.", False),
    ],
)
async def test_issue_27_one_number(
    server_data: None, answer: str, passes: bool
) -> None:
    item = _item("adv-one-number-please")
    a = _answerer([Step("", [("get_official_figure", W2020)]), Step(answer)])
    rec = await a.answer_async(item.id, item.question)
    score = score_item(item, rec)
    assert score.correct is passes, (score.checks, rec.final_text)
    if passes:
        assert score.checks["revision"] is True


async def test_declines_score_as_declines(server_data: None) -> None:
    item = next(
        i
        for i in load_bank()
        if i.expected.behavior == "decline" and "judge" in i.question.lower()
    )
    a = _answerer([Step("should not be said")])
    rec = await a.answer_async(item.id, item.question)
    assert rec.model_requests == 0
    assert score_item(item, rec).actual_behavior == "decline"
