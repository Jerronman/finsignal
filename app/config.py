"""Loads .env and exposes all configuration as module-level constants."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Marketaux (news source) ---
# Free plan is capped at 100 requests/day -- POLL_INTERVAL_SECONDS defaults
# to 900s (15 min) so one call per cycle stays well under that (96/day),
# leaving headroom for restarts and scripts/test_news_api.py runs.
MARKETAUX_API_TOKEN = os.getenv("MARKETAUX_API_TOKEN", "")
MARKETAUX_BASE_URL = os.getenv("MARKETAUX_BASE_URL", "https://api.marketaux.com/v1")
NEWS_LIMIT = int(os.getenv("NEWS_LIMIT", "10"))
NEWS_LANGUAGE = os.getenv("NEWS_LANGUAGE", "en")

# --- Alpaca paper trading ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# Stock orders outside regular hours (9:30am-4pm ET) must be limit orders
# sized in shares with extended_hours=True -- market/notional orders (used
# during regular hours) are rejected outside them. When enabled, buys,
# sells, and take-profit trims automatically switch order shape based on
# Alpaca's own market clock; regular-hours behavior is unchanged either way.
# Options are unaffected -- US options markets have no extended session.
EXTENDED_HOURS_ENABLED = os.getenv("EXTENDED_HOURS_ENABLED", "true").lower() == "true"
EXTENDED_HOURS_LIMIT_BUFFER_PCT = float(os.getenv("EXTENDED_HOURS_LIMIT_BUFFER_PCT", "0.0025"))

# --- Anthropic signal engine ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SIGNAL_MODEL = os.getenv("SIGNAL_MODEL", "claude-haiku-4-5")

# --- Trading behavior knobs ---
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "900"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.6"))
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", "200"))
MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", "1000"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "60"))

# --- Take-profit (independent of the news signal) ---
# Tiered profit-taking based on gain since YOUR entry price (Alpaca's
# unrealized_plpc -- not "today's" move). Each tier sells a fixed fraction
# of the ORIGINAL share count once crossed, so the position fully
# liquidates in stages by the highest tier. Format: "threshold:fraction,..."
# Default: up 5% -> sell 25% of original; up 10% -> another 25% (50% sold
# total); up 20% -> another 25% (75% sold); up 50% -> sell whatever's left
# (100% sold). Only calls Alpaca (no news-API quota impact), so it can run
# much more often than news polling. No downside/stop-loss handling yet --
# deliberately deferred.
TAKE_PROFIT_ENABLED = os.getenv("TAKE_PROFIT_ENABLED", "true").lower() == "true"
TAKE_PROFIT_CHECK_INTERVAL_SECONDS = int(os.getenv("TAKE_PROFIT_CHECK_INTERVAL_SECONDS", "120"))


def _parse_tiers(raw: str) -> list[tuple[float, float]]:
    tiers = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        threshold_str, fraction_str = part.split(":")
        tiers.append((float(threshold_str), float(fraction_str)))
    return sorted(tiers, key=lambda t: t[0])


TAKE_PROFIT_TIERS = _parse_tiers(os.getenv("TAKE_PROFIT_TIERS", "5:0.25,10:0.25,20:0.25,50:0.25"))

# --- Options trading (same news signal, separate tab/pipeline from stocks) ---
# Always Buy-to-Open, weekly, ~OPTIONS_OTM_PCT out of the money: a `buy`
# verdict buys a call, `sell` buys a put (never writes/sells options short).
# Expiration is the nearest Friday that's at least 2 days out -- if the
# signal fires on Thursday or Friday, it rolls to the following week's
# Friday instead. Positions are force-closed the Thursday before their own
# expiration, regardless of P&L, to avoid Friday expiration/assignment.
OPTIONS_ENABLED = os.getenv("OPTIONS_ENABLED", "true").lower() == "true"
OPTIONS_MIN_CONFIDENCE = float(os.getenv("OPTIONS_MIN_CONFIDENCE", str(MIN_CONFIDENCE)))
OPTIONS_OTM_PCT = float(os.getenv("OPTIONS_OTM_PCT", "0.05"))
OPTIONS_MAX_TRADE_USD = float(os.getenv("OPTIONS_MAX_TRADE_USD", "5000"))
OPTIONS_MIN_OPEN_INTEREST = int(os.getenv("OPTIONS_MIN_OPEN_INTEREST", "50"))
OPTIONS_MAX_SPREAD_PCT = float(os.getenv("OPTIONS_MAX_SPREAD_PCT", "0.15"))
OPTIONS_COOLDOWN_MINUTES = int(os.getenv("OPTIONS_COOLDOWN_MINUTES", str(COOLDOWN_MINUTES)))
OPTIONS_CHECK_INTERVAL_SECONDS = int(os.getenv("OPTIONS_CHECK_INTERVAL_SECONDS", "120"))
# No stop-loss by design -- a losing contract rides to its forced Thursday
# close-out rather than being cut early.
OPTIONS_TIERS = _parse_tiers(os.getenv("OPTIONS_TIERS", "25:0.25,50:0.25,75:0.25,200:0.25"))

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "finsignal.db"))

# --- Access control ---
# HTTP Basic Auth in front of the whole app -- required once this is hosted
# anywhere reachable off your own machine. Auth is skipped entirely if
# APP_PASSWORD is unset, so local development stays prompt-free.
APP_USERNAME = os.getenv("APP_USERNAME", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
AUTH_ENABLED = bool(APP_PASSWORD)
