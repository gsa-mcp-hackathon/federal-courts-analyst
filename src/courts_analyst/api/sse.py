"""Server-sent events for the agent stream.

Each event is ``id: <seq>``, ``event: <type>``, ``data: <json>``. A comment
line goes out every ``KEEPALIVE_S`` seconds while nothing else does (for
example while a clarification waits for the user), so proxies don't close
the connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from courts_analyst.agent.events import AgentEvent

KEEPALIVE_S = 15.0


def encode(event: AgentEvent) -> str:
    data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"


async def stream(
    events: AsyncIterator[AgentEvent], keepalive_s: float = KEEPALIVE_S
) -> AsyncIterator[str]:
    it = events.__aiter__()
    pending: asyncio.Future[Any] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=keepalive_s)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            finally:
                pending = None
            yield encode(event)
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(BaseException):
                await pending
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            await aclose()
