"""API routes for the scaffolded control plane."""

from fastapi import APIRouter

from app.domain.models import (
    DashboardSnapshot,
    HandoffCatalog,
    PipelinePreview,
    SystemProfile,
)
from app.domain.trading import BrokerAccountStatus, PipelineRunResult, RiskLimits
from app.domain.trading import AuditSummary, BrokerReconciliationSnapshot, SafetyState
from app.services.broker_adapter import get_active_alpaca_broker, get_alpaca_paper_broker
from app.services.audit_store import (
    record_cancel_result,
    record_reconciliation_snapshot,
    set_kill_switch,
    summarize_audit,
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
