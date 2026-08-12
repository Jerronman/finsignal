from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from app import db, screener

router = APIRouter()


class RunRequest(BaseModel):
    tickers: list[str] | None = None  # None -> use your watchlist, or the demo list if empty


@router.post("/adam/run")
async def run_screener(body: RunRequest):
    if body.tickers:
        tickers = [t.strip().upper() for t in body.tickers if t.strip()]
    else:
        tickers = await asyncio.to_thread(db.get_watchlist)
        if not tickers:
            tickers = screener.DEFAULT_WATCHLIST

    results = await asyncio.to_thread(screener.screen_stocks, tickers)
    await asyncio.to_thread(db.insert_adam_run, "manual", tickers, results)
    return {"tickers_screened": tickers, "results": results}


@router.get("/adam/default-tickers")
async def default_tickers():
    watchlist = await asyncio.to_thread(db.get_watchlist)
    return {"tickers": watchlist or screener.DEFAULT_WATCHLIST, "source": "watchlist" if watchlist else "demo"}


@router.get("/adam/runs")
async def get_runs(limit: int = 50):
    """Full run history, auto and manual, including runs that found
    nothing -- so the history itself proves the auto-run is alive."""
    return await asyncio.to_thread(db.get_adam_runs, limit)
