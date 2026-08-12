"""Alpaca paper-trading implementation of BrokerInterface."""
from __future__ import annotations

import logging
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus, OrderSide, PositionIntent, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest, MarketOrderRequest

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
        self._asset_name_cache: dict[str, str] = {}

    def _get_asset_name(self, symbol: str) -> str:
        """Company name for a symbol, e.g. 'Apple Inc.' for AAPL -- cached
        since it never changes, so the Positions panel isn't paying for an
        extra Alpaca call per symbol on every 30s refresh."""
        if symbol not in self._asset_name_cache:
            try:
                self._asset_name_cache[symbol] = self._client.get_asset(symbol).name or symbol
            except Exception:
                self._asset_name_cache[symbol] = symbol
        return self._asset_name_cache[symbol]

    def is_tradable(self, symbol: str) -> bool:
        try:
            asset = self._client.get_asset(symbol)
        except Exception:
            # Includes "asset not found" -- covers foreign-exchange tickers
            # (e.g. IFT.AX) that don't exist in Alpaca's universe at all.
            return False
        return bool(asset.tradable) and asset.status == AssetStatus.ACTIVE

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

    def sell_qty(self, symbol: str, qty: float) -> dict[str, Any]:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(order_data=req)
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": "sell",
            "qty": qty,
            "status": str(order.status),
        }

    def get_positions(self) -> list[dict[str, Any]]:
        # Equities only -- options positions have their own panel/methods
        # below so the two don't get mixed together in the stock UI.
        positions = [p for p in self._client.get_all_positions() if p.asset_class == AssetClass.US_EQUITY]
        return [
            {
                "symbol": p.symbol,
                "name": self._get_asset_name(p.symbol),
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price is not None else None,
                "market_value": float(p.market_value) if p.market_value is not None else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl is not None else None,
                "unrealized_plpc": float(p.unrealized_plpc) if p.unrealized_plpc is not None else None,
                "unrealized_intraday_plpc": (
                    float(p.unrealized_intraday_plpc) if p.unrealized_intraday_plpc is not None else None
                ),
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
        equity = float(acct.equity)
        last_equity = float(acct.last_equity) if acct.last_equity is not None else equity
        pl_today = equity - last_equity

        all_positions = self._client.get_all_positions()
        stocks_unrealized_pl = sum(
            float(p.unrealized_pl or 0) for p in all_positions if p.asset_class == AssetClass.US_EQUITY
        )
        options_unrealized_pl = sum(
            float(p.unrealized_pl or 0) for p in all_positions if p.asset_class == AssetClass.US_OPTION
        )
        total_unrealized = stocks_unrealized_pl + options_unrealized_pl

        # Realized P&L (all-time) = total account gain since inception, minus
        # whatever's still unrealized on currently open positions. `base_value`
        # is Alpaca's own record of starting equity -- no cost-basis
        # reconstruction needed on our end. Whole-account only -- splitting
        # this by asset class would need us to record actual sell/close
        # proceeds ourselves, which we don't today.
        realized_pl = None
        try:
            history = self._client.get_portfolio_history(GetPortfolioHistoryRequest(period="1A", timeframe="1D"))
            base_value = float(history.base_value) if history.base_value is not None else None
            if base_value is not None:
                realized_pl = (equity - base_value) - total_unrealized
        except Exception:
            log.exception("Failed to compute realized P&L")

        return {
            "cash": float(acct.cash),
            "portfolio_value": float(acct.portfolio_value),
            "buying_power": float(acct.buying_power),
            "equity": equity,
            "pl_today": pl_today,
            "pl_today_pct": (pl_today / last_equity * 100) if last_equity else 0.0,
            "realized_pl": realized_pl,
            "stocks_unrealized_pl": stocks_unrealized_pl,
            "options_unrealized_pl": options_unrealized_pl,
        }

    def get_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        # Alpaca's default is open orders only -- ALL is needed so filled/
        # canceled orders still show up (the Trade Log's fill-status column
        # relies on this).
        req = GetOrdersRequest(limit=limit, status=QueryOrderStatus.ALL)
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

    def place_option_order(self, contract_symbol: str, qty: int) -> dict[str, Any]:
        req = MarketOrderRequest(
            symbol=contract_symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            position_intent=PositionIntent.BUY_TO_OPEN,
        )
        order = self._client.submit_order(order_data=req)
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": "buy",
            "qty": qty,
            "status": str(order.status),
        }

    def sell_option_qty(self, contract_symbol: str, qty: int) -> dict[str, Any]:
        req = MarketOrderRequest(
            symbol=contract_symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            position_intent=PositionIntent.SELL_TO_CLOSE,
        )
        order = self._client.submit_order(order_data=req)
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "side": "sell",
            "qty": qty,
            "status": str(order.status),
        }

    def get_option_positions(self) -> list[dict[str, Any]]:
        positions = [p for p in self._client.get_all_positions() if p.asset_class == AssetClass.US_OPTION]
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price is not None else None,
                "market_value": float(p.market_value) if p.market_value is not None else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl is not None else None,
                "unrealized_plpc": float(p.unrealized_plpc) if p.unrealized_plpc is not None else None,
            }
            for p in positions
        ]
