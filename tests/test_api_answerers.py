"""Paid API answerers, tested offline: fake model clients, the real MCP server
on the fixture data. No network, no spend."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

import pytest

from courts_analyst.evaluation.anthropic_agent import AnthropicAnswerer
from courts_analyst.evaluation.bank import load_bank
from courts_analyst.evaluation.budget import Budget, BudgetExceeded, cost_usd
from courts_analyst.evaluation.cli import main
from courts_analyst.evaluation.openai_agent import OpenAIAnswerer
from courts_analyst.evaluation.scoring import score_item

ITEM = next(i for i in load_bank() if i.id == "fy2020-weighted-civil-national")
ARGS = {"measure": "weighted_civil_filings_per_judgeship", "fiscal_year": 2020}
FINAL = "322 (JFF-2025), revised from 554 as first published in JB-2020."


def test_cost_math() -> None:
    # 1M uncached input + 1M output on Sonnet 5 = $2 + $10.
    assert cost_usd("claude-sonnet-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert cost_usd("claude-sonnet-5", 0, 0, cache_read_tokens=1_000_000) == (
        pytest.approx(0.2)
    )
    with pytest.raises(KeyError):
        cost_usd("unknown-model", 1, 1)


def test_budget_stops_further_requests() -> None:
    b = Budget(0.01)
    b.check()
    b.charge(0.02)
    assert b.requests == 1 and b.spent_usd == pytest.approx(0.02)
    with pytest.raises(BudgetExceeded, match="budget exhausted"):
        b.check()
    with pytest.raises(ValueError):
        Budget(0)


# ── Anthropic ────────────────────────────────────────────────────────────────


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        usage = NS(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=5000 if self.calls[1:] else 0,
            cache_creation_input_tokens=0 if self.calls[1:] else 5000,
        )
        if len(self.calls) == 1:
            use = NS(type="tool_use", id="tu_1", name="get_official_figure", input=ARGS)
            return NS(content=[use], stop_reason="tool_use", usage=usage)
        return NS(
            content=[NS(type="text", text=FINAL)], stop_reason="end_turn", usage=usage
        )


def test_anthropic_loop(server_data: None) -> None:
    a = AnthropicAnswerer(budget=Budget(1.0))
    fake = FakeMessages()
    a.client = NS(messages=fake)  # type: ignore[assignment]
    rec = a.answer(ITEM)
    assert rec.error is None and rec.final_text == FINAL
    assert [c.name for c in rec.tool_calls] == ["get_official_figure"]
    assert rec.tool_calls[0].output["data"]["value"] == 322  # type: ignore[index]
    assert rec.model_requests == 2 and rec.cost_usd and rec.cost_usd > 0
    first, second = fake.calls
    assert first["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in first["tools"]} >= {"get_official_figure", "find_cases"}
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu_1"
    assert score_item(ITEM, rec).correct


def test_anthropic_respects_budget(server_data: None) -> None:
    a = AnthropicAnswerer(budget=Budget(0.000001))
    a.budget.charge(1.0)
    fake = FakeMessages()
    a.client = NS(messages=fake)  # type: ignore[assignment]
    rec = a.answer(ITEM)
    assert fake.calls == [] and rec.error and "budget exhausted" in rec.error


# ── OpenAI ───────────────────────────────────────────────────────────────────


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> Any:
        import json

        self.calls.append(kw)
        usage = NS(
            input_tokens=6000,
            output_tokens=80,
            input_tokens_details=NS(cached_tokens=5000 if self.calls[1:] else 0),
        )
        if len(self.calls) == 1:
            fc = NS(
                type="function_call",
                call_id="call_1",
                name="get_official_figure",
                arguments=json.dumps(ARGS),
            )
            return NS(id="resp_1", output=[fc], output_text="", usage=usage)
        text = NS(type="message")
        return NS(id="resp_2", output=[text], output_text=FINAL, usage=usage)


def test_openai_loop(server_data: None) -> None:
    o = OpenAIAnswerer(budget=Budget(1.0))
    fake = FakeResponses()
    o.client = NS(responses=fake)  # type: ignore[assignment]
    rec = o.answer(ITEM)
    assert rec.error is None and rec.final_text == FINAL
    assert rec.tool_calls[0].output["data"]["value"] == 322  # type: ignore[index]
    first, second = fake.calls
    assert first["previous_response_id"] is None
    assert second["previous_response_id"] == "resp_1"
    assert second["input"][0]["type"] == "function_call_output"
    assert second["input"][0]["call_id"] == "call_1"
    assert {t["name"] for t in first["tools"]} >= {"get_official_figure"}
    assert rec.cost_usd == pytest.approx(
        cost_usd("gpt-5.6-sol", 6000, 80) + cost_usd("gpt-5.6-sol", 1000, 80, 5000)
    )
    assert score_item(ITEM, rec).correct


# ── CLI guard ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("answerer", ["claude-api", "claude-api-opus", "openai-api"])
def test_paid_answerers_need_the_smoke_set(
    answerer: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--answerer", answerer]) == 2
    assert "--tag smoke" in capsys.readouterr().err
    assert main(["run", "--answerer", answerer, "--suite", "e2e"]) == 2
