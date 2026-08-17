"""SQLite storage. Plain sqlite3, no ORM -- schema is small and stable.

Tables:
  news_items        one row per distinct article fetched
  verdicts           one row per (article, symbol) LLM judgment
  trades             one row per (article, symbol) outcome -- traded or skipped, with why
  watchlist          symbols you're extra-polling for news
  symbol_cooldowns   last time we news-traded each symbol, for the cooldown guardrail
  profit_take_plans  per-symbol tiered take-profit plan (original share count + which tiers have fired)

  -- options (separate pipeline, same news signal) --
  option_cooldowns      last time we options-traded each underlying symbol
  option_trades         one row per options trade decision -- traded or skipped, with why
  option_position_plans per-contract tiered take-profit plan (original contract count + tiers fired)

  adam_runs          one row per Adam screener run (auto or manual), including empty ones
"""
from __future__ import annotations

import json
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
-- Trade Log is paginated newest-first -- keeps the ORDER BY off a full
-- table scan + sort as the table grows past a few thousand rows. (Doesn't
-- help the symbol search: that's a LIKE '%x%' with a leading wildcard,
-- which no plain index can range-scan -- it's still a full scan either way,
-- just over a small/cheap table so it isn't worth a covering index for.)
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);

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

CREATE TABLE IF NOT EXISTS option_cooldowns (
    underlying_symbol TEXT PRIMARY KEY,
    last_trade_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS option_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT,
    underlying_symbol TEXT NOT NULL,
    contract_symbol TEXT,
    option_type TEXT,
    strike REAL,
    expiration_date TEXT,
    outcome TEXT NOT NULL,
    qty INTEGER,
    price_usd REAL,
    order_id TEXT,
    reasoning TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS option_position_plans (
    contract_symbol TEXT PRIMARY KEY,
    underlying_symbol TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiration_date TEXT NOT NULL,
    original_qty INTEGER NOT NULL,
    triggered_tiers TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adam_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 'auto' | 'manual'
    tickers_screened TEXT NOT NULL, -- comma-separated
    match_count INTEGER NOT NULL,
    results_json TEXT NOT NULL,     -- json-encoded list of matching rows ('[]' if none)
    ran_at TEXT NOT NULL
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


def get_trades(limit: int = 100, symbol: str | None = None, offset: int = 0) -> list[dict[str, Any]]:
    """Full trade log (executed and skipped), newest first, with the source
    article's headline + URL attached when there is one (profit-take trims
    have no article, so both are null for those).

    If `symbol` is given, it's applied as a SQL filter *before* the limit --
    a search this way always finds a match regardless of how much other
    activity has happened since, unlike filtering an already-limited batch
    fetched client-side (which can silently miss older matching rows once
    they've scrolled past the fetch window).

    `offset` pages through results (paired with `get_trades_count` for a
    total, so the frontend can show "101-200 of 543" and a Next button)."""
    query = """
        SELECT t.*, n.headline, n.url as headline_url
        FROM trades t
        LEFT JOIN news_items n ON n.id = t.article_id
    """
    params: list[Any] = []
    if symbol:
        query += " WHERE UPPER(t.symbol) LIKE ?"
        params.append(f"%{symbol.upper()}%")
    query += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_trades_count(symbol: str | None = None) -> int:
    """Total matching row count, for pagination -- same WHERE clause as
    get_trades but without LIMIT/OFFSET."""
    query = "SELECT COUNT(*) FROM trades"
    params: list[Any] = []
    if symbol:
        query += " WHERE UPPER(symbol) LIKE ?"
        params.append(f"%{symbol.upper()}%")
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()[0]


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


def update_profit_take_original_qty(symbol: str, new_original_qty: float) -> None:
    """Corrects a plan's original_qty -- used when the checker detects the
    snapshot was taken before a buy order had fully settled (so it locked
    onto a smaller-than-real quantity)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE profit_take_plans SET original_qty = ? WHERE symbol = ?",
            (new_original_qty, symbol),
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


def is_in_option_cooldown(underlying_symbol: str, cooldown_minutes: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_trade_at FROM option_cooldowns WHERE underlying_symbol = ?", (underlying_symbol,)
        ).fetchone()
    if not row:
        return False
    last = datetime.fromisoformat(row["last_trade_at"])
    return (datetime.now(timezone.utc) - last).total_seconds() < cooldown_minutes * 60


def set_option_cooldown(underlying_symbol: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO option_cooldowns (underlying_symbol, last_trade_at) VALUES (?, ?) "
            "ON CONFLICT(underlying_symbol) DO UPDATE SET last_trade_at = excluded.last_trade_at",
            (underlying_symbol, now_iso()),
        )


def insert_option_trade(
    article_id: str | None,
    underlying_symbol: str,
    contract_symbol: str | None,
    option_type: str | None,
    strike: float | None,
    expiration_date: str | None,
    outcome: str,
    qty: int | None,
    price_usd: float | None,
    order_id: str | None,
    reasoning: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO option_trades (article_id, underlying_symbol, contract_symbol, option_type, strike, "
            "expiration_date, outcome, qty, price_usd, order_id, reasoning, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                article_id, underlying_symbol, contract_symbol, option_type, strike, expiration_date,
                outcome, qty, price_usd, order_id, reasoning, now_iso(),
            ),
        )


def get_option_trades(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.*, n.headline, n.url as headline_url
            FROM option_trades t
            LEFT JOIN news_items n ON n.id = t.article_id
            ORDER BY t.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_option_position_plan(contract_symbol: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM option_position_plans WHERE contract_symbol = ?", (contract_symbol,)
        ).fetchone()
    if not row:
        return None
    plan = dict(row)
    plan["triggered_tiers"] = {float(t) for t in plan["triggered_tiers"].split(",") if t}
    return plan


def create_option_position_plan(
    contract_symbol: str, underlying_symbol: str, option_type: str, strike: float,
    expiration_date: str, original_qty: int,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO option_position_plans "
            "(contract_symbol, underlying_symbol, option_type, strike, expiration_date, original_qty, "
            "triggered_tiers, created_at) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
            (contract_symbol, underlying_symbol, option_type, strike, expiration_date, original_qty, now_iso()),
        )


def mark_option_tier_triggered(contract_symbol: str, threshold: float) -> None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT triggered_tiers FROM option_position_plans WHERE contract_symbol = ?", (contract_symbol,)
        ).fetchone()
        existing = [t for t in (row["triggered_tiers"] if row else "").split(",") if t]
        existing.append(str(threshold))
        conn.execute(
            "UPDATE option_position_plans SET triggered_tiers = ? WHERE contract_symbol = ?",
            (",".join(existing), contract_symbol),
        )


def update_option_plan_original_qty(contract_symbol: str, new_original_qty: int) -> None:
    """Same self-healing correction as update_profit_take_original_qty, for
    option contract plans."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE option_position_plans SET original_qty = ? WHERE contract_symbol = ?",
            (new_original_qty, contract_symbol),
        )


def clear_stale_option_plans(open_contract_symbols: set[str]) -> None:
    with get_conn() as conn:
        rows = conn.execute("SELECT contract_symbol FROM option_position_plans").fetchall()
        stale = [r["contract_symbol"] for r in rows if r["contract_symbol"] not in open_contract_symbols]
        if stale:
            conn.executemany(
                "DELETE FROM option_position_plans WHERE contract_symbol = ?", [(s,) for s in stale]
            )


def insert_adam_run(source: str, tickers: list[str], results: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO adam_runs (source, tickers_screened, match_count, results_json, ran_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, ",".join(tickers), len(results), json.dumps(results), now_iso()),
        )


def get_adam_runs(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM adam_runs ORDER BY ran_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        row["tickers_screened"] = row["tickers_screened"].split(",") if row["tickers_screened"] else []
        row["results"] = json.loads(row["results_json"])
        del row["results_json"]
        out.append(row)
    return out


# Tables that hold trade/position bookkeeping tied to a specific Alpaca
# account -- wiped together when switching to a different account (see
# reset_trading_state) so nothing from the old account lingers. News/verdict
# history, the watchlist, and Adam screener runs aren't account-specific and
# are left alone.
RESETTABLE_TABLES = [
    "trades",
    "profit_take_plans",
    "symbol_cooldowns",
    "option_trades",
    "option_cooldowns",
    "option_position_plans",
]


def reset_trading_state() -> dict[str, int]:
    """Wipes all local trade history and plan/cooldown bookkeeping -- for
    switching to a different Alpaca account, so the Trade Log and take-profit
    plans don't carry over stale rows from an account this app no longer
    talks to. Real positions/orders live on Alpaca's side and already
    reflect whichever account's keys are active; this only clears what's
    stored locally. Returns the row count deleted from each table."""
    deleted: dict[str, int] = {}
    with get_conn() as conn:
        for table in RESETTABLE_TABLES:
            cur = conn.execute(f"DELETE FROM {table}")
            deleted[table] = cur.rowcount
    return deleted


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
