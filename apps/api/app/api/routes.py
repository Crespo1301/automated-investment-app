"""API routes for the scaffolded control plane."""

from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.domain.models import (
    DashboardSnapshot,
    HandoffCatalog,
    PipelinePreview,
    SystemProfile,
)
from app.domain.trading import (
    AutopilotState,
    BrokerAccountStatus,
    DailyTradeRecap,
    DefragmentationReport,
    ExecutionIntent,
    ExitCheckResult,
    PipelineRunResult,
    PerformanceHistory,
    ProfitLockReport,
    ProtectionPlan,
    RiskLimits,
)
from app.domain.trading import (
    AuditSummary,
    BrokerReconciliationSnapshot,
    SafetyState,
    SymbolPerformanceHistory,
)
from app.services.broker_adapter import (
    PositionNotFoundError,
    get_active_alpaca_broker,
    get_alpaca_paper_broker,
)
from app.services.audit_store import (
    get_autopilot_state,
    get_daily_trade_recap,
    get_performance_history,
    get_symbol_performance_history,
    record_cancel_result,
    record_order_receipt,
    record_reconciliation_snapshot,
    set_kill_switch,
    summarize_audit,
)
from app.services.autopilot import disable_autopilot, enable_autopilot, run_autopilot_once
from app.services.exit_monitor import (
    get_defragmentation_report,
    get_profit_lock_report,
    run_exit_check,
)
from app.services.demo_data import (
    get_dashboard_snapshot,
    get_handoff_catalog,
    get_pipeline_preview,
    get_system_profile,
)
from app.services.local_worker import (
    get_risk_limits,
    run_queue_for_open_cycle,
    run_single_cycle,
)
from app.core.config import settings
from app.services.coid import coid_prefix_for, make_coid
from app.services.options_worker import recent_options_records
from app.services.protection_plan import build_protection_plan
from app.services.readiness import get_morning_readiness


router = APIRouter()


def require_operator_token(
    authorization: str | None = Header(default=None),
    x_operator_token: str | None = Header(default=None),
) -> None:
    """Require an operator token before API routes can mutate trading state."""

    configured_token = settings.operator_api_token
    if not configured_token:
        if settings.trading_mode == "live" or settings.allow_live_trading:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Operator API token is required before live trading controls can be used.",
            )
        return

    provided_token = x_operator_token
    if authorization and authorization.lower().startswith("bearer "):
        provided_token = authorization[7:].strip()

    if not provided_token or not compare_digest(provided_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid operator token required.",
        )


@router.get("/", tags=["system"])
def root() -> dict[str, str]:
    """Small landing endpoint to confirm the service is running."""

    return {
        "name": "automated-investment-api",
        "message": "Autonomous trading control plane is available.",
    }


@router.get("/api/system/profile", response_model=SystemProfile, tags=["system"])
def system_profile() -> SystemProfile:
    """Describe the operating assumptions for this scaffold."""

    return get_system_profile()


@router.get(
    "/api/dashboard/snapshot",
    response_model=DashboardSnapshot,
    tags=["dashboard"],
)
def dashboard_snapshot() -> DashboardSnapshot:
    """Return a demo snapshot for the operator dashboard shell."""

    return get_dashboard_snapshot()


@router.get(
    "/api/pipeline/preview",
    response_model=PipelinePreview,
    tags=["pipeline"],
)
def pipeline_preview() -> PipelinePreview:
    """Show how an event moves through signal, risk, and execution gates."""

    return get_pipeline_preview()


@router.get(
    "/api/pipeline/handoffs",
    response_model=HandoffCatalog,
    tags=["pipeline"],
)
def handoff_catalog() -> HandoffCatalog:
    """Return documented passthrough summaries for clients and future workers."""

    return get_handoff_catalog()


@router.get(
    "/api/trading/config",
    response_model=RiskLimits,
    tags=["trading"],
)
def trading_config() -> RiskLimits:
    """Return the active watchlist and risk limits for local trading."""

    return get_risk_limits()


@router.get(
    "/api/trading/morning-readiness",
    tags=["trading"],
)
def trading_morning_readiness() -> dict[str, object]:
    """Return the morning trading readiness checklist."""

    return get_morning_readiness()


@router.post(
    "/api/trading/local-cycle",
    response_model=PipelineRunResult,
    tags=["trading"],
    dependencies=[Depends(require_operator_token)],
)
def trading_local_cycle() -> PipelineRunResult:
    """Run one safe local pipeline cycle against demo market data."""

    return run_single_cycle()


@router.post(
    "/api/trading/run-cycle",
    response_model=PipelineRunResult,
    tags=["trading"],
    dependencies=[Depends(require_operator_token)],
)
def trading_run_cycle() -> PipelineRunResult:
    """Run one configured trading cycle through the active risk and broker path."""

    return run_single_cycle()


@router.post(
    "/api/trading/queue-for-open",
    response_model=PipelineRunResult,
    tags=["trading"],
    dependencies=[Depends(require_operator_token)],
)
def trading_queue_for_open() -> PipelineRunResult:
    """Queue one guarded regular-session order while the market is closed."""

    return run_queue_for_open_cycle()


@router.get(
    "/api/autopilot/status",
    response_model=AutopilotState,
    tags=["autopilot"],
)
def autopilot_status() -> AutopilotState:
    """Return the local supervised automation state."""

    return get_autopilot_state()


@router.post(
    "/api/autopilot/enable",
    response_model=AutopilotState,
    tags=["autopilot"],
    dependencies=[Depends(require_operator_token)],
)
def autopilot_enable(reason: str = "Enabled from dashboard.") -> AutopilotState:
    """Arm autopilot. A separate local loop process must still be running."""

    return enable_autopilot(reason=reason)


@router.post(
    "/api/autopilot/disable",
    response_model=AutopilotState,
    tags=["autopilot"],
    dependencies=[Depends(require_operator_token)],
)
def autopilot_disable(reason: str = "Disabled from dashboard.") -> AutopilotState:
    """Disarm autopilot."""

    return disable_autopilot(reason=reason)


@router.post(
    "/api/autopilot/tick",
    response_model=AutopilotState,
    tags=["autopilot"],
    dependencies=[Depends(require_operator_token)],
)
def autopilot_tick() -> AutopilotState:
    """Run one supervised autopilot check."""

    return run_autopilot_once()


@router.get(
    "/api/broker/alpaca/account",
    response_model=BrokerAccountStatus,
    tags=["broker"],
)
def alpaca_account_status() -> BrokerAccountStatus:
    """Read-only Alpaca account check. This endpoint never places orders."""

    return get_alpaca_paper_broker().get_account_status()


@router.get(
    "/api/broker/account",
    response_model=BrokerAccountStatus,
    tags=["broker"],
)
def active_broker_account_status() -> BrokerAccountStatus:
    """Read-only active broker account check for the current paper/live config."""

    return get_active_alpaca_broker().get_account_status()


@router.get(
    "/api/broker/alpaca/reconciliation",
    response_model=BrokerReconciliationSnapshot,
    tags=["broker"],
)
def alpaca_reconciliation() -> BrokerReconciliationSnapshot:
    """Read-only Alpaca orders and positions snapshot."""

    return get_alpaca_paper_broker().get_reconciliation_snapshot()


@router.get(
    "/api/broker/reconciliation",
    response_model=BrokerReconciliationSnapshot,
    tags=["broker"],
)
def active_broker_reconciliation() -> BrokerReconciliationSnapshot:
    """Read-only account, orders, and positions for the active paper/live config."""

    snapshot = get_active_alpaca_broker().get_reconciliation_snapshot(order_limit=100)
    record_reconciliation_snapshot(snapshot)
    return snapshot


@router.get(
    "/api/risk/protection-plan",
    response_model=ProtectionPlan,
    tags=["risk"],
)
def risk_protection_plan() -> ProtectionPlan:
    """Return a read-only position protection plan for operator review."""

    broker = get_active_alpaca_broker()
    snapshot = broker.get_reconciliation_snapshot(order_limit=50)
    record_reconciliation_snapshot(snapshot)
    return build_protection_plan(snapshot.positions, snapshot.orders)


@router.get(
    "/api/risk/exit-check",
    response_model=ExitCheckResult,
    tags=["risk"],
)
def risk_exit_check() -> ExitCheckResult:
    """Return current app-managed exit signals without submitting orders."""

    return run_exit_check(get_active_alpaca_broker(), execute=False)


@router.get(
    "/api/risk/profit-locks",
    response_model=ProfitLockReport,
    tags=["risk"],
)
def risk_profit_locks() -> ProfitLockReport:
    """Return profit-locked carries — positions whose TP signal was PDT-blocked."""

    return get_profit_lock_report(get_active_alpaca_broker())


@router.get(
    "/api/risk/defragmentation-candidates",
    response_model=DefragmentationReport,
    tags=["risk"],
)
def risk_defragmentation_candidates() -> DefragmentationReport:
    """Return stale tiny lots safe to liquidate without consuming a PDT slot."""

    return get_defragmentation_report(get_active_alpaca_broker())


@router.get(
    "/api/performance/history",
    response_model=PerformanceHistory,
    tags=["performance"],
)
def performance_history() -> PerformanceHistory:
    """Return recent local broker reconciliation history for charts."""

    return get_performance_history()


@router.get(
    "/api/performance/symbol-history",
    response_model=SymbolPerformanceHistory,
    tags=["performance"],
)
def symbol_performance_history() -> SymbolPerformanceHistory:
    """Return per-symbol performance history for multi-line dashboard charts."""

    return get_symbol_performance_history()


@router.get(
    "/api/performance/daily-recap",
    response_model=DailyTradeRecap,
    tags=["performance"],
)
def performance_daily_recap() -> DailyTradeRecap:
    """Return today's provider, strategy, and compounding recap."""

    return get_daily_trade_recap()


@router.get(
    "/api/options/recent",
    tags=["options"],
)
def options_recent(limit: int = 25) -> dict[str, object]:
    """Return the latest options-cycle records persisted by the worker."""

    return {
        "enabled": settings.options_enabled,
        "max_level": settings.options_max_level,
        "records": recent_options_records(limit=limit),
    }


@router.post(
    "/api/broker/cancel-open-orders",
    tags=["broker"],
    dependencies=[Depends(require_operator_token)],
)
def cancel_open_orders() -> dict[str, object]:
    """Cancel all currently open orders on the active broker configuration."""

    result = {
        "broker": "alpaca",
        "mode": "active-config",
        "canceled_orders": get_active_alpaca_broker().cancel_open_orders(),
    }
    record_cancel_result(result)
    return result


@router.post(
    "/api/broker/positions/{symbol}/sell-market",
    tags=["broker"],
    dependencies=[Depends(require_operator_token)],
)
def sell_position_market(
    symbol: str,
    force_pdt: bool = False,
    percent: float | None = None,
    dollars: float | None = None,
) -> dict[str, object]:
    """Submit a manual day market sell for an existing position.

    Sizing is one of three mutually exclusive forms:

    - neither ``percent`` nor ``dollars``: sell the whole position.
    - ``percent`` (greater than 0, at most 100): sell that share.
    - ``dollars`` (greater than 0): sell approximately that dollar amount.
      Alpaca only accepts a share quantity on a position sell, so the
      broker layer converts dollars to shares against live market value.

    By default, refuses to submit if the sell would be a same-day round
    trip AND the PDT cap is reached. The operator can override with
    ``?force_pdt=true`` to explicitly spend a PDT slot.
    """

    if percent is not None and dollars is not None:
        raise HTTPException(
            status_code=400,
            detail="Specify a sell size as percent or dollars, not both.",
        )
    if percent is not None and not 0 < percent <= 100:
        raise HTTPException(
            status_code=400,
            detail="percent must be greater than 0 and at most 100.",
        )
    if dollars is not None and dollars <= 0:
        raise HTTPException(
            status_code=400,
            detail="dollars must be greater than 0.",
        )

    broker = get_active_alpaca_broker()
    clock = broker.get_market_clock()
    if not clock.is_open:
        raise HTTPException(
            status_code=409,
            detail="Market is closed. Manual market sells are blocked from the dashboard until regular hours.",
        )

    if not force_pdt:
        guard = broker.get_day_trade_guard(symbol)
        if guard.would_be_day_trade and not guard.allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Manual sell of {symbol.upper()} would create a same-day round trip and the PDT cap "
                    f"is reached ({guard.day_trades_5_business_days}/{guard.max_day_trades_5_business_days}). "
                    "Hold overnight, or override with ?force_pdt=true if you accept burning a slot."
                ),
            )
        # Slot-conservation guard only applies when a real PDT cap is in force.
        # PDT was retired 2026-06-04 (cap configured to <=0 = unlimited), so
        # day-trade slots are not scarce and same-day rotations must not be
        # blocked to "preserve" a slot that no longer exists.
        if guard.would_be_day_trade and guard.max_day_trades_5_business_days > 0:
            remaining = max(
                0,
                guard.max_day_trades_5_business_days - guard.day_trades_5_business_days,
            )
            if remaining <= 1:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Manual sell of {symbol.upper()} would consume a PDT slot "
                        f"({guard.day_trades_5_business_days}/{guard.max_day_trades_5_business_days} used; "
                        f"{remaining} remaining). Hold overnight to preserve the slot, "
                        "or override with ?force_pdt=true."
                    ),
                )

    try:
        receipt = broker.submit_position_market_sell(
            symbol, percent=percent, dollars=dollars
        )
    except PositionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # Guard rejection on an existing position (sub-minimum notional, an
        # open sell already pending, partial rounds to zero). Not a missing
        # resource — surface as a 409 conflict so the dashboard shows why.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record_order_receipt(receipt)
    return {"broker": "alpaca", "mode": "active-config", "receipt": receipt.model_dump(mode="json")}


@router.post(
    "/api/broker/positions/{symbol}/buy-market",
    tags=["broker"],
    dependencies=[Depends(require_operator_token)],
)
def buy_position_market(
    symbol: str,
    dollars: float,
    force: bool = False,
) -> dict[str, object]:
    """Submit a manual notional market BUY for a discretionary, operator-chosen entry.

    This is the founded-entry path: an operator (or supervising Claude
    session) names the symbol and dollar size directly, instead of letting
    the deterministic scorer pick the candidate. It reuses the same broker
    submit path and the same risk gates the autopilot honors:

    - market-hours only (regular session);
    - spread guard (rejects if the live quote is wider than
      ``max_entry_spread_bps``);
    - cash-reserve + per-trade buying-power discipline (rejects a size that
      would breach the reserve or exceed available buying power);
    - ``max_open_positions`` cap for *new* symbols (adding to an existing
      lot is always allowed);
    - duplicate-order suppression within the session lookback window;
    - an idempotent ``client_order_id`` keyed on (UTC date, symbol, size),
      so an accidental re-submit of the same intent is a broker-side no-op.

    A fresh buy is the *opening* leg, so it never consumes a PDT day-trade
    slot on its own. ``force=true`` overrides the soft guards (spread,
    size, position-count) for a deliberate operator decision; it cannot
    override the market-hours or minimum-notional hard guards.
    """

    normalized = symbol.upper().strip()
    if dollars <= 0:
        raise HTTPException(status_code=400, detail="dollars must be greater than 0.")
    if dollars < settings.minimum_order_notional:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Buy size ${dollars:.2f} is below the ${settings.minimum_order_notional:.2f} "
                "minimum order notional."
            ),
        )

    broker = get_active_alpaca_broker()
    clock = broker.get_market_clock()
    if not clock.is_open:
        raise HTTPException(
            status_code=409,
            detail="Market is closed. Manual market buys are blocked from the dashboard until regular hours.",
        )

    account = broker.get_account_status()
    reserve = max(0.0, account.portfolio_value * settings.cash_reserve_percent_of_portfolio)
    available = account.buying_power - reserve
    if not force and dollars > available:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Buy size ${dollars:.2f} exceeds available buying power after the "
                f"{settings.cash_reserve_percent_of_portfolio:.0%} cash reserve "
                f"(buying_power ${account.buying_power:.2f} - reserve ${reserve:.2f} = ${available:.2f}). "
                "Lower the size or pass ?force=true to override the reserve."
            ),
        )
    if dollars > account.buying_power:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Buy size ${dollars:.2f} exceeds total buying power ${account.buying_power:.2f}. "
                "This hard guard cannot be forced."
            ),
        )

    held = {p.symbol.upper() for p in broker.list_positions()}
    if not force and normalized not in held and len(held) >= settings.max_open_positions:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Book is full at {len(held)}/{settings.max_open_positions} positions and "
                f"{normalized} is not already held. Free a slot first or pass ?force=true."
            ),
        )

    if not force:
        events = broker.list_watchlist_market_events([normalized])
        event = next((e for e in events if e.symbol.upper() == normalized), None)
        if event is not None and event.spread_bps is not None:
            if event.spread_bps > settings.max_entry_spread_bps:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{normalized} quote spread is {event.spread_bps:.1f} bps, wider than the "
                        f"{settings.max_entry_spread_bps:.0f} bps entry guard. Wait for tighter "
                        "liquidity or pass ?force=true."
                    ),
                )

    duplicate = broker.has_open_duplicate_order(
        normalized,
        side="buy",
        notional=dollars,
        strategy_prefix=coid_prefix_for("manual_entry"),
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"An open manual buy for {normalized} at ~${dollars:.2f} already exists "
                f"(order {duplicate.broker_order_id}). Not submitting a duplicate."
            ),
        )

    intent = ExecutionIntent(
        candidate_id="manual_entry",
        symbol=normalized,
        side="buy",
        approved_notional=round(dollars, 2),
        mode="live" if settings.allow_live_trading else "paper",
        client_order_id=make_coid(
            lane="manual_entry",
            symbol=normalized,
            discriminator=f"{normalized}:{round(dollars, 2)}",
        ),
    )
    receipt = broker.submit_order(intent)
    record_order_receipt(receipt)
    return {"broker": "alpaca", "mode": "active-config", "receipt": receipt.model_dump(mode="json")}


@router.post(
    "/api/broker/positions/{symbol}/protect-oco",
    tags=["broker"],
    dependencies=[Depends(require_operator_token)],
)
def protect_position_oco(symbol: str) -> dict[str, object]:
    """Submit broker-side OCO take-profit and stop-loss protection for a whole-share position."""

    broker = get_active_alpaca_broker()
    clock = broker.get_market_clock()
    if not clock.is_open:
        raise HTTPException(
            status_code=409,
            detail="Market is closed. Broker OCO protection is blocked from the dashboard until regular hours.",
        )

    try:
        receipt = broker.submit_position_oco_protection(symbol)
    except PositionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record_order_receipt(receipt)
    return {"broker": "alpaca", "mode": "active-config", "receipt": receipt.model_dump(mode="json")}


@router.get(
    "/api/safety/status",
    response_model=AuditSummary,
    tags=["safety"],
)
def safety_status() -> AuditSummary:
    """Return local audit, kill-switch, and active market-clock state."""

    broker = get_active_alpaca_broker()
    return summarize_audit(market_clock=broker.get_market_clock())


@router.post(
    "/api/safety/kill-switch/enable",
    response_model=SafetyState,
    tags=["safety"],
    dependencies=[Depends(require_operator_token)],
)
def enable_kill_switch(reason: str = "Enabled from API.") -> SafetyState:
    """Enable the local operator kill switch."""

    return set_kill_switch(True, reason=reason)


@router.post(
    "/api/safety/kill-switch/disable",
    response_model=SafetyState,
    tags=["safety"],
    dependencies=[Depends(require_operator_token)],
)
def disable_kill_switch() -> SafetyState:
    """Disable the local operator kill switch."""

    return set_kill_switch(False, reason="Disabled from API.")
