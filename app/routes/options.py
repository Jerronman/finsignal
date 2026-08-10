from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app import config, db
from app.broker import broker
from app.order_status import normalize_fill_status

router = APIRouter()


@router.get("/options/positions")
async def option_positions():
    positions = await asyncio.to_thread(broker.get_option_positions)
    # Attach each position's plan (strike/expiration/type/original qty) so
    # the frontend doesn't need a second round trip.
    for p in positions:
        plan = await asyncio.to_thread(db.get_option_position_plan, p["symbol"])
        if plan:
            p["underlying_symbol"] = plan["underlying_symbol"]
            p["option_type"] = plan["option_type"]
            p["strike"] = plan["strike"]
            p["expiration_date"] = plan["expiration_date"]
            p["original_qty"] = plan["original_qty"]
    return positions


@router.get("/options/trades")
async def option_trades(limit: int = 100):
    trade_rows = await asyncio.to_thread(db.get_option_trades, limit)
    order_ids = {t["order_id"] for t in trade_rows if t.get("order_id")}
    status_by_id: dict[str, str] = {}
    if order_ids:
        orders_list = await asyncio.to_thread(broker.get_orders, max(len(order_ids) * 2, 100))
        status_by_id = {o["order_id"]: normalize_fill_status(o["status"]) for o in orders_list}
    for t in trade_rows:
        t["fill_status"] = status_by_id.get(t.get("order_id"))
    return trade_rows


@router.get("/options/config")
async def options_config():
    return {
        "enabled": config.OPTIONS_ENABLED,
        "otm_pct": config.OPTIONS_OTM_PCT,
        "max_trade_usd": config.OPTIONS_MAX_TRADE_USD,
        "min_open_interest": config.OPTIONS_MIN_OPEN_INTEREST,
        "max_spread_pct": config.OPTIONS_MAX_SPREAD_PCT,
        "cooldown_minutes": config.OPTIONS_COOLDOWN_MINUTES,
        "min_confidence": config.OPTIONS_MIN_CONFIDENCE,
        "check_interval_seconds": config.OPTIONS_CHECK_INTERVAL_SECONDS,
        "tiers": config.OPTIONS_TIERS,
    }
