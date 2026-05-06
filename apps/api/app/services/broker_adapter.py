"""Broker adapter layer.

The local paper broker is safe for tests and demos. The Alpaca adapter is
constructed only when credentials are present and can target paper or live
depending on runtime settings.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.domain.trading import (
    BrokerAccountStatus,
    BrokerOrderReceipt,
    BrokerOrderSummary,
    BrokerPositionSummary,
    BrokerReconciliationSnapshot,
    ExecutionIntent,
    MarketClockStatus,
    MarketEvent,
    new_id,
)


class MissingBrokerCredentialsError(RuntimeError):
    """Raised when a broker operation needs credentials that are not configured."""

    def __init__(self, missing_names: list[str]) -> None:
        self.missing_names = missing_names
        super().__init__(
            "Missing broker credentials: " + ", ".join(missing_names)
        )


class MarketDataUnavailableError(RuntimeError):
    """Raised when live market data could not be fetched from Alpaca."""


def missing_alpaca_credential_names() -> list[str]:
    """Return missing Alpaca env names without exposing configured values."""

    missing_names: list[str] = []
    if not settings.alpaca_api_key:
        missing_names.append("INVESTMENT_APP_ALPACA_API_KEY")
    if not settings.alpaca_secret_key:
        missing_names.append("INVESTMENT_APP_ALPACA_SECRET_KEY")

    return missing_names


class LocalPaperBroker:
    """Local receipt generator that never contacts a broker."""

    def get_account_status(self) -> BrokerAccountStatus:
        """Return a local demo account shape for offline development."""

        return BrokerAccountStatus(
            broker="local-paper",
            account_mode="paper",
            account_id_hint="local",
            status="offline-demo",
            currency=settings.base_currency,
            buying_power=10,
            cash=10,
            portfolio_value=10,
            pattern_day_trader=None,
        )

    def submit_order(self, intent: ExecutionIntent) -> BrokerOrderReceipt:
        """Pretend to submit an order for pipeline verification."""

        return BrokerOrderReceipt(
            broker_order_id=new_id("local_order"),
            intent_id=intent.intent_id,
            status="accepted_local_paper",
            symbol=intent.symbol,
            side=intent.side,
            submitted_notional=intent.approved_notional,
            raw_message="Local paper broker accepted the execution intent.",
        )


class AlpacaBroker:
    """Minimal Alpaca order adapter using notional market orders."""

    def __init__(self) -> None:
        missing_names = missing_alpaca_credential_names()
        if missing_names:
            raise MissingBrokerCredentialsError(missing_names)

        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        self.client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )
        self.data_client = StockHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )

    def get_account_status(self) -> BrokerAccountStatus:
        """Fetch a read-only account snapshot from Alpaca."""

        account = self.client.get_account()
        account_id = str(account.id)
        return BrokerAccountStatus(
            broker="alpaca",
            account_mode="paper" if settings.alpaca_paper else "live",
            account_id_hint=f"...{account_id[-6:]}",
            status=str(account.status),
            currency=str(account.currency),
            buying_power=float(account.buying_power),
            cash=float(account.cash),
            portfolio_value=float(account.portfolio_value),
            pattern_day_trader=bool(account.pattern_day_trader),
        )

    def get_market_clock(self) -> MarketClockStatus:
        """Fetch the broker market clock."""

        clock = self.client.get_clock()
        return MarketClockStatus(
            is_open=bool(clock.is_open),
            timestamp=getattr(clock, "timestamp", None),
            next_open=getattr(clock, "next_open", None),
            next_close=getattr(clock, "next_close", None),
        )

    def list_watchlist_market_events(self, symbols: list[str]) -> list[MarketEvent]:
        """Return normalized real market events for the configured watchlist."""

        from alpaca.data.requests import StockSnapshotRequest

        normalized_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
        if not normalized_symbols:
            return []

        snapshots = self.data_client.get_stock_snapshot(
            StockSnapshotRequest(symbol_or_symbols=normalized_symbols)
        )
        clock = self.get_market_clock()
        session_state = self._resolve_session_state(clock)
        intraday_profiles = self._get_intraday_profiles(normalized_symbols, clock)
        events: list[MarketEvent] = []
        missing_symbols: list[str] = []

        for symbol in normalized_symbols:
            snapshot = snapshots.get(symbol)
            if snapshot is None:
                missing_symbols.append(symbol)
                continue

            minute_bar = getattr(snapshot, "minute_bar", None)
            daily_bar = getattr(snapshot, "daily_bar", None)
            previous_daily_bar = getattr(snapshot, "previous_daily_bar", None)
            latest_trade = getattr(snapshot, "latest_trade", None)
            timestamp = (
                getattr(minute_bar, "timestamp", None)
                or getattr(latest_trade, "timestamp", None)
                or datetime.now(UTC)
            )
            price = (
                getattr(minute_bar, "close", None)
                or getattr(latest_trade, "price", None)
            )
            volume = getattr(minute_bar, "volume", 0) or 0
            previous_close = getattr(previous_daily_bar, "close", None)
            intraday_profile = intraday_profiles.get(symbol, {})

            if price is None or previous_close is None:
                missing_symbols.append(symbol)
                continue

            events.append(
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol=symbol,
                    event_kind="bar",
                    price=float(price),
                    volume=float(volume),
                    previous_close=float(previous_close),
                    day_open=self._optional_float(getattr(daily_bar, "open", None)),
                    day_high=self._optional_float(getattr(daily_bar, "high", None)),
                    day_low=self._optional_float(getattr(daily_bar, "low", None)),
                    day_volume=self._optional_float(getattr(daily_bar, "volume", None)),
                    previous_volume=self._optional_float(
                        getattr(previous_daily_bar, "volume", None)
                    ),
                    vwap=intraday_profile.get("vwap"),
                    opening_range_high=intraday_profile.get("opening_range_high"),
                    opening_range_low=intraday_profile.get("opening_range_low"),
                    recent_high=intraday_profile.get("recent_high"),
                    recent_low=intraday_profile.get("recent_low"),
                    recent_volume=intraday_profile.get("recent_volume"),
                    average_recent_volume=intraday_profile.get("average_recent_volume"),
                    previous_bar_close=intraday_profile.get("previous_bar_close"),
                    timestamp=timestamp,
                    session_state=session_state,
                )
            )

        if not events:
            joined = ", ".join(missing_symbols[:5]) or "unknown symbols"
            raise MarketDataUnavailableError(
                "Alpaca returned no usable market snapshots for the watchlist. "
                f"Missing or incomplete symbols: {joined}."
            )

        return events

    def has_market_data_access(self, symbols: list[str]) -> tuple[bool, str | None]:
        """Probe Alpaca market data access for readiness checks."""

        try:
            self.list_watchlist_market_events(symbols[:1])
        except Exception as exc:
            return False, str(exc)

        return True, None

    def submit_order(self, intent: ExecutionIntent) -> BrokerOrderReceipt:
        """Submit an approved execution intent to Alpaca."""

        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        order = self.client.submit_order(
            order_data=MarketOrderRequest(
                symbol=intent.symbol,
                notional=intent.approved_notional,
                side=OrderSide.BUY if intent.side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                client_order_id=intent.client_order_id,
            )
        )
        return BrokerOrderReceipt(
            broker_order_id=str(order.id),
            intent_id=intent.intent_id,
            status=str(order.status),
            symbol=intent.symbol,
            side=intent.side,
            submitted_notional=intent.approved_notional,
            raw_message=f"Alpaca accepted order with client id {intent.client_order_id}.",
        )

    def list_recent_orders(self, limit: int = 10) -> list[BrokerOrderSummary]:
        """Fetch recent Alpaca orders in a dashboard-safe shape."""

        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
        orders = self.client.get_orders(filter=request)
        return [self._order_to_summary(order) for order in orders]

    def has_open_duplicate_order(
        self,
        symbol: str,
        side: str,
        notional: float,
        strategy_prefix: str,
    ) -> BrokerOrderSummary | None:
        """Return the first open same-symbol order that looks like a duplicate."""

        open_statuses = {
            "accepted",
            "new",
            "pending_new",
            "partially_filled",
            "pending_replace",
            "pending_cancel",
        }
        cutoff = datetime.now(UTC) - timedelta(
            minutes=max(1, settings.duplicate_order_lookback_minutes)
        )
        for order in self.list_recent_orders(limit=50):
            status = order.status.split(".")[-1].lower()
            order_side = order.side.split(".")[-1].lower()
            client_order_id = order.client_order_id or ""
            submitted_notional = order.submitted_notional or 0
            if status not in open_statuses:
                continue
            if order.submitted_at is not None and order.submitted_at.astimezone(UTC) < cutoff:
                continue
            if order.symbol.upper() != symbol.upper() or order_side != side.lower():
                continue
            if not client_order_id.startswith(strategy_prefix):
                continue
            if abs(submitted_notional - notional) > 0.01:
                continue
            return order

        return None

    def list_positions(self) -> list[BrokerPositionSummary]:
        """Fetch open Alpaca positions in a dashboard-safe shape."""

        positions = self.client.get_all_positions()
        return [
            BrokerPositionSummary(
                symbol=str(position.symbol),
                quantity=float(position.qty),
                market_value=float(position.market_value),
                cost_basis=float(position.cost_basis),
                unrealized_pl=float(position.unrealized_pl),
                unrealized_pl_percent=float(position.unrealized_plpc),
                current_price=(
                    float(position.current_price)
                    if position.current_price is not None
                    else None
                ),
            )
            for position in positions
        ]

    def get_reconciliation_snapshot(self, order_limit: int = 10) -> BrokerReconciliationSnapshot:
        """Fetch account, order, and position state from Alpaca."""

        return BrokerReconciliationSnapshot(
            account=self.get_account_status(),
            orders=self.list_recent_orders(limit=order_limit),
            positions=self.list_positions(),
        )

    def cancel_open_orders(self) -> list[dict[str, object]]:
        """Cancel all open orders and return a compact result list."""

        responses = self.client.cancel_orders()
        results: list[dict[str, object]] = []
        for response in responses:
            results.append(
                {
                    "id": str(getattr(response, "id", "")),
                    "status": int(getattr(response, "status", 0)),
                    "body": str(getattr(response, "body", "")),
                }
            )
        return results

    def submit_position_market_sell(self, symbol: str) -> BrokerOrderReceipt:
        """Submit a day market sell for the full open long position."""

        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        normalized_symbol = symbol.upper()
        position = next(
            (
                broker_position
                for broker_position in self.list_positions()
                if broker_position.symbol.upper() == normalized_symbol
            ),
            None,
        )
        if position is None or position.quantity <= 0:
            raise ValueError(f"No open long position found for {normalized_symbol}.")
        if position.market_value < settings.minimum_order_notional:
            raise ValueError(
                f"{normalized_symbol} position value is below the ${settings.minimum_order_notional:.2f} minimum order guard."
            )
        if self._has_open_sell_order(normalized_symbol):
            raise ValueError(f"An open sell order already exists for {normalized_symbol}.")

        client_order_id = new_id(f"manual_exit_{normalized_symbol.lower()}")
        order = self.client.submit_order(
            order_data=MarketOrderRequest(
                symbol=normalized_symbol,
                qty=position.quantity,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id,
            )
        )
        return BrokerOrderReceipt(
            broker_order_id=str(order.id),
            intent_id=client_order_id,
            status=str(order.status),
            symbol=normalized_symbol,
            side="sell",
            submitted_notional=position.market_value,
            raw_message=f"Alpaca accepted manual sell order with client id {client_order_id}.",
        )

    def submit_position_oco_protection(self, symbol: str) -> BrokerOrderReceipt:
        """Submit broker-side OCO take-profit and stop-loss protection for a whole-share position."""

        from alpaca.trading.enums import OrderClass, OrderSide, OrderType, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        normalized_symbol = symbol.upper()
        position = next(
            (
                broker_position
                for broker_position in self.list_positions()
                if broker_position.symbol.upper() == normalized_symbol
            ),
            None,
        )
        if position is None or position.quantity <= 0:
            raise ValueError(f"No open long position found for {normalized_symbol}.")
        if position.market_value < settings.minimum_order_notional:
            raise ValueError(
                f"{normalized_symbol} position value is below the ${settings.minimum_order_notional:.2f} minimum order guard."
            )
        if abs(position.quantity - round(position.quantity)) >= 0.000000001:
            raise ValueError(
                f"{normalized_symbol} has a fractional quantity. Broker OCO protection is blocked; use app-managed exits."
            )
        if self._has_open_sell_order(normalized_symbol):
            raise ValueError(f"An open sell order already exists for {normalized_symbol}.")

        average_entry_price = position.cost_basis / position.quantity
        stop_price = _round_order_price(
            average_entry_price * (1 - settings.autopilot_stop_loss_percent / 100)
        )
        take_profit_price = _round_order_price(
            average_entry_price * (1 + settings.autopilot_take_profit_percent / 100)
        )
        if take_profit_price <= stop_price:
            raise ValueError(f"Invalid protection prices for {normalized_symbol}.")

        client_order_id = new_id(f"protective_exit_{normalized_symbol.lower()}")
        order = self.client.submit_order(
            order_data=LimitOrderRequest(
                symbol=normalized_symbol,
                qty=round(position.quantity),
                side=OrderSide.SELL,
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.OCO,
                limit_price=take_profit_price,
                take_profit=TakeProfitRequest(limit_price=take_profit_price),
                stop_loss=StopLossRequest(stop_price=stop_price),
                client_order_id=client_order_id,
            )
        )
        return BrokerOrderReceipt(
            broker_order_id=str(order.id),
            intent_id=client_order_id,
            status=str(order.status),
            symbol=normalized_symbol,
            side="sell",
            submitted_notional=position.market_value,
            raw_message=(
                f"Alpaca accepted OCO protection for {normalized_symbol}: "
                f"take profit {take_profit_price}, stop {stop_price}."
            ),
        )

    def _has_open_sell_order(self, symbol: str) -> bool:
        open_statuses = {
            "accepted",
            "new",
            "pending_new",
            "partially_filled",
            "pending_replace",
            "pending_cancel",
        }
        for order in self.list_recent_orders(limit=50):
            status = order.status.split(".")[-1].lower()
            side = order.side.split(".")[-1].lower()
            if order.symbol.upper() == symbol.upper() and side == "sell" and status in open_statuses:
                return True

        return False

    def _order_to_summary(self, order: object) -> BrokerOrderSummary:
        """Normalize an Alpaca SDK order object."""

        return BrokerOrderSummary(
            broker_order_id=str(getattr(order, "id")),
            client_order_id=getattr(order, "client_order_id", None),
            symbol=str(getattr(order, "symbol")),
            side=str(getattr(order, "side")),
            order_type=str(getattr(order, "order_type", getattr(order, "type", ""))),
            status=str(getattr(order, "status")),
            submitted_quantity=self._optional_float(getattr(order, "qty", None)),
            submitted_notional=self._optional_float(getattr(order, "notional", None)),
            filled_quantity=float(getattr(order, "filled_qty", 0) or 0),
            filled_average_price=self._optional_float(getattr(order, "filled_avg_price", None)),
            submitted_at=getattr(order, "submitted_at", None),
            filled_at=getattr(order, "filled_at", None),
        )

    def _optional_float(self, value: object | None) -> float | None:
        """Convert optional Alpaca numeric fields to floats."""

        if value is None:
            return None

        return float(value)

    def _get_intraday_profiles(
        self,
        symbols: list[str],
        clock: MarketClockStatus,
    ) -> dict[str, dict[str, float]]:
        """Build lightweight intraday context from recent minute bars."""

        try:
            from alpaca.data.enums import DataFeed
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
        except Exception:
            return {}

        eastern_now = (clock.timestamp or datetime.now(UTC)).astimezone(
            ZoneInfo("America/New_York")
        )
        session_start = datetime.combine(
            eastern_now.date(),
            time(9, 30),
            tzinfo=ZoneInfo("America/New_York"),
        )
        lookback_start = session_start

        try:
            bar_set = self.data_client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=TimeFrame.Minute,
                    start=lookback_start.astimezone(UTC),
                    end=eastern_now.astimezone(UTC),
                    feed=DataFeed.IEX,
                )
            )
        except Exception:
            return {}

        profiles: dict[str, dict[str, float]] = {}
        for symbol, bars in getattr(bar_set, "data", {}).items():
            sorted_bars = sorted(bars, key=lambda bar: bar.timestamp)
            if not sorted_bars:
                continue

            opening_bars = sorted_bars[:15]
            recent_bars = sorted_bars[-10:]
            volume_bars = sorted_bars[-30:]
            total_volume = sum(float(bar.volume or 0) for bar in sorted_bars)
            vwap_numerator = sum(
                float((bar.vwap or bar.close) or 0) * float(bar.volume or 0)
                for bar in sorted_bars
            )
            profiles[str(symbol).upper()] = {
                "vwap": (
                    round(vwap_numerator / total_volume, 4)
                    if total_volume > 0
                    else float(sorted_bars[-1].close)
                ),
                "opening_range_high": max(float(bar.high) for bar in opening_bars),
                "opening_range_low": min(float(bar.low) for bar in opening_bars),
                "recent_high": max(float(bar.high) for bar in recent_bars),
                "recent_low": min(float(bar.low) for bar in recent_bars),
                "recent_volume": sum(float(bar.volume or 0) for bar in recent_bars),
                "average_recent_volume": (
                    sum(float(bar.volume or 0) for bar in volume_bars)
                    / max(1, len(volume_bars))
                ),
                "previous_bar_close": (
                    float(sorted_bars[-2].close)
                    if len(sorted_bars) >= 2
                    else float(sorted_bars[-1].close)
                ),
            }

        return profiles

    def _resolve_session_state(self, clock: MarketClockStatus) -> str:
        """Map the broker clock into the normalized market-event session state."""

        if clock.is_open:
            return "regular"

        eastern_now = (clock.timestamp or datetime.now(UTC)).astimezone(
            ZoneInfo("America/New_York")
        )
        current_time = eastern_now.time()

        if time(4, 0) <= current_time < time(9, 30):
            return "pre_market"
        if time(16, 0) <= current_time < time(20, 0):
            return "after_hours"
        return "closed"


def _round_order_price(price: float) -> float:
    """Round equity order prices using Alpaca's displayed sub-penny rule."""

    return round(price, 2 if price >= 1 else 4)


def get_broker() -> LocalPaperBroker | AlpacaBroker:
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
