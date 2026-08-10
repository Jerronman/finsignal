"""Alpaca-specific options discovery: current price, target expiration
date, contract selection (~OTM strike), and liquidity checks. Order
execution itself lives in app/broker (so it stays swappable) -- this
module is just "find and validate a contract worth trading."
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest, StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import ContractType
from alpaca.trading.requests import GetOptionContractsRequest

from app import config

log = logging.getLogger(__name__)

_trading_client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.ALPACA_PAPER)
_stock_data_client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
_option_data_client = OptionHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)


def target_expiration_date(today: date | None = None) -> date:
    """Nearest Friday that's at least 2 days out. Thursday/Friday signals
    roll to the following week's Friday instead of this week's."""
    today = today or date.today()
    weekday = today.weekday()  # Monday=0 ... Sunday=6, Friday=4
    this_friday = today + timedelta(days=(4 - weekday) % 7)
    if weekday in (3, 4):  # Thursday or Friday
        return this_friday + timedelta(days=7)
    return this_friday


def get_stock_price(symbol: str) -> float | None:
    try:
        trade = _stock_data_client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
        return float(trade[symbol].price)
    except Exception:
        log.exception("Failed to fetch current price for %s", symbol)
        return None


def find_contract(underlying_symbol: str, option_type: str, target_date: date) -> dict[str, Any] | None:
    """Returns {'symbol', 'strike', 'expiration_date', 'open_interest'} for
    the contract closest to OPTIONS_OTM_PCT out of the money, at the
    earliest available expiration on/after target_date (a window is
    searched so a holiday or a thin weekly chain doesn't return nothing).
    None if no contracts exist in that window at all.
    """
    price = get_stock_price(underlying_symbol)
    if price is None:
        return None
    target_strike = price * (1 + config.OPTIONS_OTM_PCT) if option_type == "call" else price * (1 - config.OPTIONS_OTM_PCT)

    try:
        resp = _trading_client.get_option_contracts(
            GetOptionContractsRequest(
                underlying_symbols=[underlying_symbol],
                expiration_date_gte=target_date.isoformat(),
                expiration_date_lte=(target_date + timedelta(days=7)).isoformat(),
                type=ContractType.CALL if option_type == "call" else ContractType.PUT,
                limit=1000,
            )
        )
        contracts = resp.option_contracts
    except Exception:
        log.exception("Option contract lookup failed for %s", underlying_symbol)
        return None

    if not contracts:
        return None

    earliest_exp = min(c.expiration_date for c in contracts)
    same_exp = [c for c in contracts if c.expiration_date == earliest_exp]
    best = min(same_exp, key=lambda c: abs(float(c.strike_price) - target_strike))

    return {
        "symbol": best.symbol,
        "strike": float(best.strike_price),
        "expiration_date": earliest_exp if isinstance(earliest_exp, date) else date.fromisoformat(str(earliest_exp)),
        "open_interest": int(best.open_interest) if best.open_interest is not None else 0,
        "tradable": bool(best.tradable),
    }


def check_liquidity(contract: dict[str, Any]) -> tuple[bool, str]:
    """(is_liquid, reason). reason is a human-readable skip explanation
    when is_liquid is False, empty string otherwise."""
    if not contract.get("tradable", True):
        return False, "contract not tradable"
    if contract["open_interest"] < config.OPTIONS_MIN_OPEN_INTEREST:
        return False, f"open interest too low ({contract['open_interest']} < {config.OPTIONS_MIN_OPEN_INTEREST})"

    try:
        quote = _option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract["symbol"])
        )[contract["symbol"]]
    except Exception:
        log.exception("Option quote lookup failed for %s", contract["symbol"])
        return False, "quote lookup failed"

    bid, ask = float(quote.bid_price or 0), float(quote.ask_price or 0)
    if bid <= 0 or ask <= 0:
        return False, "no real bid/ask market"
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid if mid else 1.0
    if spread_pct > config.OPTIONS_MAX_SPREAD_PCT:
        return False, f"spread too wide ({spread_pct:.1%} > {config.OPTIONS_MAX_SPREAD_PCT:.0%})"
    return True, ""


_OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def parse_occ_symbol(symbol: str) -> dict[str, Any] | None:
    """Reconstruct underlying/expiration/type/strike from an OCC-format
    contract symbol (e.g. 'AAPL260814C00322500'). Used as a fallback if a
    position's local plan record is ever missing (e.g. after a DB reset)."""
    m = _OCC_RE.match(symbol)
    if not m:
        return None
    underlying, exp_str, cp, strike_str = m.groups()
    try:
        expiration = date(2000 + int(exp_str[0:2]), int(exp_str[2:4]), int(exp_str[4:6]))
    except ValueError:
        return None
    return {
        "underlying_symbol": underlying,
        "expiration_date": expiration,
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike_str) / 1000.0,
    }


def get_option_ask_price(contract_symbol: str) -> float | None:
    try:
        quote = _option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=contract_symbol)
        )[contract_symbol]
        return float(quote.ask_price) if quote.ask_price else None
    except Exception:
        log.exception("Failed to fetch ask price for %s", contract_symbol)
        return None
