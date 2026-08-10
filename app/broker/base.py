"""Broker abstraction. Anything that trades goes through this interface so a
future real broker (e.g. Schwab) can be dropped in without touching poller.py
or the routes -- just implement this interface and swap the instance in
app/broker/__init__.py behind a config flag.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BrokerInterface(ABC):
    @abstractmethod
    def place_notional_order(self, symbol: str, side: str, notional_usd: float) -> dict[str, Any]:
        """Submit a market order sized in dollars. side is 'buy' or 'sell'."""

    @abstractmethod
    def close_position(self, symbol: str) -> dict[str, Any]:
        """Fully liquidate the current position in symbol."""

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_position_qty(self, symbol: str) -> float:
        """Current share quantity held for symbol (0 if none)."""

    @abstractmethod
    def get_account(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def get_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        ...
