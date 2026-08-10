"""Exposes the live (non-secret) trading knobs so the Strategy page can
explain exactly what the running app is actually configured to do, rather
than a static description that could drift out of sync with .env."""
from __future__ import annotations

from fastapi import APIRouter

from app import config

router = APIRouter()


@router.get("/strategy-config")
async def strategy_config():
    return {
        "poll_interval_seconds": config.POLL_INTERVAL_SECONDS,
        "min_confidence": config.MIN_CONFIDENCE,
        "min_trade_usd": config.MIN_TRADE_USD,
        "max_trade_usd": config.MAX_TRADE_USD,
        "cooldown_minutes": config.COOLDOWN_MINUTES,
        "take_profit_enabled": config.TAKE_PROFIT_ENABLED,
        "take_profit_tiers": config.TAKE_PROFIT_TIERS,
        "take_profit_check_interval_seconds": config.TAKE_PROFIT_CHECK_INTERVAL_SECONDS,
    }
