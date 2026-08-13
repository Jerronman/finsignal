"""Alpaca paper-trading implementation of BrokerInterface."""
from __future__ import annotations

import logging
from typing import Any

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus, OrderSide, PositionIntent, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest, LimitOrderRequest, MarketOrderRequest

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
        self._stock_data_client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
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

    def _is_regular_hours(self) -> bool:
        """Whether it's currently regular market hours (9:30am-4pm ET) per
        Alpaca's own clock. Defaults to True (regular-hours order shape) if
        the clock check itself fails -- the existing, more-tested code path,
        and a safe failure mode either way (worst case: a market/notional
        order gets rejected outside hours and is caught upstream as an error,
        rather than us guessing wrong about extended-hours pricing)."""
        try:
            return bool(self._client.get_clock().is_open)
        except Exception:
            log.exception("Failed to check market clock -- defaulting to regular-hours order construction")
            return True

    def _get_stock_price(self, symbol: str) -> float | None:
        try:
            trade = self._stock_data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
            return float(trade[symbol].price)
        except Exception:
            log.exception("Failed to fetch current price for %s", symbol)
            return None

    def _extended_hours_limit_order(self, symbol: str, side: OrderSide, qty: float) -> LimitOrderRequest:
        """Builds the limit+extended_hours order required outside regular
        hours -- market and notional orders are rejected then. Buys bid
        slightly above, sells offer slightly below, the last trade price,
        to make an actual fill likely without chasing too far."""
        price = self._get_stock_price(symbol)
        if not price or price <= 0:
            raise RuntimeError(f"Could not get a current price for {symbol} to build an extended-hours order")
        buffer = config.EXTENDED_HOURS_LIMIT_BUFFER_PCT
        limit_price = round(price * (1 + buffer) if side == OrderSide.BUY else price * (1 - buffer), 2)
        return LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
            extended_hours=True,
        )

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

        if config.EXTENDED_HOURS_ENABLED and not self._is_regular_hours():
            price = self._get_stock_price(symbol)
            if not price or price <= 0:
                raise RuntimeError(f"Could not get a current price for {symbol} to size an extended-hours order")
            qty = round(notional_usd / price, 6)
            req = self._extended_hours_limit_order(symbol, order_side, qty)
        else:
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
        if config.EXTENDED_HOURS_ENABLED and not self._is_regular_hours():
            # The dedicated close-position endpoint always submits a market
            # order and has no extended_hours option -- route a full close
            # through the regular limit-order path instead.
            qty = self.get_position_qty(symbol)
            if qty <= 0:
                raise RuntimeError(f"No position to close for {symbol}")
            return self.sell_qty(symbol, qty)

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
        if config.EXTENDED_HOURS_ENABLED and not self._is_regular_hours():
            req = self._extended_hours_limit_order(symbol, OrderSide.SELL, qty)
        else:
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

    def _replay_stock_orders(self) -> tuple[float, float, dict[str, float]]:
        """Returns (realized_pl, total_invested, realized_by_order_id) by
        replaying every filled stock order chronologically with a running
        weighted-average cost basis per symbol. Rebuilt from Alpaca's own
        permanent order history each call, so it's retroactively accurate
        -- not dependent on when this tracking was added.

        total_invested is the sum of every buy's dollar cost, all-time --
        i.e. total capital *deployed* over time, not capital currently at
        risk. If you buy, sell, then buy something else with that same
        money, both purchases count -- it doesn't shrink when a position
        closes.

        realized_by_order_id maps each sell order's id to the $ gain/loss
        realized by that specific sale -- lets the Trade Log show a P&L
        figure per row (sold/profit_take) rather than only an aggregate."""
        orders = self._client.get_orders(GetOrdersRequest(limit=1000, status=QueryOrderStatus.ALL))
        stock_orders = [
            o for o in orders
            if o.asset_class == AssetClass.US_EQUITY and o.filled_qty and o.filled_avg_price and o.filled_at
        ]
        stock_orders.sort(key=lambda o: o.filled_at)

        qty_held: dict[str, float] = {}
        avg_cost: dict[str, float] = {}
        realized_pl = 0.0
        total_invested = 0.0
        realized_by_order_id: dict[str, float] = {}

        for o in stock_orders:
            symbol = o.symbol
            qty = float(o.filled_qty)
            price = float(o.filled_avg_price)
            side = str(o.side).split(".")[-1].lower()

            if side == "buy":
                total_invested += qty * price
                prev_qty = qty_held.get(symbol, 0.0)
                prev_avg = avg_cost.get(symbol, 0.0)
                new_qty = prev_qty + qty
                avg_cost[symbol] = (prev_qty * prev_avg + qty * price) / new_qty if new_qty else 0.0
                qty_held[symbol] = new_qty
            else:  # sell
                prev_qty = qty_held.get(symbol, 0.0)
                if prev_qty <= 0:
                    continue  # no shorting by design -- guard defensively anyway
                sell_qty = min(qty, prev_qty)
                gain = (price - avg_cost.get(symbol, 0.0)) * sell_qty
                realized_pl += gain
                realized_by_order_id[str(o.id)] = realized_by_order_id.get(str(o.id), 0.0) + gain
                qty_held[symbol] = prev_qty - sell_qty

        return realized_pl, total_invested, realized_by_order_id

    def get_realized_pl_by_order_id(self) -> dict[str, float]:
        """Just the per-order breakdown from _replay_stock_orders, for
        callers (like the Trade Log) that only need that part."""
        _, _, realized_by_order_id = self._replay_stock_orders()
        return realized_by_order_id

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

        # Realized P&L (all-time, whole-account) = total account gain since
        # inception, minus whatever's still unrealized on currently open
        # positions. `base_value` is Alpaca's own record of starting equity
        # -- no cost-basis reconstruction needed for this whole-account figure.
        realized_pl = None
        try:
            history = self._client.get_portfolio_history(GetPortfolioHistoryRequest(period="1A", timeframe="1D"))
            base_value = float(history.base_value) if history.base_value is not None else None
            if base_value is not None:
                realized_pl = (equity - base_value) - total_unrealized
        except Exception:
            log.exception("Failed to compute realized P&L")

        stocks_realized_pl = None
        stocks_total_invested = None
        try:
            stocks_realized_pl, stocks_total_invested, _ = self._replay_stock_orders()
        except Exception:
            log.exception("Failed to compute stocks realized P&L / total invested")

        stocks_unrealized_pct = (
            (stocks_unrealized_pl / stocks_total_invested * 100) if stocks_total_invested else None
        )
        stocks_realized_pct = (
            (stocks_realized_pl / stocks_total_invested * 100)
            if stocks_total_invested and stocks_realized_pl is not None
            else None
        )

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
            "stocks_realized_pl": stocks_realized_pl,
            "stocks_total_invested": stocks_total_invested,
            "stocks_unrealized_pct": stocks_unrealized_pct,
            "stocks_realized_pct": stocks_realized_pct,
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
