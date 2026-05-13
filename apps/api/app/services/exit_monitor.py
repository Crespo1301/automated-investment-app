"""App-managed exit monitoring for fractional starter positions."""

from datetime import UTC, datetime, timedelta

from app.core.config import configured_high_vol_symbols, settings
from app.domain.trading import (
    BrokerOrderSummary,
    BrokerPositionSummary,
    DefragmentationCandidate,
    DefragmentationReport,
    ExitCheckResult,
    ExitSignal,
    ProfitLockEntry,
    ProfitLockReport,
)
from app.services.audit_store import (
    list_profit_locks,
    record_order_receipt,
    record_profit_lock,
)


def evaluate_exit_signals(
    positions: list[BrokerPositionSummary],
    orders: list[BrokerOrderSummary],
    *,
    execution_allowed: bool,
    portfolio_value: float | None = None,
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
        stop_loss_percent = _stop_loss_percent(position.symbol)
        stop_price = average_entry_price * (1 - stop_loss_percent / 100)
        small_win_percent = _small_win_percent(portfolio_value)
        small_win_price = average_entry_price * (1 + small_win_percent / 100)
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
            small_win_execution_allowed = execution_allowed and _small_win_hold_satisfied(
                position.symbol,
                orders,
                portfolio_value=portfolio_value,
            )
            signals.append(
                ExitSignal(
                    symbol=position.symbol,
                    reason="small_win",
                    current_price=position.current_price,
                    average_entry_price=average_entry_price,
                    trigger_price=round(small_win_price, 2),
                    quantity=position.quantity,
                    market_value=position.market_value,
                    execution_allowed=small_win_execution_allowed,
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
    portfolio_value = getattr(getattr(snapshot, "account", None), "portfolio_value", None)

    signals = evaluate_exit_signals(
        snapshot.positions,
        snapshot.orders,
        execution_allowed=execution_allowed,
        portfolio_value=portfolio_value,
    )
    submitted_receipts = []
    blocked_reasons: list[str] = []

    if execution_allowed:
        positions_by_symbol = {position.symbol.upper(): position for position in snapshot.positions}
        for signal in signals:
            if not signal.execution_allowed:
                blocked_reasons.append(
                    f"{signal.symbol}: small-win exit is waiting for the minimum holding window."
                )
                continue
            day_trade_guard = _day_trade_guard(broker, signal.symbol)
            position = positions_by_symbol.get(signal.symbol.upper())
            if (
                signal.reason == "small_win"
                and day_trade_guard is not None
                and day_trade_guard.would_be_day_trade
                and position is not None
                and not _small_win_can_spend_pdt_slot(
                    position,
                    day_trade_guard,
                    portfolio_value=portfolio_value,
                )
            ):
                blocked_reasons.append(
                    f"{signal.symbol}: small-win exit held to preserve PDT slot; estimated net "
                    f"${_estimated_net_profit(position):.2f} below "
                    f"${_small_win_min_net_profit(portfolio_value):.2f} floor."
                )
                signal.execution_allowed = False
                continue
            if day_trade_guard is not None and not day_trade_guard.allowed:
                # Persistent take-profit lockouts: stop spamming heartbeats by
                # marking the position profit-locked. The lock is keyed by
                # symbol+session so subsequent ticks treat it as a known
                # carry rather than re-emitting blocked exit noise.
                if signal.reason == "take_profit" and position is not None:
                    record_profit_lock(
                        symbol=signal.symbol,
                        current_price=signal.current_price,
                        average_entry_price=signal.average_entry_price,
                        unrealized_pl=position.unrealized_pl,
                        market_value=position.market_value,
                        block_reason=day_trade_guard.reason or "PDT day-trade cap reached.",
                    )
                blocked_reasons.append(f"{signal.symbol}: {day_trade_guard.reason}")
                signal.execution_allowed = False
                continue
            receipt = broker.submit_position_market_sell(signal.symbol)
            record_order_receipt(receipt)
            submitted_receipts.append(receipt)

    notes = [
        "Exit monitor is app-managed and uses market sells during regular market hours.",
        "Existing open sell orders suppress duplicate exit signals.",
        f"Positions below ${settings.minimum_order_notional:.2f} market value are skipped to avoid sub-dollar trade attempts.",
    ]
    if portfolio_value is not None and portfolio_value <= settings.low_portfolio_threshold:
        notes.append(
            f"Low-portfolio mode is active: small-win exits require {settings.low_portfolio_small_win_percent:.1f}% "
            f"and at least {settings.small_win_min_holding_minutes} holding minutes."
        )
    notes.append(
        "PDT allocator reserves scarce day-trade slots for stop-losses and high-value exits before small wins."
    )
    if not market_is_open and not settings.allow_outside_market_hours:
        notes.append("Exit execution is locked because the regular market is closed.")
    if signals and not execution_allowed:
        notes.append("Exit signal found, but execution is locked by INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=false.")
    notes.extend(blocked_reasons)

    # Surface persistent profit-locked carries so the operator sees them
    # without scrolling through repeated blocked-reason rows.
    locked = [lock for lock in list_profit_locks()
              if (lock.get("symbol") or "").upper()
              in {p.symbol.upper() for p in snapshot.positions}]
    if locked:
        symbols = ", ".join(sorted({(l.get("symbol") or "").upper() for l in locked}))
        notes.append(f"Profit-locked carry (sell next session): {symbols}")

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


def _small_win_percent(portfolio_value: float | None) -> float:
    if portfolio_value is not None and portfolio_value <= settings.low_portfolio_threshold:
        return max(settings.autopilot_small_win_percent, settings.low_portfolio_small_win_percent)

    return settings.autopilot_small_win_percent


def _stop_loss_percent(symbol: str) -> float:
    if symbol.upper() in configured_high_vol_symbols():
        return settings.high_vol_stop_loss_percent

    return settings.autopilot_stop_loss_percent


def _estimated_net_profit(position: BrokerPositionSummary) -> float:
    half_spread_rate = max(0.0, settings.max_entry_spread_bps) / 2 / 10_000
    estimated_round_trip_spread = (position.market_value + position.cost_basis) * half_spread_rate
    return position.unrealized_pl - estimated_round_trip_spread


def _small_win_can_spend_pdt_slot(
    position: BrokerPositionSummary,
    day_trade_guard: object,
    *,
    portfolio_value: float | None = None,
) -> bool:
    slots_remaining = max(
        0,
        day_trade_guard.max_day_trades_5_business_days
        - day_trade_guard.day_trades_5_business_days,
    )
    if slots_remaining < settings.small_win_min_pdt_slots_to_exit:
        return False

    return _estimated_net_profit(position) >= _small_win_min_net_profit(portfolio_value)


def _small_win_min_net_profit(portfolio_value: float | None) -> float:
    """At low NAV, require a larger net win before spending a PDT slot."""

    base = settings.small_win_min_net_profit_dollars
    if portfolio_value is None:
        return base
    if portfolio_value > settings.low_portfolio_threshold:
        return base
    low_nav_floor = getattr(
        settings,
        "low_nav_small_win_min_net_profit_dollars",
        base,
    )
    return max(base, float(low_nav_floor))


def _small_win_hold_satisfied(
    symbol: str,
    orders: list[BrokerOrderSummary],
    *,
    portfolio_value: float | None,
) -> bool:
    if portfolio_value is None or portfolio_value > settings.low_portfolio_threshold:
        return True

    required_minutes = max(0, settings.small_win_min_holding_minutes)
    if required_minutes == 0:
        return True

    latest_buy = _latest_filled_buy(symbol, orders)
    if latest_buy is None or latest_buy.filled_at is None:
        return False

    held_for = datetime.now(UTC) - latest_buy.filled_at.astimezone(UTC)
    return held_for.total_seconds() >= required_minutes * 60


def _latest_filled_buy(
    symbol: str,
    orders: list[BrokerOrderSummary],
) -> BrokerOrderSummary | None:
    buys = [
        order
        for order in orders
        if order.symbol.upper() == symbol.upper()
        and order.side.split(".")[-1].lower() == "buy"
        and order.status.split(".")[-1].lower() == "filled"
        and order.filled_quantity > 0
        and order.filled_at is not None
    ]
    if not buys:
        return None

    return max(buys, key=lambda order: order.filled_at)


def _market_is_open(broker: object) -> bool:
    get_market_clock = getattr(broker, "get_market_clock", None)
    if get_market_clock is None:
        return True

    clock = get_market_clock()
    return bool(getattr(clock, "is_open", False))


def _day_trade_guard(broker: object, symbol: str):
    get_day_trade_guard = getattr(broker, "get_day_trade_guard", None)
    if get_day_trade_guard is None:
        return None

    return get_day_trade_guard(symbol)


def get_profit_lock_report(broker: object) -> ProfitLockReport:
    """Return all profit-locked positions still open at the broker.

    Locks that no longer correspond to a held position are cleared in the
    return view (the audit row stays for replay). The report is the
    operator-facing summary of "TP signal blocked by PDT — held for next
    session."
    """

    snapshot = broker.get_reconciliation_snapshot(order_limit=20)
    open_symbols = {pos.symbol.upper() for pos in snapshot.positions}
    raw_locks = list_profit_locks()
    entries: list[ProfitLockEntry] = []
    for lock in raw_locks:
        symbol = (lock.get("symbol") or "").upper()
        if symbol and symbol in open_symbols:
            entries.append(
                ProfitLockEntry(
                    symbol=symbol,
                    locked_at=lock.get("locked_at"),
                    block_reason=lock.get("block_reason") or "",
                    average_entry_price=lock.get("average_entry_price"),
                    current_price=lock.get("current_price"),
                    market_value=lock.get("market_value"),
                    unrealized_pl=lock.get("unrealized_pl"),
                )
            )
    notes = []
    if entries:
        notes.append(
            "Profit-locked positions: a take-profit signal fired but PDT prevented the sell. "
            "Treat as next-session priority exits — do not let the gain roll back."
        )
    return ProfitLockReport(entries=entries, notes=notes)


def get_defragmentation_report(broker: object) -> DefragmentationReport:
    """Surface stale tiny lots safe to liquidate for buying-power reclaim.

    A position is a defrag candidate when:
      - market value is at or below ``defragmentation_max_market_value_dollars``
      - the most recent buy fill is older than the small-win min holding
        window (i.e., selling now would not be a day trade)
      - there is no open sell order already working

    The report is read-only; the operator chooses whether to act on it.
    """

    snapshot = broker.get_reconciliation_snapshot(order_limit=50)
    max_value = float(
        getattr(settings, "defragmentation_max_market_value_dollars", 3.0)
    )
    min_age_minutes = max(0, settings.small_win_min_holding_minutes)
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=min_age_minutes)

    candidates: list[DefragmentationCandidate] = []
    for position in snapshot.positions:
        if position.market_value <= 0 or position.market_value > max_value:
            continue
        if _has_open_sell_order(position.symbol, snapshot.orders):
            continue
        latest_buy = _latest_filled_buy(position.symbol, snapshot.orders)
        if latest_buy is None or latest_buy.filled_at is None:
            continue
        filled_at = latest_buy.filled_at.astimezone(UTC)
        if filled_at > cutoff:
            continue
        candidates.append(
            DefragmentationCandidate(
                symbol=position.symbol,
                market_value=position.market_value,
                unrealized_pl=position.unrealized_pl,
                last_buy_filled_at=filled_at,
                age_minutes=int((now - filled_at).total_seconds() // 60),
            )
        )

    candidates.sort(key=lambda c: c.market_value)
    notes = [
        f"Lots at or below ${max_value:.2f} market value held >{min_age_minutes//60}h "
        "are listed for optional liquidation to reclaim buying power.",
        "Selling these does NOT consume a PDT slot because the buy is older than today's session.",
    ]
    return DefragmentationReport(candidates=candidates, notes=notes)
