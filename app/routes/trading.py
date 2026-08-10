from __future__ import annotations

from fastapi import APIRouter

from app import db
from app.broker import broker

router = APIRouter()


@router.get("/positions")
async def positions():
    return broker.get_positions()


@router.get("/account")
async def account():
    return broker.get_account()


@router.get("/orders")
async def orders(limit: int = 50):
    return broker.get_orders(limit=limit)


@router.get("/trades")
async def trades(limit: int = 100):
    """Raw audit log: every trade decision, executed or skipped, and why."""
    return db.get_trades(limit=limit)
