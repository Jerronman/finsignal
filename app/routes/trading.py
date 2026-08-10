from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app import db
from app.broker import broker
from app.order_status import normalize_fill_status

router = APIRouter()


@router.get("/positions")
async def positions():
    # broker calls hit Alpaca over the network and are synchronous --
    # asyncio.to_thread keeps them from blocking the whole event loop
    # (and every other in-flight request) while waiting on the response.
    return await asyncio.to_thread(broker.get_positions)


@router.get("/account")
async def account():
    return await asyncio.to_thread(broker.get_account)


@router.get("/orders")
async def orders(limit: int = 50):
    return await asyncio.to_thread(broker.get_orders, limit)


@router.get("/trades")
async def trades(limit: int = 100):
    """Full trade log, each row annotated with whether its Alpaca order has
    actually filled yet (None for rows with no order -- skips/errors)."""
    trade_rows = await asyncio.to_thread(db.get_trades, limit)
    order_ids = {t["order_id"] for t in trade_rows if t.get("order_id")}
    status_by_id: dict[str, str] = {}
    if order_ids:
        orders_list = await asyncio.to_thread(broker.get_orders, max(len(order_ids) * 2, 100))
        status_by_id = {o["order_id"]: normalize_fill_status(o["status"]) for o in orders_list}
    for t in trade_rows:
        t["fill_status"] = status_by_id.get(t.get("order_id"))
    return trade_rows
