"""``claude-api`` answerers: Claude through the Anthropic API, with this
server's tools, under a hard budget.

A manual tool-use loop (rather than the SDK's tool runner) so every request
can be checked against the budget first and the loop can stop after
``MAX_TURNS``. Tools and the system prompt are identical for every question,
so top-level automatic prompt caching makes later requests read them from
the cache.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import anthropic
from fastmcp import Client

from courts_analyst.evaluation.budget import Budget, BudgetExceeded, cost_usd
from courts_analyst.evaluation.mcp_bridge import SYSTEM_PROMPT, call_tool, list_tools
from courts_analyst.evaluation.records import AnswerRecord, ToolCall
from courts_analyst.evaluation.schema import QuestionItem

MAX_TURNS = 8
MAX_TOKENS = 4096


class AnthropicAnswerer:
    """Claude via the Messages API, only this MCP server's tools."""

    paid = True

    def __init__(self, model: str = "claude-sonnet-5", budget: Budget | None = None):
        self.model = model
        self.name = f"claude-api-{model.removeprefix('claude-')}"
        self.budget = budget or Budget(1.00)
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        """Created on first use, with the key from settings (``.env``)."""
        if self._client is None:
            from courts_analyst.config import settings

            key = settings.anthropic_api_key
            self._client = anthropic.Anthropic(
                api_key=key.get_secret_value() if key else None, max_retries=3
            )
        return self._client

    @client.setter
    def client(self, value: anthropic.Anthropic) -> None:
        self._client = value

    def answer(self, item: QuestionItem) -> AnswerRecord:
        return asyncio.run(self._answer(item))

    async def _answer(self, item: QuestionItem) -> AnswerRecord:
        from courts_analyst.app import mcp

        start = time.perf_counter()
        calls: list[ToolCall] = []
        usage = {"in": 0, "out": 0, "cost": 0.0, "requests": 0}
        final = ""
        error: str | None = None
        async with Client(mcp) as client:
            tools: list[Any] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in await list_tools(client)
            ]
            messages: list[Any] = [{"role": "user", "content": item.question}]
            try:
                for _ in range(MAX_TURNS):
                    self.budget.check()
                    response = await asyncio.to_thread(
                        lambda: self.client.messages.create(
                            model=self.model,
                            max_tokens=MAX_TOKENS,
                            system=SYSTEM_PROMPT,
                            tools=tools,
                            messages=messages,
                            cache_control={"type": "ephemeral"},
                        )
                    )
                    u = response.usage
                    spent = cost_usd(
                        self.model,
                        u.input_tokens,
                        u.output_tokens,
                        u.cache_read_input_tokens or 0,
                        u.cache_creation_input_tokens or 0,
                    )
                    self.budget.charge(spent)
                    usage["in"] += (
                        u.input_tokens
                        + (u.cache_read_input_tokens or 0)
                        + (u.cache_creation_input_tokens or 0)
                    )
                    usage["out"] += u.output_tokens
                    usage["cost"] += spent
                    usage["requests"] += 1
                    text = [b.text for b in response.content if b.type == "text"]
                    if text:
                        final = "\n".join(text)
                    if response.stop_reason == "refusal":
                        error = "model refused"
                        break
                    uses = [b for b in response.content if b.type == "tool_use"]
                    if response.stop_reason != "tool_use" or not uses:
                        break
                    messages.append({"role": "assistant", "content": response.content})
                    results = []
                    for b in uses:
                        args = dict(b.input) if isinstance(b.input, dict) else {}
                        t0 = time.perf_counter()
                        out_text, structured, err = await call_tool(
                            client, b.name, args
                        )
                        calls.append(
                            ToolCall(
                                name=b.name,
                                arguments=args,
                                output=structured,
                                error=err,
                                latency_s=time.perf_counter() - t0,
                            )
                        )
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": b.id,
                                "content": out_text,
                                **({"is_error": True} if err else {}),
                            }
                        )
                    messages.append({"role": "user", "content": results})
                else:
                    error = f"stopped after {MAX_TURNS} model turns"
            except BudgetExceeded as exc:
                error = str(exc)
            except anthropic.APIStatusError as exc:
                error = f"API error {exc.status_code}: {exc.message}"[:300]
            except anthropic.APIConnectionError:
                error = "API connection error"
        return AnswerRecord(
            question_id=item.id,
            answerer=self.name,
            final_text=final,
            tool_calls=calls,
            latency_s=time.perf_counter() - start,
            input_tokens=usage["in"],
            output_tokens=usage["out"],
            cost_usd=usage["cost"],
            model_requests=usage["requests"],
            error=error,
        )
