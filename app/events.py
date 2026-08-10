"""Tiny in-memory pub/sub used to push live updates to the dashboard over SSE."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


async def publish(event: dict[str, Any]) -> None:
    for q in list(_subscribers):
        await q.put(event)


async def sse_stream(q: asyncio.Queue) -> AsyncIterator[str]:
    try:
        while True:
            event = await q.get()
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        unsubscribe(q)
