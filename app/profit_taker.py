"""Background loop: independent of the news signal entirely. Tiered
profit-taking based on gain since YOUR entry price (Alpaca's
unrealized_plpc -- not "today's" move). Each tier sells a fixed fraction
of the ORIGINAL share count once crossed, so by the highest tier the whole
position has been sold off in stages.

Example with the default tiers (5%, 10%, 20%, 50%, each 25% of original):
  up 5%  -> sell 25% of original shares
  up 10% -> sell another 25% of original shares (50% sold total)
  up 20% -> sell another 25% (75% sold total)
  up 50% -> sell whatever's left (100% sold, position fully closed)

If price gaps past several tiers between checks, all newly-crossed tiers
fire in the same pass rather than only the highest one.

"Original" is snapshotted the first time this checker sees an open
position for a symbol -- if more shares are bought later while a plan
already exists, they aren't folded into original_qty until the position
fully closes and a fresh plan starts. See docs (the Strategy tab) for
the full explanation.

Downside is NOT handled here -- no stop-loss yet, deliberately deferred.
"""
from __future__ import annotations

import asyncio
import logging

from app import config, db, events
from app.broker import broker

log = logging.getLogger(__name__)


async def _check_position(position: dict) -> None:
    symbol = position["symbol"]
    qty = position.get("qty") or 0
    gain_pct = position.get("unrealized_plpc")
    if qty <= 0 or gain_pct is None:
        return
    gain_pct *= 100  # Alpaca returns a fraction (0.05 == 5%)

    plan = db.get_profit_take_plan(symbol)
    if plan is None:
        db.create_profit_take_plan(symbol, qty)
        return  # first time seeing this position -- nothing to trim yet

    remaining_qty = qty
    for i, (threshold, fraction) in enumerate(config.TAKE_PROFIT_TIERS):
        if threshold in plan["triggered_tiers"] or gain_pct < threshold:
            continue

        is_last_tier = i == len(config.TAKE_PROFIT_TIERS) - 1
        sell_qty = remaining_qty if is_last_tier else round(plan["original_qty"] * fraction, 6)
        sell_qty = min(sell_qty, remaining_qty)
        if sell_qty <= 0:
            continue

        reasoning = (
            f"Up {gain_pct:.1f}% since entry (crossed the {threshold:g}% tier) -- "
            f"sold {fraction * 100:.0f}% of the original position."
        )
        try:
            result = await asyncio.to_thread(broker.sell_qty, symbol, sell_qty)
            db.insert_trade(None, symbol, "profit_take", None, result.get("order_id"), reasoning)
            db.mark_tier_triggered(symbol, threshold)
            await events.publish(
                {"type": "trade", "article_id": None, "symbol": symbol, "outcome": "profit_take",
                 "qty": sell_qty, "reasoning": reasoning, **result}
            )
            log.info("Profit-take tier %s%%: sold %s %s", threshold, sell_qty, symbol)
            remaining_qty -= sell_qty
        except Exception as exc:
            log.exception("Profit-take sell failed for %s at tier %s", symbol, threshold)
            db.insert_trade(None, symbol, "error", None, None, f"{reasoning} | order error: {exc}")


async def check_once() -> None:
    try:
        positions = await asyncio.to_thread(broker.get_positions)
    except Exception:
        log.exception("Failed to fetch positions for profit-take check")
        return

    open_symbols = {p["symbol"] for p in positions}
    await asyncio.to_thread(db.clear_stale_profit_take_plans, open_symbols)

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
