"""Background loop: runs the Adam screener automatically every 30 minutes,
aligned to wall-clock :00/:30 (UTC) rather than just every 1800s from
whenever the app happened to start. Every run is recorded via
db.insert_adam_run -- including ones that find nothing -- so the run
history itself proves it's actually running, not just silent.

Fully independent of the news signal and of Alpaca -- only touches
yfinance, same as an on-demand run.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app import config, db, screener

log = logging.getLogger(__name__)


def _seconds_until_next_half_hour(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if now.minute < 30:
        next_boundary = now.replace(minute=30, second=0, microsecond=0)
    else:
        next_boundary = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    return max((next_boundary - now).total_seconds(), 0.0)


async def run_once() -> None:
    tickers = await asyncio.to_thread(db.get_watchlist)
    if not tickers:
        tickers = screener.DEFAULT_WATCHLIST
    results = await asyncio.to_thread(screener.screen_stocks, tickers)
    await asyncio.to_thread(db.insert_adam_run, "auto", tickers, results)
    log.info("Adam auto-run: screened %d ticker(s), %d match(es)", len(tickers), len(results))


async def run_forever() -> None:
    if not config.ADAM_AUTO_RUN_ENABLED:
        log.info("Adam auto-run disabled (ADAM_AUTO_RUN_ENABLED=false)")
        return
    while True:
        await asyncio.sleep(_seconds_until_next_half_hour())
        try:
            await run_once()
        except Exception:
            log.exception("Adam auto-run failed")
