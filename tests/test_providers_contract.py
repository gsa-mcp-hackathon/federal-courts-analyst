"""Both model adapters map to the same internal events.

Each SDK (both are on httpx2) talks to a mock HTTP transport that replays a streamed response
in that API's documented wire format (hand-written fixtures, no live
calls). The same logical response (a sentence, then one tool call) must
come out of both as the same sequence of our types, and the requests must
carry what we promised (system prompt, tools, prompt caching, the prior
turn).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
import openai

from courts_analyst.agent.providers.anthropic import AnthropicProvider, to_api_messages
from courts_analyst.agent.providers.base import (
    AssistantTurn,
    Done,
    TextChunk,
    ToolResult,
    ToolResults,
    ToolSpec,
    ToolUse,
    ToolUseRequested,
    UserText,
)
from courts_analyst.agent.providers.openai import OpenAIProvider, pending_input

TOOLS = [
    ToolSpec(
        "get_official_figure",
        "One published statistic.",
        {"type": "object", "properties": {"measure": {"type": "string"}}},
    )
]
ARGS = {"measure": "weighted_civil_filings_per_judgeship", "fiscal_year": 2020}


def _sse(events: list[tuple[str | None, dict[str, Any]]]) -> bytes:
    out = []
    for name, data in events:
        head = f"event: {name}\n" if name else ""
        out.append(f"{head}data: {json.dumps(data)}\n\n")
    return "".join(out).encode()


ANTHROPIC_STREAM = _sse(
    [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_01",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 400,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 800,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Let me "},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "check."},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "get_official_figure",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(ARGS)[:30],
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(ARGS)[30:],
                },
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 42},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
)

_RESPONSE = {
    "id": "resp_01",
    "object": "response",
    "created_at": 1790000000,
    "model": "gpt-5.6-sol",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "id": "msg_01",
            "role": "assistant",
            "status": "completed",
            "content": [
                {"type": "output_text", "text": "Let me check.", "annotations": []}
            ],
        },
        {
            "type": "function_call",
            "id": "fc_01",
            "call_id": "call_01",
            "name": "get_official_figure",
            "arguments": json.dumps(ARGS),
            "status": "completed",
        },
    ],
    "usage": {
        "input_tokens": 1200,
        "input_tokens_details": {"cached_tokens": 800},
        "output_tokens": 42,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 1242,
    },
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
}
OPENAI_STREAM = _sse(
    [
        (
            "response.created",
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**_RESPONSE, "status": "in_progress", "output": []},
            },
        ),
        (
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "sequence_number": 1,
                "item_id": "msg_01",
                "output_index": 0,
                "content_index": 0,
                "delta": "Let me ",
                "logprobs": [],
            },
        ),
        (
            "response.output_text.delta",
            {
                "type": "response.output_text.delta",
                "sequence_number": 2,
                "item_id": "msg_01",
                "output_index": 0,
                "content_index": 0,
                "delta": "check.",
                "logprobs": [],
            },
        ),
        (
            "response.completed",
            {"type": "response.completed", "sequence_number": 3, "response": _RESPONSE},
        ),
    ]
)


def _anthropic(sent: list[dict[str, Any]]) -> AnthropicProvider:
    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=ANTHROPIC_STREAM,
        )

    client = anthropic.AsyncAnthropic(
        api_key="test-key",  # pragma: allowlist secret
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(handler)
        ),
    )
    return AnthropicProvider("claude-sonnet-5", client=client)


def _openai(sent: list[dict[str, Any]]) -> OpenAIProvider:
    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=OPENAI_STREAM
        )

    client = openai.AsyncOpenAI(
        api_key="test-key",  # pragma: allowlist secret
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(handler)
        ),
    )
    return OpenAIProvider("gpt-5.6-sol", client=client)


async def _events(provider: Any, messages: list[Any]) -> list[Any]:
    return [e async for e in provider.stream("SYSTEM", messages, TOOLS, 1000)]


def _shape(events: list[Any]) -> list[Any]:
    """Provider-independent view: types, text, tool name and arguments."""
    out: list[Any] = []
    for e in events:
        if isinstance(e, TextChunk):
            out.append(("text", e.text))
        elif isinstance(e, ToolUseRequested):
            out.append(("tool", e.tool_use.name, e.tool_use.arguments))
        elif isinstance(e, Done):
            out.append(("done", e.stop_reason, e.turn.text, len(e.turn.tool_uses)))
    return out


async def test_same_events_from_both_providers() -> None:
    a_sent: list[dict[str, Any]] = []
    o_sent: list[dict[str, Any]] = []
    a = await _events(_anthropic(a_sent), [UserText("Q?")])
    o = await _events(_openai(o_sent), [UserText("Q?")])
    expected = [
        ("text", "Let me "),
        ("text", "check."),
        ("tool", "get_official_figure", ARGS),
        ("done", "tool_use", "Let me check.", 1),
    ]
    assert _shape(a) == expected
    assert _shape(o) == expected


async def test_usage_is_normalised() -> None:
    a = (await _events(_anthropic([]), [UserText("Q?")]))[-1]
    o = (await _events(_openai([]), [UserText("Q?")]))[-1]
    # Both: 400 uncached + 800 cached input, 42 output.
    for done in (a, o):
        assert done.usage.input_tokens == 400
        assert done.usage.cache_read_tokens == 800
        assert done.usage.total_input == 1200
        assert done.usage.output_tokens == 42


async def test_requests_carry_system_tools_and_caching() -> None:
    a_sent: list[dict[str, Any]] = []
    o_sent: list[dict[str, Any]] = []
    await _events(_anthropic(a_sent), [UserText("Q?")])
    await _events(_openai(o_sent), [UserText("Q?")])
    (a,) = a_sent
    assert a["system"] == "SYSTEM" and a["stream"] is True
    assert a["cache_control"] == {"type": "ephemeral"}
    assert a["tools"][0]["name"] == "get_official_figure"
    assert a["messages"] == [{"role": "user", "content": "Q?"}]
    (o,) = o_sent
    assert o["instructions"] == "SYSTEM" and o["stream"] is True
    assert o["tools"][0] == {
        "type": "function",
        "name": "get_official_figure",
        "description": "One published statistic.",
        "parameters": TOOLS[0].input_schema,
        "strict": False,
    }


async def test_follow_up_turns() -> None:
    """The second request replays the assistant turn and the tool results."""
    a_sent: list[dict[str, Any]] = []
    o_sent: list[dict[str, Any]] = []
    ap, op = _anthropic(a_sent), _openai(o_sent)
    a_done = (await _events(ap, [UserText("Q?")]))[-1]
    o_done = (await _events(op, [UserText("Q?")]))[-1]
    for p, done in ((ap, a_done), (op, o_done)):
        use = done.turn.tool_uses[0]
        await _events(
            p,
            [
                UserText("Q?"),
                done.turn,
                ToolResults([ToolResult(use.id, '{"value":322}')]),
            ],
        )
    msgs = a_sent[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][1]["type"] == "tool_use"
    assert msgs[1]["content"][1]["input"] == ARGS
    assert msgs[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_01", "content": '{"value":322}'}
    ]
    assert o_sent[1]["previous_response_id"] == "resp_01"
    assert o_sent[1]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_01",
            "output": '{"value":322}',
        }
    ]


def test_message_conversion_without_raw_turns() -> None:
    turn = AssistantTurn("Hi", [ToolUse("t1", "server_info", {})])
    msgs = to_api_messages(
        [UserText("Q"), turn, ToolResults([ToolResult("t1", "x", is_error=True)])]
    )
    assert msgs[1]["content"] == [
        {"type": "text", "text": "Hi"},
        {"type": "tool_use", "id": "t1", "name": "server_info", "input": {}},
    ]
    assert msgs[2]["content"][0]["is_error"] is True
    assert pending_input([UserText("Q")]) == (None, [{"role": "user", "content": "Q"}])


async def test_api_errors_are_typed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            529,
            json={
                "type": "error",
                "error": {"type": "overloaded_error", "message": "x"},
            },
        )

    client = anthropic.AsyncAnthropic(
        api_key="k",  # pragma: allowlist secret
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(handler)
        ),
    )
    from courts_analyst.agent.providers.base import ProviderError

    try:
        await _events(AnthropicProvider(client=client), [UserText("Q")])
    except ProviderError as err:
        assert err.code == "model_api_error"
    else:  # pragma: no cover
        raise AssertionError("expected ProviderError")
