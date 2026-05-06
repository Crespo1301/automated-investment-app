"""API routes for the scaffolded control plane."""

from fastapi import APIRouter

from app.domain.models import (
    DashboardSnapshot,
    HandoffCatalog,
    PipelinePreview,
    SystemProfile,
)
from app.domain.trading import BrokerAccountStatus, PipelineRunResult, RiskLimits
from app.domain.trading import BrokerReconciliationSnapshot
from app.services.broker_adapter import get_alpaca_paper_broker
from app.services.demo_data import (
    get_dashboard_snapshot,
    get_handoff_catalog,
    get_pipeline_preview,
    get_system_profile,
)
from app.services.local_worker import get_risk_limits, run_single_cycle


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


@router.get(
    "/api/broker/alpaca/account",
    response_model=BrokerAccountStatus,
    tags=["broker"],
)
def alpaca_account_status() -> BrokerAccountStatus:
    """Read-only Alpaca account check. This endpoint never places orders."""

    return get_alpaca_paper_broker().get_account_status()


@router.get(
    "/api/broker/alpaca/reconciliation",
    response_model=BrokerReconciliationSnapshot,
    tags=["broker"],
)
def alpaca_reconciliation() -> BrokerReconciliationSnapshot:
    """Read-only Alpaca orders and positions snapshot."""

    return get_alpaca_paper_broker().get_reconciliation_snapshot()
