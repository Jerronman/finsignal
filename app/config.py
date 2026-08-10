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
# Checks every open position's *today's* gain (Alpaca's unrealized_intraday_plpc)
# and trims TAKE_PROFIT_SELL_FRACTION of the position the first time it's up
# TAKE_PROFIT_PCT or more in a day. At most once per symbol per calendar day.
# Only calls Alpaca (no news-API quota impact), so it can run much more often
# than news polling.
TAKE_PROFIT_ENABLED = os.getenv("TAKE_PROFIT_ENABLED", "true").lower() == "true"
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.05"))
TAKE_PROFIT_SELL_FRACTION = float(os.getenv("TAKE_PROFIT_SELL_FRACTION", "0.25"))
TAKE_PROFIT_CHECK_INTERVAL_SECONDS = int(os.getenv("TAKE_PROFIT_CHECK_INTERVAL_SECONDS", "120"))

DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "finsignal.db"))

# --- Access control ---
# HTTP Basic Auth in front of the whole app -- required once this is hosted
# anywhere reachable off your own machine. Auth is skipped entirely if
# APP_PASSWORD is unset, so local development stays prompt-free.
APP_USERNAME = os.getenv("APP_USERNAME", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
AUTH_ENABLED = bool(APP_PASSWORD)
