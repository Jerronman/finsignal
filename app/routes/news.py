from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import db, events

router = APIRouter()


@router.get("/news")
async def list_news(limit: int = 50):
    return db.get_recent_activity(limit=limit)


@router.get("/news/stream")
async def stream_news():
    q = events.subscribe()
    return StreamingResponse(events.sse_stream(q), media_type="text/event-stream")
