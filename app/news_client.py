"""Client for the Marketaux news API (https://www.marketaux.com).

Unlike the Seeking Alpha API this app originally used, Marketaux reliably
tags each article with the actual ticker symbols it's about via its
`entities` array -- no LLM-based symbol guessing needed. We still let the
signal engine (app/signal_engine.py) do the buy/sell/hold judgment itself,
ignoring Marketaux's own sentiment score, per the "LLM-based judgment"
choice made earlier.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from app import config

log = logging.getLogger(__name__)


def _get(params: dict[str, Any]) -> Any:
    url = f"{config.MARKETAUX_BASE_URL}/news/all"
    full_params = {"api_token": config.MARKETAUX_API_TOKEN, **params}
    resp = requests.get(url, params=full_params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    article_id = str(raw.get("uuid") or "").strip()
    headline = (raw.get("title") or "").strip()
    if not article_id or not headline:
        return None

    summary = (raw.get("description") or raw.get("snippet") or "").strip()
    published_at = str(raw.get("published_at") or "")
    url = raw.get("url") or ""

    symbols: set[str] = set()
    for entity in raw.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        # Keep to equities -- Marketaux also tags forex/crypto/index entities,
        # which Alpaca can't trade and would just show up as order errors.
        if entity.get("type") and entity.get("type") != "equity":
            continue
        symbol = entity.get("symbol")
        if symbol:
            symbols.add(str(symbol).upper())

    return {
        "id": f"marketaux:{article_id}",
        "headline": headline,
        "summary": summary,
        "url": url,
        "published_at": published_at,
        "symbols": sorted(symbols),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_news(limit: int | None = None) -> list[dict[str, Any]]:
    """General news feed, filtered to articles that have at least one
    identified entity (so we're not paying LLM calls to judge stories with
    no ticker to act on)."""
    payload = _get(
        {
            "language": config.NEWS_LANGUAGE,
            "must_have_entities": "true",
            "limit": limit or config.NEWS_LIMIT,
        }
    )
    raw_items = payload.get("data") if isinstance(payload, dict) else None
    raw_items = raw_items if isinstance(raw_items, list) else []
    return [n for n in (_normalize_item(r) for r in raw_items) if n]
