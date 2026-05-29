"""Re-export shim for the broker adapter layer.

The real implementations now live in ``app.services.brokers``. This
module preserves the legacy import path so callers can continue to write
``from app.services.broker_adapter import ...`` without change.
"""

from app.services.brokers import (
    AlpacaBroker,
    AlpacaOptionsMixin,
    LocalPaperBroker,
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
    get_active_alpaca_broker,
    get_alpaca_paper_broker,
    get_broker,
    missing_alpaca_credential_names,
)

__all__ = [
    "AlpacaBroker",
    "AlpacaOptionsMixin",
    "LocalPaperBroker",
    "MarketDataUnavailableError",
    "MissingBrokerCredentialsError",
    "PositionNotFoundError",
    "get_active_alpaca_broker",
    "get_alpaca_paper_broker",
    "get_broker",
    "missing_alpaca_credential_names",
    "_round_order_price",
    "_detect_day_trade_records",
    "_has_filled_buy_on_date",
    "_rolling_business_dates",
    "_market_date",
    "_optional_int",
    "_parse_occ_symbol",
]
