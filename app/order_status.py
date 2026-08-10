"""Shared between routes/trading.py (stocks) and routes/options.py --
broker.get_orders() returns every order regardless of asset class, so both
trade logs cross-reference the same order list for fill status."""
from __future__ import annotations


def normalize_fill_status(raw_status: str) -> str:
    """Alpaca's OrderStatus enum (e.g. 'OrderStatus.FILLED') collapsed to a
    small set the UI can style: filled / partially_filled / canceled / pending."""
    s = raw_status.split(".")[-1].lower()
    if s == "filled":
        return "filled"
    if s == "partially_filled":
        return "partially_filled"
    if s in ("canceled", "cancelled", "rejected", "expired"):
        return "canceled"
    return "pending"  # new, accepted, pending_new, accepted_for_bidding, etc.
