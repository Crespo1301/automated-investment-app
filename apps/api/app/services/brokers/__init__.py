"""Broker adapter subpackage.

The public surface is intentionally a superset of the legacy
``app.services.broker_adapter`` module so callers can migrate from
``from app.services.broker_adapter import ...`` to
``from app.services.brokers import ...`` without behavior changes.
"""

from app.core.config import settings

from app.services.brokers.alpaca import AlpacaBroker
from app.services.brokers.base import (
    MarketDataUnavailableError,
    MissingBrokerCredentialsError,
    PositionNotFoundError,
    _detect_day_trade_records,
    _has_filled_buy_on_date,
    _market_date,
    _optional_int,
    _parse_occ_symbol,
    _rolling_business_dates,
    _round_order_price,
    missing_alpaca_credential_names,
)
from app.services.brokers.local_paper import LocalPaperBroker
from app.services.brokers.options import AlpacaOptionsMixin


def get_broker() -> "LocalPaperBroker | AlpacaBroker":
    """Return the configured broker adapter.

    Live Alpaca submission requires explicit live mode, live permission, and
    credentials. Until then, the local paper broker keeps the worker safe.
    """

    if settings.trading_mode == "live" and settings.allow_live_trading:
        return AlpacaBroker()

    return LocalPaperBroker()


def get_alpaca_paper_broker() -> AlpacaBroker:
    """Return an Alpaca paper broker for read-only checks and paper workflows."""

    original_paper = settings.alpaca_paper
    if not original_paper:
        raise ValueError("Refusing paper account check because Alpaca paper mode is disabled.")

    return AlpacaBroker()


def get_active_alpaca_broker() -> AlpacaBroker:
    """Return an Alpaca broker using the repo's current paper/live settings."""

    return AlpacaBroker()


__all__ = [
    # exceptions
    "MissingBrokerCredentialsError",
    "MarketDataUnavailableError",
    "PositionNotFoundError",
    # brokers
    "LocalPaperBroker",
    "AlpacaBroker",
    "AlpacaOptionsMixin",
    # factories
    "get_broker",
    "get_alpaca_paper_broker",
    "get_active_alpaca_broker",
    # helpers
    "missing_alpaca_credential_names",
    "_round_order_price",
    "_detect_day_trade_records",
    "_has_filled_buy_on_date",
    "_rolling_business_dates",
    "_market_date",
    "_optional_int",
    "_parse_occ_symbol",
]
