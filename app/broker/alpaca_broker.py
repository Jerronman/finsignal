"""Alpaca paper-trading implementation of BrokerInterface."""
from __future__ import annotations

import logging
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

from app import config
from app.broker.base import BrokerInterface

log = logging.getLogger(__name__)


class AlpacaBroker(BrokerInterface):
    def __init__(self) -> None:
        self._client = TradingClient(
            config.ALPACA_API_KEY,
            config.ALPACA_SECRET_KEY,
            paper=config.ALPACA_PAPER,
        )

    def place_notional_order(self, symbol: str, side: str, notional_usd: float) -> dict[str, Any]:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=symbol,
            notional=round(notional_usd, 2),
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(order_data=req)
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": side,
            "notional": notional_usd,
            "status": str(order.status),
        }

    def close_position(self, symbol: str) -> dict[str, Any]:
        order = self._client.close_position(symbol)
        order_id = getattr(order, "id", None)
        status = getattr(order, "status", "closed")
        return {
            "order_id": str(order_id) if order_id else None,
            "symbol": symbol,
            "side": "sell",
            "status": str(status),
        }

    def get_positions(self) -> list[dict[str, Any]]:
        positions = self._client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price is not None else None,
                "market_value": float(p.market_value) if p.market_value is not None else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl is not None else None,
            }
            for p in positions
        ]

    def get_position_qty(self, symbol: str) -> float:
        try:
            pos = self._client.get_open_position(symbol)
            return float(pos.qty)
        except Exception:
            return 0.0

    def get_account(self) -> dict[str, Any]:
        acct = self._client.get_account()
        return {
            "cash": float(acct.cash),
            "portfolio_value": float(acct.portfolio_value),
            "buying_power": float(acct.buying_power),
            "equity": float(acct.equity),
        }

    def get_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        req = GetOrdersRequest(limit=limit)
        orders = self._client.get_orders(req)
        return [
            {
                "order_id": str(o.id),
                "symbol": o.symbol,
                "side": str(o.side),
                "notional": float(o.notional) if o.notional is not None else None,
                "qty": float(o.qty) if o.qty is not None else None,
                "status": str(o.status),
                "submitted_at": str(o.submitted_at),
            }
            for o in orders
        ]
