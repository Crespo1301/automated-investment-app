"""API routes for the scaffolded control plane."""

from fastapi import APIRouter, HTTPException

from app.domain.models import (
    DashboardSnapshot,
    HandoffCatalog,
    PipelinePreview,
    SystemProfile,
)
from app.domain.trading import (
    AutopilotState,
    BrokerAccountStatus,
    ExitCheckResult,
    PipelineRunResult,
    PerformanceHistory,
    ProtectionPlan,
    RiskLimits,
)
from app.domain.trading import AuditSummary, BrokerReconciliationSnapshot, SafetyState
from app.services.broker_adapter import get_active_alpaca_broker, get_alpaca_paper_broker
from app.services.audit_store import (
    get_autopilot_state,
    get_performance_history,
    record_cancel_result,
    record_order_receipt,
    record_reconciliation_snapshot,
    set_kill_switch,
    summarize_audit,
)
from app.services.autopilot import disable_autopilot, enable_autopilot, run_autopilot_once
from app.services.exit_monitor import run_exit_check
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
from app.services.protection_plan import build_protection_plan


router = APIRouter()


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


@router.post(
    "/api/trading/local-cycle",
    response_model=PipelineRunResult,
    tags=["trading"],
)
def trading_local_cycle() -> PipelineRunResult:
    """Run one safe local pipeline cycle against demo market data."""

    return run_single_cycle()


@router.post(
    "/api/trading/run-cycle",
    response_model=PipelineRunResult,
    tags=["trading"],
)
def trading_run_cycle() -> PipelineRunResult:
    """Run one configured trading cycle through the active risk and broker path."""

    return run_single_cycle()


@router.post(
    "/api/trading/queue-for-open",
    response_model=PipelineRunResult,
    tags=["trading"],
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
)
def autopilot_enable(reason: str = "Enabled from dashboard.") -> AutopilotState:
    """Arm autopilot. A separate local loop process must still be running."""

    return enable_autopilot(reason=reason)


@router.post(
    "/api/autopilot/disable",
    response_model=AutopilotState,
    tags=["autopilot"],
)
def autopilot_disable(reason: str = "Disabled from dashboard.") -> AutopilotState:
    """Disarm autopilot."""

    return disable_autopilot(reason=reason)


@router.post(
    "/api/autopilot/tick",
    response_model=AutopilotState,
    tags=["autopilot"],
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

    snapshot = get_active_alpaca_broker().get_reconciliation_snapshot()
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
    "/api/performance/history",
    response_model=PerformanceHistory,
    tags=["performance"],
)
def performance_history() -> PerformanceHistory:
    """Return recent local broker reconciliation history for charts."""

    return get_performance_history()


@router.post(
    "/api/broker/cancel-open-orders",
    tags=["broker"],
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
)
def sell_position_market(symbol: str) -> dict[str, object]:
    """Submit a manual day market sell for an existing position."""

    broker = get_active_alpaca_broker()
    clock = broker.get_market_clock()
    if not clock.is_open:
        raise HTTPException(
            status_code=409,
            detail="Market is closed. Manual market sells are blocked from the dashboard until regular hours.",
        )

    try:
        receipt = broker.submit_position_market_sell(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
)
def enable_kill_switch(reason: str = "Enabled from API.") -> SafetyState:
    """Enable the local operator kill switch."""

    return set_kill_switch(True, reason=reason)


@router.post(
    "/api/safety/kill-switch/disable",
    response_model=SafetyState,
    tags=["safety"],
)
def disable_kill_switch() -> SafetyState:
    """Disable the local operator kill switch."""

    return set_kill_switch(False, reason="Disabled from API.")
