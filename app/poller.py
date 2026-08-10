"""Background loop: poll news -> judge each (article, symbol) with the LLM ->
apply guardrails -> place paper trades -> broadcast everything to the
dashboard over SSE. This is where "fully automatic" actually happens.
"""
from __future__ import annotations

import asyncio
import logging

from app import config, db, events, news_client, signal_engine
from app.broker import broker

log = logging.getLogger(__name__)


def _confidence_to_notional(confidence: float) -> float:
    """Scale position size linearly with confidence: MIN_TRADE_USD right at
    the confidence threshold, up to MAX_TRADE_USD at confidence 1.0."""
    span = max(1.0 - config.MIN_CONFIDENCE, 1e-6)
    normalized = min(max((confidence - config.MIN_CONFIDENCE) / span, 0.0), 1.0)
    return round(config.MIN_TRADE_USD + normalized * (config.MAX_TRADE_USD - config.MIN_TRADE_USD), 2)


async def _handle_verdict(article_id: str, verdict: dict) -> None:
    symbol = verdict["symbol"]
    db.insert_verdict(article_id, symbol, verdict)
    await events.publish({"type": "verdict", "article_id": article_id, "symbol": symbol, **verdict})

    action = verdict["action"]
    confidence = verdict["confidence"]
    reasoning = verdict.get("reasoning", "")

    if action == "hold":
        db.insert_trade(article_id, symbol, "skipped_hold", None, None, reasoning)
        return

    if confidence < config.MIN_CONFIDENCE:
        db.insert_trade(article_id, symbol, "skipped_low_confidence", None, None, reasoning)
        return

    if db.is_in_cooldown(symbol, config.COOLDOWN_MINUTES):
        db.insert_trade(article_id, symbol, "skipped_cooldown", None, None, reasoning)
        return

    tradable = await asyncio.to_thread(broker.is_tradable, symbol)
    if not tradable:
        db.insert_trade(
            article_id, symbol, "skipped_not_tradable", None, None,
            f"{reasoning} (Alpaca doesn't support trading {symbol} -- "
            f"foreign listing, inactive/expired warrant, or otherwise unavailable.)",
        )
        return

    try:
        if action == "buy":
            notional = _confidence_to_notional(confidence)
            result = await asyncio.to_thread(broker.place_notional_order, symbol, "buy", notional)
            db.insert_trade(article_id, symbol, "bought", notional, result.get("order_id"), reasoning)
            db.set_cooldown(symbol)
            await events.publish(
                {"type": "trade", "article_id": article_id, "symbol": symbol,
                 "outcome": "bought", "amount_usd": notional, **result}
            )
        else:  # sell
            qty = await asyncio.to_thread(broker.get_position_qty, symbol)
            if qty <= 0:
                db.insert_trade(article_id, symbol, "skipped_no_position", None, None, reasoning)
                return
            result = await asyncio.to_thread(broker.close_position, symbol)
            db.insert_trade(article_id, symbol, "sold", None, result.get("order_id"), reasoning)
            db.set_cooldown(symbol)
            await events.publish(
                {"type": "trade", "article_id": article_id, "symbol": symbol, "outcome": "sold", **result}
            )
    except Exception as exc:
        log.exception("Order failed for %s", symbol)
        db.insert_trade(article_id, symbol, "error", None, None, f"{reasoning} | order error: {exc}")


async def _process_item(item: dict) -> None:
    if db.article_exists(item["id"]):
        return
    db.insert_news_item(item)
    await events.publish({"type": "news", **item})

    symbols = item.get("symbols") or []
    if not symbols:
        return  # nothing tagged -- no LLM call, nothing to trade
    verdicts = await asyncio.to_thread(signal_engine.judge, symbols, item["headline"], item.get("summary", ""))
    for verdict in verdicts:
        await _handle_verdict(item["id"], verdict)


async def poll_once() -> None:
    try:
        items = await asyncio.to_thread(news_client.get_news)
    except Exception:
        log.exception("Failed to fetch news")
        return
    for item in items:
        await _process_item(item)


async def run_forever() -> None:
    db.init_db()
    while True:
        try:
            await poll_once()
        except Exception:
            log.exception("Poll cycle failed")
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
