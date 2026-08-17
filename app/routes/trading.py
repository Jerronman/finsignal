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
async def trades(limit: int = 100, symbol: str | None = None, offset: int = 0):
    """One page of the trade log, each row annotated with whether its Alpaca
    order has actually filled yet (None for rows with no order -- skips/
    errors), and for sold/profit_take rows, the actual $ realized on that
    specific sale (reconstructed from Alpaca's order history, so it's
    accurate even for rows logged before this was added).
    Pass `symbol` to search the full history at the database level rather
    than whatever's already been fetched into the page. `offset` pages
    through results `limit` at a time; the response's `total` is the full
    matching count so the frontend can render "101-200 of 543" and a Next
    button without a separate request."""
    trade_rows, total = await asyncio.gather(
        asyncio.to_thread(db.get_trades, limit, symbol, offset),
        asyncio.to_thread(db.get_trades_count, symbol),
    )
    order_ids = {t["order_id"] for t in trade_rows if t.get("order_id")}
    status_by_id: dict[str, str] = {}
    if order_ids:
        orders_list = await asyncio.to_thread(broker.get_orders, max(len(order_ids) * 2, 100))
        status_by_id = {o["order_id"]: normalize_fill_status(o["status"]) for o in orders_list}

    realized_by_order_id: dict[str, float] = {}
    if any(t["outcome"] in ("sold", "profit_take") for t in trade_rows):
        realized_by_order_id = await asyncio.to_thread(broker.get_realized_pl_by_order_id)

    for t in trade_rows:
        t["fill_status"] = status_by_id.get(t.get("order_id"))
        t["realized_pl"] = (
            realized_by_order_id.get(t["order_id"])
            if t["outcome"] in ("sold", "profit_take") and t.get("order_id")
            else None
        )
    return {"trades": trade_rows, "total": total, "offset": offset, "limit": limit}


@router.post("/admin/reset-trading-state")
async def reset_trading_state():
    """Wipes the local Trade Log, take-profit plans, and cooldowns -- for
    switching to a different Alpaca account (see the Trade Log page's Reset
    button). Already behind the app's Basic Auth like every other route, and
    only touches locally-stored bookkeeping -- it can't place or cancel any
    real order on Alpaca's side."""
    deleted = await asyncio.to_thread(db.reset_trading_state)
    return {"deleted": deleted}
