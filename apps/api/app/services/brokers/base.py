"""Shared broker exceptions and module-level helpers.

These primitives are intentionally lightweight and free of broker-SDK
imports so the rest of the ``brokers`` subpackage (and the legacy
``broker_adapter`` shim) can re-export them without circular imports.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.domain.trading import BrokerOrderSummary, DayTradeRecord


class MissingBrokerCredentialsError(RuntimeError):
    """Raised when a broker operation needs credentials that are not configured."""

    def __init__(self, missing_names: list[str]) -> None:
        self.missing_names = missing_names
        super().__init__(
            "Missing broker credentials: " + ", ".join(missing_names)
        )


class MarketDataUnavailableError(RuntimeError):
    """Raised when live market data could not be fetched from Alpaca."""


class PositionNotFoundError(ValueError):
    """Raised when a broker operation targets a symbol with no open long position.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers keep
    working, while letting callers distinguish a genuine missing position
    (HTTP 404) from a guard rejection on an existing position (HTTP 409).
    """


def missing_alpaca_credential_names() -> list[str]:
    """Return missing Alpaca env names without exposing configured values."""

    missing_names: list[str] = []
    if not settings.alpaca_api_key:
        missing_names.append("INVESTMENT_APP_ALPACA_API_KEY")
    if not settings.alpaca_secret_key:
        missing_names.append("INVESTMENT_APP_ALPACA_SECRET_KEY")

    return missing_names


def _round_order_price(price: float) -> float:
    """Round equity order prices using Alpaca's displayed sub-penny rule."""

    return round(price, 2 if price >= 1 else 4)


def _detect_day_trade_records(orders: list[BrokerOrderSummary]) -> list[DayTradeRecord]:
    """Detect simple long-only same-symbol same-day buy/sell round trips."""

    cutoff_dates = _rolling_business_dates(datetime.now(UTC), days=5)
    filled_orders = [
        order
        for order in orders
        if order.filled_quantity > 0
        and order.filled_at is not None
        and _market_date(order.filled_at) in cutoff_dates
    ]
    records: list[DayTradeRecord] = []
    for trade_date in sorted(cutoff_dates):
        symbols = {
            order.symbol.upper()
            for order in filled_orders
            if _market_date(order.filled_at) == trade_date
        }
        for symbol in sorted(symbols):
            unmatched_buys: list[BrokerOrderSummary] = []
            day_orders = sorted(
                [
                    order
                    for order in filled_orders
                    if order.symbol.upper() == symbol
                    and _market_date(order.filled_at) == trade_date
                ],
                key=lambda order: order.filled_at,
            )
            for order in day_orders:
                side = order.side.split(".")[-1].lower()
                if side == "buy":
                    unmatched_buys.append(order)
                    continue

                if side != "sell" or not unmatched_buys:
                    continue

                opened_order = unmatched_buys.pop(0)
                records.append(
                    DayTradeRecord(
                        symbol=symbol,
                        trade_date=trade_date,
                        opened_at=opened_order.filled_at,
                        closed_at=order.filled_at,
                    )
                )

    return records


def _has_filled_buy_on_date(
    orders: list[BrokerOrderSummary],
    symbol: str,
    trade_date: str,
) -> bool:
    return any(
        order.symbol.upper() == symbol.upper()
        and order.side.split(".")[-1].lower() == "buy"
        and order.filled_quantity > 0
        and order.filled_at is not None
        and _market_date(order.filled_at) == trade_date
        for order in orders
    )


def _rolling_business_dates(now: datetime, days: int) -> set[str]:
    eastern_now = now.astimezone(ZoneInfo("America/New_York"))
    dates: set[str] = set()
    current = eastern_now.date()
    while len(dates) < days:
        if current.weekday() < 5:
            dates.add(current.isoformat())
        current = current - timedelta(days=1)

    return dates


def _market_date(timestamp: datetime) -> str:
    return timestamp.astimezone(ZoneInfo("America/New_York")).date().isoformat()


def _optional_int(value: object | None) -> int | None:
    if value is None:
        return None

    return int(value)


def _parse_occ_symbol(occ_symbol: str) -> tuple[str, float, str] | None:
    """Parse an OCC option symbol into (expiration, strike, contract_type).

    OCC format: <root><YYMMDD><C|P><strike*1000 padded to 8 digits>
    Example: AAPL250620C00230000 → ("2025-06-20", 230.0, "call")
    Root may include digits/letters; we scan from the right.
    """

    if len(occ_symbol) < 15:
        return None
    try:
        strike_raw = occ_symbol[-8:]
        right = occ_symbol[-9]
        date_raw = occ_symbol[-15:-9]
        if not strike_raw.isdigit() or not date_raw.isdigit():
            return None
        year = 2000 + int(date_raw[0:2])
        month = int(date_raw[2:4])
        day = int(date_raw[4:6])
        expiration = f"{year:04d}-{month:02d}-{day:02d}"
        strike = int(strike_raw) / 1000.0
        contract_type = "call" if right.upper() == "C" else "put" if right.upper() == "P" else None
        if contract_type is None:
            return None
        return expiration, strike, contract_type
    except (ValueError, IndexError):
        return None


__all__ = [
    "MissingBrokerCredentialsError",
    "MarketDataUnavailableError",
    "PositionNotFoundError",
    "missing_alpaca_credential_names",
    "_round_order_price",
    "_detect_day_trade_records",
    "_has_filled_buy_on_date",
    "_rolling_business_dates",
    "_market_date",
    "_optional_int",
    "_parse_occ_symbol",
]
