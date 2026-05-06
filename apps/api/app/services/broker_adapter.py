"""Broker adapter layer.

The local paper broker is safe for tests and demos. The Alpaca adapter is
constructed only when credentials are present and can target paper or live
depending on runtime settings.
"""

from app.core.config import settings
from app.domain.trading import (
    BrokerAccountStatus,
    BrokerOrderReceipt,
    BrokerOrderSummary,
    BrokerPositionSummary,
    BrokerReconciliationSnapshot,
    ExecutionIntent,
    new_id,
)


class MissingBrokerCredentialsError(RuntimeError):
    """Raised when a broker operation needs credentials that are not configured."""

    def __init__(self, missing_names: list[str]) -> None:
        self.missing_names = missing_names
        super().__init__(
            "Missing broker credentials: " + ", ".join(missing_names)
        )


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

        from alpaca.trading.client import TradingClient

        self.client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
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
