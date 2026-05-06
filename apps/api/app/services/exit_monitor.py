"""App-managed exit monitoring for fractional starter positions."""

from app.core.config import settings
from app.domain.trading import (
    BrokerOrderSummary,
    BrokerPositionSummary,
    ExitCheckResult,
    ExitSignal,
)
from app.services.audit_store import record_order_receipt


def evaluate_exit_signals(
    positions: list[BrokerPositionSummary],
    orders: list[BrokerOrderSummary],
    *,
    execution_allowed: bool,
) -> list[ExitSignal]:
    """Return stop-loss and take-profit signals for open long positions."""

    signals: list[ExitSignal] = []
    for position in positions:
        if position.quantity <= 0 or position.current_price is None or position.cost_basis <= 0:
            continue
        if position.market_value < settings.minimum_order_notional:
            continue
        if _has_open_sell_order(position.symbol, orders):
            continue

        average_entry_price = position.cost_basis / position.quantity
        stop_price = average_entry_price * (1 - settings.autopilot_stop_loss_percent / 100)
        small_win_price = average_entry_price * (1 + settings.autopilot_small_win_percent / 100)
        take_profit_price = average_entry_price * (1 + settings.autopilot_take_profit_percent / 100)

        if position.current_price <= stop_price:
            signals.append(
                ExitSignal(
                    symbol=position.symbol,
                    reason="stop_loss",
                    current_price=position.current_price,
                    average_entry_price=average_entry_price,
                    trigger_price=round(stop_price, 2),
                    quantity=position.quantity,
                    market_value=position.market_value,
                    execution_allowed=execution_allowed,
                )
            )
        elif position.current_price >= take_profit_price:
            signals.append(
                ExitSignal(
                    symbol=position.symbol,
                    reason="take_profit",
                    current_price=position.current_price,
                    average_entry_price=average_entry_price,
                    trigger_price=round(take_profit_price, 2),
                    quantity=position.quantity,
                    market_value=position.market_value,
                    execution_allowed=execution_allowed,
                )
            )
        elif position.current_price >= small_win_price:
            signals.append(
                ExitSignal(
                    symbol=position.symbol,
                    reason="small_win",
                    current_price=position.current_price,
                    average_entry_price=average_entry_price,
                    trigger_price=round(small_win_price, 2),
                    quantity=position.quantity,
                    market_value=position.market_value,
                    execution_allowed=execution_allowed,
                )
            )

    return signals


def run_exit_check(broker: object, *, execute: bool) -> ExitCheckResult:
    """Evaluate open positions and optionally submit market sell exits."""

    snapshot = broker.get_reconciliation_snapshot(order_limit=50)
    execution_allowed = execute and settings.autopilot_allow_exits
    market_is_open = _market_is_open(broker)
    if execution_allowed and not market_is_open and not settings.allow_outside_market_hours:
        execution_allowed = False

    signals = evaluate_exit_signals(
        snapshot.positions,
        snapshot.orders,
        execution_allowed=execution_allowed,
    )
    submitted_receipts = []

    if execution_allowed:
        for signal in signals:
            receipt = broker.submit_position_market_sell(signal.symbol)
            record_order_receipt(receipt)
            submitted_receipts.append(receipt)

    notes = [
        "Exit monitor is app-managed and uses market sells during regular market hours.",
        "Existing open sell orders suppress duplicate exit signals.",
        f"Positions below ${settings.minimum_order_notional:.2f} market value are skipped to avoid sub-dollar trade attempts.",
    ]
    if not market_is_open and not settings.allow_outside_market_hours:
        notes.append("Exit execution is locked because the regular market is closed.")
    if signals and not execution_allowed:
        notes.append("Exit signal found, but execution is locked by INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=false.")

    return ExitCheckResult(signals=signals, submitted_receipts=submitted_receipts, notes=notes)


def _has_open_sell_order(symbol: str, orders: list[BrokerOrderSummary]) -> bool:
    open_statuses = {
        "accepted",
        "new",
        "pending_new",
        "partially_filled",
        "pending_replace",
        "pending_cancel",
    }
    for order in orders:
        status = order.status.split(".")[-1].lower()
        side = order.side.split(".")[-1].lower()
        if order.symbol.upper() == symbol.upper() and side == "sell" and status in open_statuses:
            return True

    return False


def _market_is_open(broker: object) -> bool:
    get_market_clock = getattr(broker, "get_market_clock", None)
    if get_market_clock is None:
        return True

    clock = get_market_clock()
    return bool(getattr(clock, "is_open", False))
