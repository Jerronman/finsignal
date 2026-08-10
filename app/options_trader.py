"""Options trading: reuses the exact same news signal as stocks (poller.py
calls handle_verdict() for every verdict, right alongside the stock
handler), but always Buy-to-Open a weekly call (on `buy`) or put (on
`sell`). Never writes/sells options short, never reacts to `hold`.

Guardrails, in order: hold/low-confidence -> skip; per-underlying cooldown
-> skip; no contract found near the target expiration -> skip; contract
fails the liquidity check -> skip; 1 contract would exceed the per-trade
budget -> skip. Sizing is `floor(OPTIONS_MAX_TRADE_USD / (ask * 100))`
contracts. See app/options_client.py for contract selection mechanics and
the Strategy tab for the full plain-language rules.
"""
from __future__ import annotations

import asyncio
import logging

from app import config, db, options_client
from app.broker import broker

log = logging.getLogger(__name__)


async def handle_verdict(article_id: str, verdict: dict) -> None:
    if not config.OPTIONS_ENABLED:
        return

    underlying = verdict["symbol"]
    action = verdict["action"]
    confidence = verdict["confidence"]
    reasoning = verdict.get("reasoning", "")

    def _log(outcome: str, extra_reasoning: str = "", **kwargs) -> None:
        db.insert_option_trade(
            article_id, underlying,
            kwargs.get("contract_symbol"), kwargs.get("option_type"), kwargs.get("strike"),
            kwargs.get("expiration_date"), outcome, kwargs.get("qty"), kwargs.get("price_usd"),
            kwargs.get("order_id"), f"{reasoning}{extra_reasoning}",
        )

    if action == "hold":
        _log("skipped_hold")
        return

    if confidence < config.OPTIONS_MIN_CONFIDENCE:
        _log("skipped_low_confidence")
        return

    if await asyncio.to_thread(db.is_in_option_cooldown, underlying, config.OPTIONS_COOLDOWN_MINUTES):
        _log("skipped_cooldown")
        return

    option_type = "call" if action == "buy" else "put"
    target_date = options_client.target_expiration_date()

    contract = await asyncio.to_thread(options_client.find_contract, underlying, option_type, target_date)
    if contract is None:
        _log("skipped_no_contract", f" (no {option_type} contract found near {target_date})",
             option_type=option_type)
        return

    exp_iso = contract["expiration_date"].isoformat()

    liquid, liquidity_reason = await asyncio.to_thread(options_client.check_liquidity, contract)
    if not liquid:
        _log(
            "skipped_illiquid", f" ({liquidity_reason})",
            contract_symbol=contract["symbol"], option_type=option_type,
            strike=contract["strike"], expiration_date=exp_iso,
        )
        return

    ask_price = await asyncio.to_thread(options_client.get_option_ask_price, contract["symbol"])
    if not ask_price or ask_price <= 0:
        _log(
            "skipped_no_price", contract_symbol=contract["symbol"], option_type=option_type,
            strike=contract["strike"], expiration_date=exp_iso,
        )
        return

    cost_per_contract = ask_price * 100
    if cost_per_contract > config.OPTIONS_MAX_TRADE_USD:
        _log(
            "skipped_too_expensive",
            f" (1 contract = ${cost_per_contract:.2f} > ${config.OPTIONS_MAX_TRADE_USD:.0f} budget)",
            contract_symbol=contract["symbol"], option_type=option_type,
            strike=contract["strike"], expiration_date=exp_iso, price_usd=ask_price,
        )
        return

    qty = int(config.OPTIONS_MAX_TRADE_USD // cost_per_contract)
    if qty <= 0:
        return

    try:
        result = await asyncio.to_thread(broker.place_option_order, contract["symbol"], qty)
        db.insert_option_trade(
            article_id, underlying, contract["symbol"], option_type, contract["strike"], exp_iso,
            "bought", qty, ask_price, result.get("order_id"), reasoning,
        )
        await asyncio.to_thread(db.set_option_cooldown, underlying)
        await asyncio.to_thread(
            db.create_option_position_plan, contract["symbol"], underlying, option_type,
            contract["strike"], exp_iso, qty,
        )
        log.info("Options buy: %s x%d %s (%s, exp %s)", contract["symbol"], qty, option_type, underlying, exp_iso)
    except Exception as exc:
        log.exception("Options order failed for %s", contract["symbol"])
        db.insert_option_trade(
            article_id, underlying, contract["symbol"], option_type, contract["strike"], exp_iso,
            "error", None, ask_price, None, f"{reasoning} | order error: {exc}",
        )
