"""Shared broker singleton. Swap this to point at a different BrokerInterface
implementation (e.g. a future Schwab broker) without touching callers."""
from app.broker.alpaca_broker import AlpacaBroker

broker = AlpacaBroker()
