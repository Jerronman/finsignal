"""Asks Claude to judge each candidate symbol's likely short-term price
impact from one news item, in a single batched call, returning a structured
list via forced tool use.

Marketaux already tells us which tickers an article is about (its
`entities` array -- see app/news_client.py), so unlike an earlier version of
this file, we don't ask Claude to guess symbols from the text. We only ask
it to judge the ones Marketaux already identified.
"""
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app import config

log = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


VERDICTS_TOOL = {
    "name": "trading_verdicts",
    "description": (
        "Report a trading verdict for each candidate symbol this news item is "
        "substantively about. Omit any candidate symbol that's only mentioned "
        "in passing or as a comparison."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "One of the candidate symbols provided."},
                        "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "How clear-cut and material this news is for this symbol.",
                        },
                        "reasoning": {"type": "string", "description": "One sentence explaining the verdict."},
                    },
                    "required": ["symbol", "action", "confidence", "reasoning"],
                },
            },
        },
        "required": ["verdicts"],
    },
}

SYSTEM_PROMPT = (
    "You are a terse financial news analyst supporting a PAPER TRADING bot "
    "(fake money, no real financial risk). You'll be given a news headline/"
    "summary plus a list of candidate stock ticker symbols this article has "
    "already been tagged with. For each candidate that the news is clearly "
    "and substantively about -- not just mentioned in passing or as a "
    "comparison -- judge the likely short-term price reaction:\n\n"
    "'buy' = meaningfully bullish for this symbol.\n"
    "'sell' = meaningfully bearish for this symbol.\n"
    "'hold' = unclear or mixed, but still worth recording.\n\n"
    "Confidence reflects how clear-cut and material the news is for that "
    "symbol -- not general optimism. Only use symbols from the candidate "
    "list provided; skip candidates that aren't really the subject of this "
    "story. Always call the trading_verdicts tool exactly once."
)


def judge(symbols: list[str], headline: str, summary: str) -> list[dict[str, Any]]:
    """Return a list of {'symbol', 'action', 'confidence', 'reasoning'} dicts,
    a subset of `symbols` (possibly empty, possibly all of them)."""
    if not symbols:
        return []

    client = _get_client()
    user_content = (
        f"Candidate symbols: {', '.join(symbols)}\n"
        f"Headline: {headline}\n"
        f"Summary: {summary or '(none provided)'}"
    )
    try:
        resp = client.messages.create(
            model=config.SIGNAL_MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            tools=[VERDICTS_TOOL],
            tool_choice={"type": "tool", "name": "trading_verdicts"},
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception:
        log.exception("Signal engine call failed for: %s", headline)
        return []

    candidate_set = {s.upper() for s in symbols}
    for block in resp.content:
        if block.type == "tool_use" and block.name == "trading_verdicts":
            raw_verdicts = block.input.get("verdicts", [])
            out: list[dict[str, Any]] = []
            for v in raw_verdicts:
                symbol = str(v.get("symbol", "")).strip().upper()
                action = v.get("action", "hold")
                if symbol not in candidate_set or action not in ("buy", "sell", "hold"):
                    continue
                try:
                    confidence = float(v.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                confidence = min(max(confidence, 0.0), 1.0)
                out.append(
                    {
                        "symbol": symbol,
                        "action": action,
                        "confidence": confidence,
                        "reasoning": v.get("reasoning", ""),
                    }
                )
            return out

    log.warning("No tool_use block returned for: %s", headline)
    return []
