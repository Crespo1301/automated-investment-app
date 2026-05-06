"""Trading pipeline contracts.

These models are the typed passthroughs between strategy detection, AI scoring,
risk validation, and broker execution. Keep them narrow and explicit so future
live trading behavior remains auditable.
"""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


TradingMode = Literal["paper", "live"]
TradeSide = Literal["buy", "sell"]
RiskState = Literal["approved", "rejected"]


def new_id(prefix: str) -> str:
    """Create a readable correlation id for audit joins."""

    return f"{prefix}_{uuid4().hex}"


class MarketEvent(BaseModel):
    """Normalized market event emitted by market ingress."""

    correlation_id: str = Field(default_factory=lambda: new_id("evt"))
    source: str
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_kind: Literal["bar", "trade", "quote"]
    price: float
    volume: float
    previous_close: float | None = None
    session_state: Literal["pre_market", "regular", "after_hours", "closed"] = "regular"


class TradeCandidate(BaseModel):
    """Strategy-created candidate before AI or risk review."""

    candidate_id: str = Field(default_factory=lambda: new_id("cand"))
    correlation_id: str
    strategy_id: str
    symbol: str
    side: TradeSide
    proposed_notional: float
    proposed_entry: float
    proposed_stop: float
    trigger_evidence: list[str]
    confidence_hint: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AIScore(BaseModel):
    """AI enrichment that stays advisory rather than authoritative."""

    model_name: str
    score: float = Field(ge=0, le=1)
    summary: str
    concerns: list[str]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScoredTradeCandidate(BaseModel):
    """Trade candidate after AI enrichment."""

    candidate: TradeCandidate
    ai_score: AIScore


class PortfolioState(BaseModel):
    """Current portfolio state needed by the risk gate."""

    open_positions: int = 0
    live_trades_today: int = 0
    realized_pnl_today: float = 0
    buying_power: float = 10
    trading_mode: TradingMode = "paper"


class RiskLimits(BaseModel):
    """Operator-defined guardrails for autonomous execution."""

    allowed_symbols: list[str]
    max_notional_per_trade: float
    max_open_positions: int
    max_live_trades_per_day: int
    max_daily_loss: float
    allow_live_trading: bool
    allow_outside_market_hours: bool = False
    duplicate_order_lookback_minutes: int = 390


class MarketClockStatus(BaseModel):
    """Broker market clock state used to block unintended queued orders."""

    is_open: bool
    timestamp: datetime | None = None
    next_open: datetime | None = None
    next_close: datetime | None = None


class SafetyState(BaseModel):
    """Operator safety state persisted outside broker state."""

    kill_switch_enabled: bool = False
    reason: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AutopilotState(BaseModel):
    """Local supervised automation state."""

    enabled: bool = False
    reason: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_at: datetime | None = None
    last_action: str | None = None
    last_error: str | None = None
    interval_seconds: int = 300
    market_open_only: bool = True
    entry_execution_enabled: bool = False
    exit_execution_enabled: bool = False


class RiskDecision(BaseModel):
    """Risk engine output for a scored trade candidate."""

    decision_id: str = Field(default_factory=lambda: new_id("risk"))
    state: RiskState
    candidate_id: str
    approved_notional: float = 0
    reasons: list[str]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExecutionIntent(BaseModel):
    """Final broker-facing instruction after risk approval."""

    intent_id: str = Field(default_factory=lambda: new_id("intent"))
    candidate_id: str
    symbol: str
    side: TradeSide
    order_type: Literal["market"] = "market"
    session_policy: Literal["immediate", "regular_open_queue"] = "immediate"
    approved_notional: float
    mode: TradingMode
    client_order_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BrokerOrderReceipt(BaseModel):
    """Broker response normalized for audit and dashboard state."""

    broker_order_id: str
    intent_id: str
    status: str
    symbol: str
    side: TradeSide
    submitted_notional: float
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_message: str | None = None


class BrokerAccountStatus(BaseModel):
    """Read-only broker account status with no secret fields."""

    broker: str
    account_mode: TradingMode
    account_id_hint: str
    status: str
    currency: str
    buying_power: float
    cash: float
    portfolio_value: float
    pattern_day_trader: bool | None = None


class BrokerOrderSummary(BaseModel):
    """Normalized broker order row for reconciliation and dashboards."""

    broker_order_id: str
    client_order_id: str | None = None
    symbol: str
    side: str
    order_type: str
    status: str
    submitted_quantity: float | None = None
    submitted_notional: float | None = None
    filled_quantity: float
    filled_average_price: float | None = None
    submitted_at: datetime | None = None
    filled_at: datetime | None = None


class BrokerPositionSummary(BaseModel):
    """Normalized broker position row for portfolio reconciliation."""

    symbol: str
    quantity: float
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_pl_percent: float
    current_price: float | None = None


class PositionProtectionPlan(BaseModel):
    """Operator-facing protection status for one broker position."""

    symbol: str
    quantity: float
    market_value: float
    current_price: float | None = None
    average_entry_price: float | None = None
    suggested_stop_price: float | None = None
    suggested_take_profit_price: float | None = None
    suggested_stop_notional: float | None = None
    status: Literal["protected", "needs_review", "unprotected"]
    notes: list[str]


class ExitSignal(BaseModel):
    """Autopilot exit signal for one open position."""

    symbol: str
    reason: Literal["stop_loss", "take_profit"]
    current_price: float
    average_entry_price: float
    trigger_price: float
    quantity: float
    market_value: float
    execution_allowed: bool


class ExitCheckResult(BaseModel):
    """Read-only or executed exit-monitor result."""

    signals: list[ExitSignal]
    submitted_receipts: list[BrokerOrderReceipt]
    notes: list[str]


class ProtectionPlan(BaseModel):
    """Portfolio-level exit/protection readiness."""

    status: Literal["no_positions", "ready", "needs_review", "unprotected"]
    plans: list[PositionProtectionPlan]
    notes: list[str]


class PerformancePoint(BaseModel):
    """Historical account value point for dashboard charts."""

    timestamp: datetime
    portfolio_value: float
    buying_power: float
    cash: float
    open_orders: int
    open_positions: int


class PerformanceHistory(BaseModel):
    """Recent local performance history from broker reconciliation snapshots."""

    points: list[PerformancePoint]
    notes: list[str]


class BrokerReconciliationSnapshot(BaseModel):
    """Read-only snapshot of broker account state after submissions."""

    account: BrokerAccountStatus
    orders: list[BrokerOrderSummary]
    positions: list[BrokerPositionSummary]


class AuditSummary(BaseModel):
    """Compact local audit status for the operator dashboard."""

    pipeline_runs: int = 0
    reconciliation_snapshots: int = 0
    order_events: int = 0
    last_event_at: datetime | None = None
    latest_order_status: str | None = None
    latest_order_symbol: str | None = None
    latest_order_notional: float | None = None
    safety_state: SafetyState = Field(default_factory=SafetyState)
    autopilot_state: AutopilotState = Field(default_factory=AutopilotState)
    market_clock: MarketClockStatus | None = None
    notes: list[str] = Field(default_factory=list)


class PipelineRunResult(BaseModel):
    """One local worker cycle result for debugging and dashboard previews."""

    event: MarketEvent
    candidate: TradeCandidate | None
    scored_candidate: ScoredTradeCandidate | None
    risk_decision: RiskDecision | None
    execution_intent: ExecutionIntent | None
    broker_receipt: BrokerOrderReceipt | None


class AuditEvent(BaseModel):
    """Append-only local audit event with a typed payload."""

    event_id: str = Field(default_factory=lambda: new_id("audit"))
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
