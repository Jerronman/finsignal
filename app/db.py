"""SQLite storage. Plain sqlite3, no ORM -- schema is small and stable.

Tables:
  news_items        one row per distinct article fetched
  verdicts           one row per (article, symbol) LLM judgment
  trades             one row per (article, symbol) outcome -- traded or skipped, with why
  watchlist          symbols you're extra-polling for news
  symbol_cooldowns   last time we news-traded each symbol, for the cooldown guardrail
  profit_take_plans  per-symbol tiered take-profit plan (original share count + which tiers have fired)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id TEXT PRIMARY KEY,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    published_at TEXT,
    symbols TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT,
    symbol TEXT NOT NULL,
    outcome TEXT NOT NULL,
    amount_usd REAL,
    order_id TEXT,
    reasoning TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_cooldowns (
    symbol TEXT PRIMARY KEY,
    last_trade_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profit_take_plans (
    symbol TEXT PRIMARY KEY,
    original_qty REAL NOT NULL,
    triggered_tiers TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""

# One-time cleanup: retire the old date-based table from the previous
# (non-tiered) take-profit design.
MIGRATIONS = "DROP TABLE IF EXISTS profit_takes;"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(MIGRATIONS)
        conn.executescript(SCHEMA)


def article_exists(article_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM news_items WHERE id = ?", (article_id,)).fetchone()
        return row is not None


def insert_news_item(item: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO news_items (id, headline, summary, url, published_at, symbols, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item["id"],
                item["headline"],
                item.get("summary", ""),
                item.get("url", ""),
                item.get("published_at", ""),
                ",".join(item.get("symbols", [])),
                item["fetched_at"],
            ),
        )


def insert_verdict(article_id: str, symbol: str, verdict: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO verdicts (article_id, symbol, action, confidence, reasoning, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (article_id, symbol, verdict["action"], verdict["confidence"], verdict.get("reasoning", ""), now_iso()),
        )


def insert_trade(
    article_id: str | None,
    symbol: str,
    outcome: str,
    amount_usd: float | None,
    order_id: str | None,
    reasoning: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO trades (article_id, symbol, outcome, amount_usd, order_id, reasoning, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (article_id, symbol, outcome, amount_usd, order_id, reasoning, now_iso()),
        )


def get_trades(limit: int = 100) -> list[dict[str, Any]]:
    """Full trade log (executed and skipped), newest first, with the source
    article's headline + URL attached when there is one (profit-take trims
    have no article, so both are null for those)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.*, n.headline, n.url as headline_url
            FROM trades t
            LEFT JOIN news_items n ON n.id = t.article_id
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_profit_take_plan(symbol: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT symbol, original_qty, triggered_tiers FROM profit_take_plans WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if not row:
        return None
    triggered = {float(t) for t in row["triggered_tiers"].split(",") if t}
    return {"symbol": row["symbol"], "original_qty": row["original_qty"], "triggered_tiers": triggered}


def create_profit_take_plan(symbol: str, original_qty: float) -> None:
    """No-op if a plan already exists -- original_qty is pinned at whatever
    it was when the plan was first created (see profit_taker.py for why)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO profit_take_plans (symbol, original_qty, triggered_tiers, created_at) "
            "VALUES (?, ?, '', ?)",
            (symbol, original_qty, now_iso()),
        )


def mark_tier_triggered(symbol: str, threshold: float) -> None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT triggered_tiers FROM profit_take_plans WHERE symbol = ?", (symbol,)
        ).fetchone()
        existing = [t for t in (row["triggered_tiers"] if row else "").split(",") if t]
        existing.append(str(threshold))
        conn.execute(
            "UPDATE profit_take_plans SET triggered_tiers = ? WHERE symbol = ?",
            (",".join(existing), symbol),
        )


def clear_stale_profit_take_plans(open_symbols: set[str]) -> None:
    """Drop plans for symbols no longer held, so a future re-buy starts a
    fresh tiered plan instead of resuming a stale, already-mostly-triggered one."""
    with get_conn() as conn:
        rows = conn.execute("SELECT symbol FROM profit_take_plans").fetchall()
        stale = [r["symbol"] for r in rows if r["symbol"] not in open_symbols]
        if stale:
            conn.executemany("DELETE FROM profit_take_plans WHERE symbol = ?", [(s,) for s in stale])


def is_in_cooldown(symbol: str, cooldown_minutes: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_trade_at FROM symbol_cooldowns WHERE symbol = ?", (symbol,)
        ).fetchone()
    if not row:
        return False
    last = datetime.fromisoformat(row["last_trade_at"])
    return (datetime.now(timezone.utc) - last).total_seconds() < cooldown_minutes * 60


def set_cooldown(symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO symbol_cooldowns (symbol, last_trade_at) VALUES (?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET last_trade_at = excluded.last_trade_at",
            (symbol, now_iso()),
        )


def get_watchlist() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT symbol FROM watchlist ORDER BY added_at").fetchall()
        return [r["symbol"] for r in rows]


def add_watchlist(symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (symbol, added_at) VALUES (?, ?)",
            (symbol.upper(), now_iso()),
        )


def remove_watchlist(symbol: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))


def get_recent_activity(limit: int = 50) -> list[dict[str, Any]]:
    """News items joined with their per-symbol verdict + resulting trade outcome.

    One row per (article, symbol) pair that has a verdict; articles with no
    verdict yet (e.g. not tagged with any symbol) still appear once with nulls.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT n.id as article_id, n.headline, n.summary, n.url, n.published_at,
                   n.symbols, n.fetched_at,
                   v.symbol as verdict_symbol, v.action, v.confidence,
                   v.reasoning as verdict_reasoning,
                   t.outcome, t.amount_usd, t.order_id
            FROM news_items n
            LEFT JOIN verdicts v ON v.article_id = n.id
            LEFT JOIN trades t ON t.article_id = n.id AND t.symbol = v.symbol
            ORDER BY n.fetched_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
