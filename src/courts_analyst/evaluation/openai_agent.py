"""``openai-api`` answerers: an OpenAI model with this server's tools, under
a hard budget, for the second-model-family comparison (issue #18).

The Responses API with function tools (current OpenAI reasoning models reject
function tools on Chat Completions), turns chained with
``previous_response_id``, capped at ``MAX_TURNS`` requests; the budget is
checked before every request. Same
system prompt and tools as the Claude answerers.
"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from typing import Any

import openai
from fastmcp import Client

from courts_analyst.evaluation.budget import Budget, BudgetExceeded, cost_usd
from courts_analyst.evaluation.mcp_bridge import SYSTEM_PROMPT, call_tool, list_tools
from courts_analyst.evaluation.records import AnswerRecord, ToolCall
from courts_analyst.evaluation.schema import QuestionItem

MAX_TURNS = 8
MAX_OUTPUT_TOKENS = 4096


class OpenAIAnswerer:
    """An OpenAI model via the Responses API, only this MCP server's tools."""

    paid = True

    def __init__(self, model: str = "gpt-5.6-sol", budget: Budget | None = None):
        self.model = model
        self.name = f"openai-api-{model}"
        self.budget = budget or Budget(1.00)
        self._client: openai.OpenAI | None = None

    @property
    def client(self) -> openai.OpenAI:
        """Created on first use, with the key from settings (``.env``)."""
        if self._client is None:
            from courts_analyst.config import settings

            key = settings.openai_api_key
            self._client = openai.OpenAI(
                api_key=key.get_secret_value() if key else None, max_retries=3
            )
        return self._client

    @client.setter
    def client(self, value: openai.OpenAI) -> None:
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
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                    "strict": False,
                }
                for t in await list_tools(client)
            ]
            pending: list[Any] = [{"role": "user", "content": item.question}]
            previous: str | None = None
            try:
                for _ in range(MAX_TURNS):
                    self.budget.check()
                    response = await asyncio.to_thread(
                        functools.partial(
                            self.client.responses.create,
                            model=self.model,
                            instructions=SYSTEM_PROMPT,
                            input=pending,
                            tools=tools,
                            max_output_tokens=MAX_OUTPUT_TOKENS,
                            prompt_cache_key="courts-analyst-eval",
                            previous_response_id=previous,
                        )
                    )
                    previous = response.id
                    u = response.usage
                    prompt = u.input_tokens if u else 0
                    cached = u.input_tokens_details.cached_tokens if u else 0
                    completion = u.output_tokens if u else 0
                    spent = cost_usd(self.model, prompt - cached, completion, cached)
                    self.budget.charge(spent)
                    usage["in"] += prompt
                    usage["out"] += completion
                    usage["cost"] += spent
                    usage["requests"] += 1
                    if response.output_text:
                        final = response.output_text
                    fcalls = [o for o in response.output if o.type == "function_call"]
                    if not fcalls:
                        break
                    pending = []
                    for fc in fcalls:
                        try:
                            args = json.loads(fc.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        t0 = time.perf_counter()
                        out_text, structured, err = await call_tool(
                            client, fc.name, args
                        )
                        calls.append(
                            ToolCall(
                                name=fc.name,
                                arguments=args,
                                output=structured,
                                error=err,
                                latency_s=time.perf_counter() - t0,
                            )
                        )
                        pending.append(
                            {
                                "type": "function_call_output",
                                "call_id": fc.call_id,
                                "output": out_text,
                            }
                        )
                else:
                    error = f"stopped after {MAX_TURNS} model turns"
            except BudgetExceeded as exc:
                error = str(exc)
            except openai.APIStatusError as exc:
                error = f"API error {exc.status_code}: {exc.message}"[:300]
            except openai.APIConnectionError:
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
