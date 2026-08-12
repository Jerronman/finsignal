"""Adam: an on-demand value/pullback stock screener, adapted from a script
you provided. Screens a ticker list for stocks that are:
  1. Trading down ~5-30% from their 52-week high (a moderate "pullback",
     not a stock in a severe downtrend)
  2. Financially solid (low debt, positive free cash flow, decent margins)
  3. Reasonably valued (P/E, P/B below thresholds)

Data source: Yahoo Finance via `yfinance`. This is entirely separate from
the rest of the app -- no news signal, no automation, nothing persisted.
You click a button, it runs once, you get a table.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import yfinance as yf

log = logging.getLogger(__name__)

DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "JNJ", "PG", "KO", "XOM", "JPM", "V", "HD",
    "UNH", "PFE", "DIS", "NKE", "INTC", "IBM", "CSCO", "T", "VZ",
    "WMT", "MRK",
]


def screen_stocks(
    tickers: list[str],
    min_pullback_pct: float = 5.0,
    max_pullback_pct: float = 30.0,  # avoid stocks in a severe downtrend
    max_pe: float = 25.0,
    max_pb: float = 4.0,
    max_debt_to_equity: float = 150.0,  # yfinance reports this as a %, e.g. 80 = 0.8x
    min_current_ratio: float = 1.2,
    require_positive_fcf: bool = True,
    pause_seconds: float = 0.5,
) -> list[dict[str, Any]]:
    """Screen tickers against pullback + value + quality criteria. Returns
    matching rows sorted by deepest pullback first. Synchronous/blocking --
    callers should run this via asyncio.to_thread (real network calls per
    ticker, roughly pause_seconds + fetch time each)."""
    rows: list[dict[str, Any]] = []

    for symbol in tickers:
        try:
            info = yf.Ticker(symbol).info

            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            high_52wk = info.get("fiftyTwoWeekHigh")
            if not current_price or not high_52wk:
                continue

            pullback_pct = (high_52wk - current_price) / high_52wk * 100
            if not (min_pullback_pct <= pullback_pct <= max_pullback_pct):
                continue

            pe_ratio = info.get("trailingPE")
            pb_ratio = info.get("priceToBook")
            debt_to_equity = info.get("debtToEquity")
            current_ratio = info.get("currentRatio")
            free_cash_flow = info.get("freeCashflow")
            profit_margin = info.get("profitMargins")
            market_cap = info.get("marketCap")

            # Quality/value filters -- skip the check (not the stock) when a
            # metric is missing, rather than auto-failing on absent data.
            if pe_ratio is not None and pe_ratio > max_pe:
                continue
            if pb_ratio is not None and pb_ratio > max_pb:
                continue
            if debt_to_equity is not None and debt_to_equity > max_debt_to_equity:
                continue
            if current_ratio is not None and current_ratio < min_current_ratio:
                continue
            if require_positive_fcf and free_cash_flow is not None and free_cash_flow <= 0:
                continue

            rows.append({
                "ticker": symbol,
                "name": info.get("shortName", symbol),
                "sector": info.get("sector"),
                "price": round(current_price, 2),
                "high_52wk": round(high_52wk, 2),
                "pullback_pct": round(pullback_pct, 2),
                "pe": round(pe_ratio, 2) if pe_ratio else None,
                "pb": round(pb_ratio, 2) if pb_ratio else None,
                "debt_to_equity": round(debt_to_equity, 1) if debt_to_equity else None,
                "current_ratio": round(current_ratio, 2) if current_ratio else None,
                "free_cash_flow_millions": round(free_cash_flow / 1e6, 1) if free_cash_flow else None,
                "profit_margin_pct": round(profit_margin * 100, 1) if profit_margin else None,
                "market_cap_billions": round(market_cap / 1e9, 1) if market_cap else None,
            })
        except Exception as exc:
            log.warning("Skipping %s: %s", symbol, exc)

        time.sleep(pause_seconds)  # be polite to Yahoo's API

    rows.sort(key=lambda r: r["pullback_pct"], reverse=True)
    return rows
