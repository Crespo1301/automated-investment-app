"""Broker adapter layer.

The local paper broker is safe for tests and demos. The Alpaca adapter is
constructed only when credentials are present and can target paper or live
depending on runtime settings.
"""

import math
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.domain.trading import (
    BrokerAccountStatus,
    BrokerOrderReceipt,
    BrokerOrderSummary,
    BrokerPositionSummary,
    BrokerReconciliationSnapshot,
    DayTradeGuardResult,
    DayTradeRecord,
    ExecutionIntent,
    MarketClockStatus,
    MarketEvent,
    OptionContract,
    OptionsChainSnapshot,
    OptionsExecutionIntent,
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

        from alpaca.data.historical import NewsClient, StockHistoricalDataClient
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
        self.news_client = NewsClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )
        self._options_data_client = None  # lazily initialized on first chain call

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
            daytrade_count=_optional_int(getattr(account, "daytrade_count", None)),
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

        benchmark_symbols = ["SPY", "QQQ"]
        request_symbols = list(dict.fromkeys(normalized_symbols + benchmark_symbols))
        snapshots = self.data_client.get_stock_snapshot(
            StockSnapshotRequest(symbol_or_symbols=request_symbols)
        )
        clock = self.get_market_clock()
        session_state = self._resolve_session_state(clock)
        intraday_profiles = self._get_intraday_profiles(request_symbols, clock)
        market_context = self._get_broader_market_context(snapshots, benchmark_symbols)
        news_context = self._get_news_context(normalized_symbols)
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
            latest_quote = getattr(snapshot, "latest_quote", None)
            quote_context = self._quote_context(latest_quote)
            symbol_news = news_context.get(symbol, {})

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
                    bid_price=quote_context.get("bid_price"),
                    ask_price=quote_context.get("ask_price"),
                    spread_bps=quote_context.get("spread_bps"),
                    quote_depth=quote_context.get("quote_depth"),
                    orderbook_imbalance=quote_context.get("orderbook_imbalance"),
                    intraday_volatility_percent=intraday_profile.get("intraday_volatility_percent"),
                    volatility_regime=intraday_profile.get("volatility_regime", "unknown"),
                    market_move_percent=market_context.get("market_move_percent"),
                    market_regime=market_context.get("market_regime", "unknown"),
                    news_count_24h=symbol_news.get("news_count_24h"),
                    latest_news_headline=symbol_news.get("latest_news_headline"),
                    news_sentiment_hint=symbol_news.get("news_sentiment_hint", "unknown"),
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

    def get_day_trade_guard(self, symbol: str) -> DayTradeGuardResult:
        """Return a rolling five-business-day PDT guard for a prospective sell."""

        normalized_symbol = symbol.upper()
        orders = self.list_recent_orders(limit=500)
        records = _detect_day_trade_records(orders)
        account = self.client.get_account()
        broker_day_trade_count = _optional_int(
            getattr(account, "daytrade_count", None)
        )
        local_day_trade_count = len(records)
        if settings.pdt_use_broker_daytrade_count and broker_day_trade_count is not None:
            day_trade_count = broker_day_trade_count
            count_source = "broker"
        else:
            day_trade_count = local_day_trade_count
            count_source = "local"
        today = _market_date(datetime.now(UTC))
        would_be_day_trade = _has_filled_buy_on_date(orders, normalized_symbol, today)
        allowed = (
            not would_be_day_trade
            or day_trade_count < settings.max_day_trades_5_business_days
        )
        reason = (
            "Sell is not a same-day round trip."
            if not would_be_day_trade
            else (
                "Day trade allowed under rolling five-business-day limit."
                if allowed
                else (
                    "Day trade blocked to avoid exceeding the rolling five-business-day PDT limit "
                    f"using {count_source} count."
                )
            )
        )
        if broker_day_trade_count is not None and broker_day_trade_count != local_day_trade_count:
            reason = (
                f"{reason} Alpaca reports {broker_day_trade_count}; local filled-order scan reports "
                f"{local_day_trade_count}."
            )

        return DayTradeGuardResult(
            symbol=normalized_symbol,
            would_be_day_trade=would_be_day_trade,
            allowed=allowed,
            day_trades_5_business_days=day_trade_count,
            local_day_trades_5_business_days=local_day_trade_count,
            broker_day_trades_5_business_days=broker_day_trade_count,
            count_source=count_source,
            max_day_trades_5_business_days=settings.max_day_trades_5_business_days,
            records=records,
            reason=reason,
        )

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

    def submit_position_market_sell(
        self,
        symbol: str,
        percent: float | None = None,
        dollars: float | None = None,
    ) -> BrokerOrderReceipt:
        """Submit a day market sell for an open long position.

        Alpaca only accepts a share ``qty`` on a position sell, never a
        dollar amount, so any dollar-denominated request is converted to
        shares here against the position's live market value.

        Sizing is one of three mutually exclusive forms:

        - neither ``percent`` nor ``dollars``: sell the whole position.
        - ``percent`` (1-100): sell that share of the position.
        - ``dollars`` (> 0): sell approximately that dollar amount;
          ``qty = position.quantity * dollars / market_value``. A dollars
          value at or above the position's market value sells it whole.

        Every partial sell guards both the trimmed proceeds and the
        *remainder* against ``minimum_order_notional`` so a trim never
        submits a sub-minimum order and never strands a sub-minimum,
        unsellable lot behind it (the lesson of the $0.98 IWM lot).
        """

        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        if percent is not None and dollars is not None:
            raise ValueError(
                "Specify a sell size as percent or dollars, not both."
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
            raise PositionNotFoundError(
                f"No open long position found for {normalized_symbol}."
            )
        if position.market_value < settings.minimum_order_notional:
            raise ValueError(
                f"{normalized_symbol} position value is below the ${settings.minimum_order_notional:.2f} minimum order guard."
            )
        if self._has_open_sell_order(normalized_symbol):
            raise ValueError(f"An open sell order already exists for {normalized_symbol}.")

        # Resolve the requested size to a single fraction of the position.
        # ``size_label`` only describes the request for the receipt/log.
        if dollars is not None:
            if dollars <= 0:
                raise ValueError(
                    f"Dollar sell amount for {normalized_symbol} must be greater than zero."
                )
            fraction = dollars / position.market_value
            size_label = f"${dollars:.2f}"
        elif percent is not None:
            if percent <= 0:
                raise ValueError(
                    f"Percent sell size for {normalized_symbol} must be greater than zero."
                )
            fraction = percent / 100
            size_label = f"{percent:.0f}%"
        else:
            fraction = 1.0
            size_label = "100%"

        # A request at or beyond the whole position is a full exit.
        is_partial = fraction < 1.0
        if is_partial:
            sell_quantity = round(position.quantity * fraction, 9)
            sell_notional = position.market_value * fraction
            remainder_notional = position.market_value - sell_notional
            if sell_quantity <= 0:
                raise ValueError(
                    f"Partial sell of {normalized_symbol} ({size_label}) rounds to zero shares."
                )
            if sell_notional < settings.minimum_order_notional:
                raise ValueError(
                    f"Partial sell of {normalized_symbol} ({size_label}) is only "
                    f"${sell_notional:.2f}, below the ${settings.minimum_order_notional:.2f} "
                    "minimum order guard. Sell a larger amount or the full position."
                )
            if remainder_notional < settings.minimum_order_notional:
                raise ValueError(
                    f"Partial sell of {normalized_symbol} ({size_label}) would leave "
                    f"${remainder_notional:.2f} behind, below the "
                    f"${settings.minimum_order_notional:.2f} minimum order guard — an "
                    "unsellable stranded lot. Sell the full position instead."
                )
        else:
            sell_quantity = position.quantity
            sell_notional = position.market_value

        order_prefix = "manual_trim" if is_partial else "manual_exit"
        client_order_id = new_id(f"{order_prefix}_{normalized_symbol.lower()}")
        order = self.client.submit_order(
            order_data=MarketOrderRequest(
                symbol=normalized_symbol,
                qty=sell_quantity,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id,
            )
        )
        sell_label = (
            f"partial sell ({size_label} = {sell_quantity:g} sh)"
            if is_partial
            else "manual sell"
        )
        return BrokerOrderReceipt(
            broker_order_id=str(order.id),
            intent_id=client_order_id,
            status=str(order.status),
            symbol=normalized_symbol,
            side="sell",
            submitted_notional=sell_notional,
            raw_message=f"Alpaca accepted {sell_label} order with client id {client_order_id}.",
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
            raise PositionNotFoundError(
                f"No open long position found for {normalized_symbol}."
            )
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

    def get_option_chain(
        self,
        underlying: str,
        *,
        dte_min: int,
        dte_max: int,
    ) -> OptionsChainSnapshot:
        """Fetch a filtered option chain snapshot for the given underlying.

        NOTE: verify Alpaca options SDK field names with a live call before
        first real submission. The alpaca-py options module shape can shift
        between SDK releases.
        """

        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        from alpaca.data.requests import StockLatestTradeRequest

        if self._options_data_client is None:
            self._options_data_client = OptionHistoricalDataClient(
                settings.alpaca_api_key,
                settings.alpaca_secret_key,
            )

        normalized = underlying.upper()
        today = datetime.now(UTC).date()
        expiration_gte = today + timedelta(days=max(0, dte_min))
        expiration_lte = today + timedelta(days=max(dte_min, dte_max))

        chain_response = self._options_data_client.get_option_chain(
            OptionChainRequest(
                underlying_symbol=normalized,
                expiration_date_gte=expiration_gte,
                expiration_date_lte=expiration_lte,
            )
        )

        # get_option_chain returns dict[occ_symbol, OptionsSnapshot]
        contracts: list[OptionContract] = []
        for occ_symbol, snapshot in chain_response.items():
            parsed = _parse_occ_symbol(occ_symbol)
            if parsed is None:
                continue
            expiration, strike, contract_type = parsed
            latest_quote = getattr(snapshot, "latest_quote", None)
            latest_trade = getattr(snapshot, "latest_trade", None)
            greeks = getattr(snapshot, "greeks", None)
            contracts.append(
                OptionContract(
                    occ_symbol=occ_symbol,
                    underlying=normalized,
                    expiration=expiration,
                    strike=strike,
                    contract_type=contract_type,
                    multiplier=100,
                    bid=self._optional_float(getattr(latest_quote, "bid_price", None)),
                    ask=self._optional_float(getattr(latest_quote, "ask_price", None)),
                    last=self._optional_float(getattr(latest_trade, "price", None)),
                    open_interest=_optional_int(getattr(snapshot, "open_interest", None)),
                    volume=_optional_int(getattr(latest_trade, "size", None)),
                    delta=self._optional_float(getattr(greeks, "delta", None)) if greeks else None,
                    implied_volatility=self._optional_float(
                        getattr(snapshot, "implied_volatility", None)
                    ),
                )
            )

        underlying_price: float | None = None
        try:
            trade = self.data_client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=normalized)
            )
            entry = trade.get(normalized) if isinstance(trade, dict) else None
            underlying_price = self._optional_float(getattr(entry, "price", None))
        except Exception:
            underlying_price = None

        return OptionsChainSnapshot(
            underlying=normalized,
            underlying_price=underlying_price,
            contracts=contracts,
        )

    def submit_options_order(self, intent: OptionsExecutionIntent) -> BrokerOrderReceipt:
        """Submit an approved options execution intent to Alpaca.

        Level 1 orders are single-leg limit orders against an OCC symbol.
        NOTE: verify with a paper round-trip before the first live call.
        """

        from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = OrderSide.SELL if intent.action in {"sell_to_open", "sell_to_close"} else OrderSide.BUY
        tif = TimeInForce.DAY if intent.time_in_force == "day" else TimeInForce.GTC

        if intent.order_type == "limit" and intent.limit_price is not None:
            request = LimitOrderRequest(
                symbol=intent.occ_symbol,
                qty=intent.contracts,
                side=side,
                type=OrderType.LIMIT,
                time_in_force=tif,
                limit_price=round(float(intent.limit_price), 2),
                client_order_id=intent.client_order_id,
            )
        else:
            request = MarketOrderRequest(
                symbol=intent.occ_symbol,
                qty=intent.contracts,
                side=side,
                time_in_force=tif,
                client_order_id=intent.client_order_id,
            )

        order = self.client.submit_order(order_data=request)
        return BrokerOrderReceipt(
            broker_order_id=str(order.id),
            intent_id=intent.intent_id,
            status=str(order.status),
            symbol=intent.occ_symbol,
            side="sell" if side == OrderSide.SELL else "buy",
            submitted_notional=(
                float(intent.limit_price) * intent.contracts * 100
                if intent.limit_price is not None
                else 0.0
            ),
            raw_message=(
                f"Alpaca accepted options {intent.action} for {intent.occ_symbol} "
                f"x{intent.contracts} (client id {intent.client_order_id})."
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

    def _quote_context(self, quote: object | None) -> dict[str, float]:
        """Extract spread and top-of-book depth proxy from the latest quote."""

        if quote is None:
            return {}

        bid_price = self._optional_float(getattr(quote, "bid_price", None))
        ask_price = self._optional_float(getattr(quote, "ask_price", None))
        bid_size = self._optional_float(getattr(quote, "bid_size", None)) or 0
        ask_size = self._optional_float(getattr(quote, "ask_size", None)) or 0
        context: dict[str, float] = {}

        if bid_price is not None:
            context["bid_price"] = bid_price
        if ask_price is not None:
            context["ask_price"] = ask_price

        if bid_price and ask_price and ask_price >= bid_price:
            mid_price = (bid_price + ask_price) / 2
            if mid_price > 0:
                context["spread_bps"] = ((ask_price - bid_price) / mid_price) * 10_000

        quote_depth = bid_size + ask_size
        if quote_depth > 0:
            context["quote_depth"] = quote_depth
            context["orderbook_imbalance"] = (bid_size - ask_size) / quote_depth

        return context

    def _get_broader_market_context(
        self,
        snapshots: dict[str, object],
        benchmark_symbols: list[str],
    ) -> dict[str, float | str]:
        """Build a simple risk-on/risk-off context from benchmark snapshots."""

        moves: list[float] = []
        for symbol in benchmark_symbols:
            snapshot = snapshots.get(symbol)
            if snapshot is None:
                continue
            minute_bar = getattr(snapshot, "minute_bar", None)
            latest_trade = getattr(snapshot, "latest_trade", None)
            previous_daily_bar = getattr(snapshot, "previous_daily_bar", None)
            price = (
                getattr(minute_bar, "close", None)
                or getattr(latest_trade, "price", None)
            )
            previous_close = getattr(previous_daily_bar, "close", None)
            if price is None or previous_close is None or previous_close <= 0:
                continue
            moves.append((float(price) - float(previous_close)) / float(previous_close))

        if not moves:
            return {"market_regime": "unknown"}

        market_move = sum(moves) / len(moves)
        if market_move >= 0.003:
            regime = "risk_on"
        elif market_move <= -0.003:
            regime = "risk_off"
        else:
            regime = "neutral"

        return {
            "market_move_percent": market_move,
            "market_regime": regime,
        }

    def _get_news_context(self, symbols: list[str]) -> dict[str, dict[str, object]]:
        """Fetch recent Alpaca news context for the watchlist without blocking trades."""

        try:
            from alpaca.data.requests import NewsRequest

            news_set = self.news_client.get_news(
                NewsRequest(
                    symbols=",".join(symbols),
                    start=datetime.now(UTC) - timedelta(days=1),
                    limit=min(50, max(1, len(symbols) * 3)),
                    include_content=False,
                    exclude_contentless=True,
                )
            )
        except Exception:
            return {}

        rows = []
        data = getattr(news_set, "data", None)
        if isinstance(data, dict):
            rows = data.get("news") or []
        elif isinstance(data, list):
            rows = data

        context = {
            symbol: {
                "news_count_24h": 0,
                "latest_news_headline": None,
                "news_sentiment_hint": "unknown",
            }
            for symbol in symbols
        }
        for item in rows:
            item_symbols = [str(symbol).upper() for symbol in getattr(item, "symbols", [])]
            headline = str(getattr(item, "headline", "") or "")
            summary = str(getattr(item, "summary", "") or "")
            sentiment = self._news_sentiment_hint(f"{headline} {summary}")
            for symbol in symbols:
                if symbol not in item_symbols:
                    continue
                symbol_context = context[symbol]
                symbol_context["news_count_24h"] = int(symbol_context["news_count_24h"] or 0) + 1
                if symbol_context["latest_news_headline"] is None and headline:
                    symbol_context["latest_news_headline"] = headline[:180]
                if sentiment != "unknown":
                    symbol_context["news_sentiment_hint"] = sentiment

        return context

    def _news_sentiment_hint(self, text: str) -> str:
        """Return a tiny deterministic sentiment hint from headline language."""

        lowered = text.lower()
        positive_words = {
            "beats",
            "beat",
            "raises",
            "upgrade",
            "surge",
            "record",
            "growth",
            "profit",
            "profits",
            "bullish",
            "wins",
            "revive",
        }
        negative_words = {
            "miss",
            "misses",
            "downgrade",
            "falls",
            "fall",
            "drop",
            "drops",
            "lawsuit",
            "probe",
            "warning",
            "bearish",
            "cut",
            "cuts",
        }
        positive_count = sum(1 for word in positive_words if word in lowered)
        negative_count = sum(1 for word in negative_words if word in lowered)
        if positive_count > negative_count:
            return "positive"
        if negative_count > positive_count:
            return "negative"
        if positive_count or negative_count:
            return "neutral"
        return "unknown"

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
            volatility_bars = sorted_bars[-30:]
            total_volume = sum(float(bar.volume or 0) for bar in sorted_bars)
            vwap_numerator = sum(
                float((bar.vwap or bar.close) or 0) * float(bar.volume or 0)
                for bar in sorted_bars
            )
            intraday_volatility = self._intraday_volatility_percent(volatility_bars)
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
                "intraday_volatility_percent": intraday_volatility,
                "volatility_regime": self._volatility_regime(intraday_volatility),
            }

        return profiles

    def _intraday_volatility_percent(self, bars: list[object]) -> float | None:
        """Return recent minute close-to-close realized volatility as percent."""

        closes = [float(getattr(bar, "close", 0) or 0) for bar in bars]
        returns = [
            (closes[index] - closes[index - 1]) / closes[index - 1]
            for index in range(1, len(closes))
            if closes[index - 1] > 0
        ]
        if len(returns) < 2:
            return None

        mean_return = sum(returns) / len(returns)
        variance = sum((item - mean_return) ** 2 for item in returns) / (len(returns) - 1)
        return math.sqrt(variance) * math.sqrt(len(returns)) * 100

    def _volatility_regime(self, volatility_percent: float | None) -> str:
        if volatility_percent is None:
            return "unknown"
        if volatility_percent < 0.15:
            return "calm"
        if volatility_percent < 0.45:
            return "normal"
        if volatility_percent < 0.90:
            return "elevated"
        return "extreme"

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
