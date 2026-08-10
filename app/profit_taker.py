"""Background loop: independent of the news signal entirely. Periodically
checks every open position's gain *today* and trims a fraction of it the
first time that gain crosses TAKE_PROFIT_PCT, at most once per symbol per
calendar day.

This only calls Alpaca (no news-API quota to worry about), so it runs on
its own, much shorter interval than the news poller.
"""
from __future__ import annotations

import asyncio
import logging

from app import config, db, events
from app.broker import broker

log = logging.getLogger(__name__)


async def _check_position(position: dict) -> None:
    symbol = position["symbol"]
    intraday_pct = position.get("unrealized_intraday_plpc")
    qty = position.get("qty") or 0
    if intraday_pct is None or intraday_pct < config.TAKE_PROFIT_PCT or qty <= 0:
        return

    if db.took_profit_today(symbol):
        return

    sell_qty = round(qty * config.TAKE_PROFIT_SELL_FRACTION, 6)
    if sell_qty <= 0:
        return

    reasoning = (
        f"Up {intraday_pct * 100:.1f}% today (threshold {config.TAKE_PROFIT_PCT * 100:.0f}%) -- "
        f"trimmed {config.TAKE_PROFIT_SELL_FRACTION * 100:.0f}% of the position."
    )
    try:
        result = await asyncio.to_thread(broker.sell_qty, symbol, sell_qty)
        db.insert_trade(None, symbol, "profit_take", None, result.get("order_id"), reasoning)
        db.mark_profit_taken_today(symbol)
        await events.publish(
            {"type": "trade", "article_id": None, "symbol": symbol, "outcome": "profit_take",
             "qty": sell_qty, "reasoning": reasoning, **result}
        )
        log.info("Profit-take trim: %s %s (%.1f%% today)", sell_qty, symbol, intraday_pct * 100)
    except Exception as exc:
        log.exception("Profit-take sell failed for %s", symbol)
        db.insert_trade(None, symbol, "error", None, None, f"profit-take sell error: {exc}")


async def check_once() -> None:
    try:
        positions = await asyncio.to_thread(broker.get_positions)
    except Exception:
        log.exception("Failed to fetch positions for profit-take check")
        return
    for position in positions:
        await _check_position(position)


async def run_forever() -> None:
    if not config.TAKE_PROFIT_ENABLED:
        log.info("Take-profit checker disabled (TAKE_PROFIT_ENABLED=false)")
        return
    while True:
        try:
            await check_once()
        except Exception:
            log.exception("Profit-take check cycle failed")
        await asyncio.sleep(config.TAKE_PROFIT_CHECK_INTERVAL_SECONDS)
