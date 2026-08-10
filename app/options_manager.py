"""Background loop: manages open option positions, independent of the news
signal entirely. Two jobs each cycle:

1. Tiered profit-taking (the same ratchet mechanic used for stocks) based
   on gain since entry -- Alpaca's unrealized_plpc on the option position
   itself. Each tier sells a fixed fraction of the ORIGINAL contract count.
2. Force-close any position by the Thursday before its OWN expiration,
   regardless of P&L -- never hold an option into Friday expiration, to
   avoid exercise/assignment. This is a time-based exit, not a loss-based
   stop -- a losing contract rides all the way to that Thursday and is
   then sold for whatever it's worth, however little.

No stop-loss otherwise, by design -- see the Strategy tab.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from app import config, db, options_client
from app.broker import broker

log = logging.getLogger(__name__)


def _past_thursday_cutoff(expiration_date_str: str, today: date | None = None) -> bool:
    today = today or date.today()
    expiration = date.fromisoformat(expiration_date_str)
    cutoff = expiration - timedelta(days=1)  # the Thursday before a Friday expiration
    return today >= cutoff


def _get_or_recover_plan(contract_symbol: str, qty: float) -> dict | None:
    """Normally created at buy-time by options_trader.py. Falls back to
    reconstructing from the OCC symbol if the plan record is ever missing
    (e.g. a DB reset while a position was still open) -- same defensive
    pattern as the stock take-profit checker."""
    plan = db.get_option_position_plan(contract_symbol)
    if plan is not None:
        return plan

    parsed = options_client.parse_occ_symbol(contract_symbol)
    if parsed is None:
        log.warning("Can't parse option symbol %s -- skipping", contract_symbol)
        return None
    db.create_option_position_plan(
        contract_symbol, parsed["underlying_symbol"], parsed["option_type"],
        parsed["strike"], parsed["expiration_date"].isoformat(), int(qty),
    )
    return db.get_option_position_plan(contract_symbol)


async def _check_position(position: dict) -> None:
    contract_symbol = position["symbol"]
    qty = position.get("qty") or 0
    if qty <= 0:
        return

    plan = await asyncio.to_thread(_get_or_recover_plan, contract_symbol, qty)
    if plan is None:
        return

    if _past_thursday_cutoff(plan["expiration_date"]):
        try:
            result = await asyncio.to_thread(broker.sell_option_qty, contract_symbol, int(qty))
            db.insert_option_trade(
                None, plan["underlying_symbol"], contract_symbol, plan["option_type"], plan["strike"],
                plan["expiration_date"], "expiration_close", int(qty), None, result.get("order_id"),
                "Forced close ahead of Friday expiration.",
            )
            log.info("Options expiration close: %s x%s", contract_symbol, qty)
        except Exception as exc:
            log.exception("Options expiration close failed for %s", contract_symbol)
            db.insert_option_trade(
                None, plan["underlying_symbol"], contract_symbol, plan["option_type"], plan["strike"],
                plan["expiration_date"], "error", None, None, None,
                f"expiration close error: {exc}",
            )
        return

    gain_pct = position.get("unrealized_plpc")
    if gain_pct is None:
        return
    gain_pct *= 100

    remaining_qty = int(qty)
    for i, (threshold, fraction) in enumerate(config.OPTIONS_TIERS):
        if threshold in plan["triggered_tiers"] or gain_pct < threshold:
            continue

        is_last_tier = i == len(config.OPTIONS_TIERS) - 1
        sell_qty = remaining_qty if is_last_tier else round(plan["original_qty"] * fraction)
        sell_qty = int(min(sell_qty, remaining_qty))
        if sell_qty <= 0:
            continue

        reasoning = (
            f"Up {gain_pct:.1f}% since entry (crossed the {threshold:g}% tier) -- "
            f"sold {fraction * 100:.0f}% of the original contracts."
        )
        try:
            result = await asyncio.to_thread(broker.sell_option_qty, contract_symbol, sell_qty)
            db.insert_option_trade(
                None, plan["underlying_symbol"], contract_symbol, plan["option_type"], plan["strike"],
                plan["expiration_date"], "profit_take", sell_qty, None, result.get("order_id"), reasoning,
            )
            db.mark_option_tier_triggered(contract_symbol, threshold)
            log.info("Options profit-take tier %s%%: sold %s %s", threshold, sell_qty, contract_symbol)
            remaining_qty -= sell_qty
        except Exception as exc:
            log.exception("Options profit-take sell failed for %s at tier %s", contract_symbol, threshold)
            db.insert_option_trade(
                None, plan["underlying_symbol"], contract_symbol, plan["option_type"], plan["strike"],
                plan["expiration_date"], "error", None, None, None, f"{reasoning} | order error: {exc}",
            )


async def check_once() -> None:
    try:
        positions = await asyncio.to_thread(broker.get_option_positions)
    except Exception:
        log.exception("Failed to fetch option positions")
        return

    open_symbols = {p["symbol"] for p in positions}
    await asyncio.to_thread(db.clear_stale_option_plans, open_symbols)

    for position in positions:
        await _check_position(position)


async def run_forever() -> None:
    if not config.OPTIONS_ENABLED:
        log.info("Options manager disabled (OPTIONS_ENABLED=false)")
        return
    while True:
        try:
            await check_once()
        except Exception:
            log.exception("Options manager check cycle failed")
        await asyncio.sleep(config.OPTIONS_CHECK_INTERVAL_SECONDS)
