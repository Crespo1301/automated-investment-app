"""Read-only position protection planning for supervised automation."""

from app.domain.trading import (
    BrokerOrderSummary,
    BrokerPositionSummary,
    PositionProtectionPlan,
    ProtectionPlan,
)
from app.core.config import settings


def build_protection_plan(
    positions: list[BrokerPositionSummary],
    orders: list[BrokerOrderSummary],
) -> ProtectionPlan:
    """Return an operator-facing view of exit readiness.

    This does not submit stop orders. It surfaces whether each live position has
    an obvious open sell order and suggests a starter stop level for review.
    """

    if not positions:
        return ProtectionPlan(
            status="no_positions",
            plans=[],
            notes=[
                "No open broker positions were returned.",
                "Autopilot entries remain locked until exit protection is intentionally enabled.",
            ],
        )

    plans = [_plan_position(position, orders) for position in positions]
    statuses = {plan.status for plan in plans}
    if "unprotected" in statuses:
        status = "unprotected"
    elif "needs_review" in statuses:
        status = "needs_review"
    else:
        status = "ready"

    return ProtectionPlan(
        status=status,
        plans=plans,
        notes=[
            "This is a read-only protection plan, not an executed stop order.",
            "Add broker-backed stop or bracket orders before allowing unattended entries.",
        ],
    )


def _plan_position(
    position: BrokerPositionSummary,
    orders: list[BrokerOrderSummary],
) -> PositionProtectionPlan:
    open_sell_order = _has_open_sell_order(position.symbol, orders)
    current_price = position.current_price
    average_entry_price = (
        position.cost_basis / position.quantity
        if position.quantity > 0 and position.cost_basis > 0
        else None
    )
    stop_reference = average_entry_price or current_price
    suggested_stop_price = (
        round(stop_reference * (1 - settings.autopilot_stop_loss_percent / 100), 2)
        if stop_reference
        else None
    )
    suggested_take_profit_price = (
        round(stop_reference * (1 + settings.autopilot_take_profit_percent / 100), 2)
        if stop_reference
        else None
    )
    suggested_stop_notional = (
        round(position.quantity * suggested_stop_price, 2)
        if suggested_stop_price is not None
        else None
    )
    notes = [
        "Suggested stop is a starter 2% review level, not financial advice.",
    ]

    if open_sell_order:
        status = "needs_review"
        notes.append("An open sell order exists. Confirm it is the intended protective exit.")
    else:
        status = "unprotected"
        notes.append("No open sell order was found for this position.")

    return PositionProtectionPlan(
        symbol=position.symbol,
        quantity=position.quantity,
        market_value=position.market_value,
        current_price=current_price,
        average_entry_price=average_entry_price,
        suggested_stop_price=suggested_stop_price,
        suggested_take_profit_price=suggested_take_profit_price,
        suggested_stop_notional=suggested_stop_notional,
        status=status,
        notes=notes,
    )


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
