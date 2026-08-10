from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import db

router = APIRouter()


class SymbolBody(BaseModel):
    symbol: str


@router.get("/watchlist")
async def get_watchlist():
    return db.get_watchlist()


@router.post("/watchlist")
async def add_symbol(body: SymbolBody):
    db.add_watchlist(body.symbol)
    return {"ok": True}


@router.delete("/watchlist/{symbol}")
async def remove_symbol(symbol: str):
    db.remove_watchlist(symbol)
    return {"ok": True}
