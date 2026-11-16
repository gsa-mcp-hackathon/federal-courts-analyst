"""CourtListener: live when a token is configured, a labelled fixture
otherwise, and only ever the read-only, party-free calls we allow.

A fake FastMCP server stands in for https://mcp.courtlistener.com/ (same
tool names and argument shapes as the real one's ``tools/list``), so the
live path is tested without the network or a token.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client, FastMCP
from pydantic import SecretStr

from courts_analyst.agent import mcp_clients
from courts_analyst.agent.events import DocketEvent, ToolResultEvent
from courts_analyst.agent.loop import Agent, transcript_text
from courts_analyst.agent.mcp_clients import (
    SAFE_DOCKET_FIELDS,
    SAFE_FIELDS,
    CourtListenerLive,
    ToolHost,
)
from courts_analyst.agent.providers.scripted import ScriptedProvider, Step

SEARCH = (
    "courtlistener_search_dockets",
    {"court": "flnd", "docket_number": "3:20-cv-00002"},
)


def fake_courtlistener(calls: list[tuple[str, dict[str, Any]]]) -> FastMCP:
    server = FastMCP("fake-courtlistener")

    @server.tool(name="search")
    def search(
        type: str = "o",
        court: str | None = None,
        docket_number: str | None = None,
        fields: list[str] | None = None,
        num_results: int = 20,
        filed_after: str | None = None,
        filed_before: str | None = None,
    ) -> dict[str, Any]:
        calls.append(("search", {"type": type, "court": court,
                                 "docket_number": docket_number, "fields": fields,
                                 "num_results": num_results}))  # fmt: skip
        return {
            "query_id": "q1",
            "results": [
                {
                    "docket_id": 12345,
                    "docketNumber": "3:20-cv-00002",
                    "court_id": "flnd",
                    "dateFiled": "2020-05-11",
                    "suitNature": "Personal Inj. Prod. Liability",
                    "cause": "28:1332 Diversity-Product Liability",
                    "absolute_url": "/docket/12345/smith-v-3m-company/",
                    # Fields we never asked for must not get through.
                    "caseName": "Smith v. 3M Company",
                    "party": ["John Smith"],
                    "attorney": "Jane Doe",
                }
            ],
        }

    @server.tool(name="get_endpoint_item")
    def get_endpoint_item(
        endpoint_id: str, item_id: int | str, fields: list[str] | None = None
    ) -> dict[str, Any]:
        calls.append(("get_endpoint_item", {"endpoint_id": endpoint_id,
                                            "item_id": item_id, "fields": fields}))  # fmt: skip
        return {
            "id": int(item_id),
            "docket_number": "3:20-cv-00002",
            "court_id": "flnd",
            "date_filed": "2020-05-11",
            "case_name": "Smith v. 3M Company",
            "absolute_url": "/docket/12345/smith-v-3m-company/",
        }

    return server


@pytest.fixture
def live_cl(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """A configured token, with the fake server behind the live client."""
    from courts_analyst.config import settings

    calls: list[tuple[str, dict[str, Any]]] = []
    server = fake_courtlistener(calls)
    monkeypatch.setattr(settings, "courtlistener_api_token", SecretStr("t" * 40))

    class Fake(CourtListenerLive):
        def __init__(self, token: str, url: str = "", client: Any = None) -> None:
            super().__init__(token, url, client=Client(server))

    monkeypatch.setattr(mcp_clients, "CourtListenerLive", Fake)
    return calls


async def _run(steps: list[Any], mode: str | bool = "auto") -> list[Any]:
    agent = Agent(ScriptedProvider(steps), courtlistener=mode)
    return [e async for e in agent.run("Show me example cases")]


async def test_no_token_uses_the_fixture_and_says_so(
    server_data: None, no_courtlistener_token: None
) -> None:
    events = await _run([Step("", [SEARCH]), Step("Here are examples.")])
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.server == "courtlistener"
    assert result.result["origin"] == "courtlistener_fixture"
    assert "no COURTLISTENER_API_TOKEN" in result.result["note"]
    assert "synthetic" in result.result["note"]
    cards = [e.card for e in events if isinstance(e, DocketEvent)]
    assert cards and all(c.origin == "courtlistener_fixture" for c in cards)
    assert cards[0].docket_number == "3:20-cv-00002"


async def test_live_path_sends_only_safe_read_only_calls(
    server_data: None, live_cl: list[Any]
) -> None:
    events = await _run(
        [
            Step("", [SEARCH]),
            Step("", [("courtlistener_get_docket", {"docket_id": 12345})]),
            Step("Found it."),
        ]
    )
    assert [c[0] for c in live_cl] == ["search", "get_endpoint_item"]
    search, item = live_cl[0][1], live_cl[1][1]
    assert search["type"] == "d"
    assert search["fields"] == list(SAFE_FIELDS)
    assert search["docket_number"] == "20-cv-00002"
    assert item["endpoint_id"] == "dockets"
    assert item["fields"] == list(SAFE_DOCKET_FIELDS)
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    for r in results:
        assert r.result["origin"] == "courtlistener"
        flat = str(r.result)
        # Party and case names never pass, even when the server sends them.
        assert "Smith" not in flat.replace("smith-v-3m-company", "")
        assert "John" not in flat and "Jane Doe" not in flat
    card = next(e.card for e in events if isinstance(e, DocketEvent))
    assert card.origin == "courtlistener"
    assert card.url == "https://www.courtlistener.com/docket/12345/smith-v-3m-company/"


async def test_unreachable_server_falls_back(
    server_data: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "courtlistener_api_token", SecretStr("t" * 40))

    class Down(CourtListenerLive):
        async def __aenter__(self) -> CourtListenerLive:
            raise ConnectionError("no route to host")

    monkeypatch.setattr(mcp_clients, "CourtListenerLive", Down)
    events = await _run([Step("", [SEARCH]), Step("ok")])
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.result["origin"] == "courtlistener_fixture"
    assert "could not be reached" in result.result["note"]


async def test_failure_mid_turn_falls_back(
    server_data: None, live_cl: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: Any, args: dict[str, Any]) -> list[dict[str, Any]]:
        raise TimeoutError

    monkeypatch.setattr(CourtListenerLive, "search", broken)
    events = await _run([Step("", [SEARCH]), Step("ok")])
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.result["origin"] == "courtlistener_fixture"
    assert "failed during this turn" in result.result["note"]


async def test_fixture_mode_never_calls_out(
    server_data: None, live_cl: list[Any]
) -> None:
    events = await _run([Step("", [SEARCH]), Step("ok")], mode="fixture")
    assert live_cl == []
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.result["origin"] == "courtlistener_fixture"


@pytest.mark.parametrize(
    "args",
    [
        {"court": "flnd", "type": "p"},  # judge search: not an argument we take
        {"court": "flnd", "endpoint_id": "people"},
        {"court": "FLND; DROP"},
        {"court": "flnd", "docket_number": "../../etc"},
        {"court": "flnd", "limit": 500},
        {"court": "flnd", "filed_after": "yesterday"},
        {},
    ],
)
async def test_argument_checks(
    server_data: None, live_cl: list[Any], args: dict[str, Any]
) -> None:
    async with ToolHost(courtlistener="auto") as host:
        out = await host.call("courtlistener_search_dockets", args)
    assert out.error and out.structured is None
    assert live_cl == []


async def test_get_docket_rejects_other_endpoints(
    server_data: None, live_cl: list[Any]
) -> None:
    async with ToolHost(courtlistener="auto") as host:
        bad = await host.call(
            "courtlistener_get_docket", {"docket_id": 1, "endpoint_id": "parties"}
        )
        worse = await host.call("courtlistener_get_docket", {"docket_id": "1 OR 1"})
    assert bad.error and worse.error and live_cl == []


async def test_the_agent_says_when_results_are_cached(
    server_data: None, no_courtlistener_token: None
) -> None:
    def answer(messages: list[Any]) -> Step:
        text = messages[-1].results[0].content
        assert text.startswith("UNTRUSTED third-party data from CourtListener")
        return Step("These are synthetic examples from a cached fixture.")

    events = await _run([Step("", [SEARCH]), answer])
    assert "synthetic" in transcript_text(events)
