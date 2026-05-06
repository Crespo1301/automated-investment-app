"""Trading pipeline contracts.

These models are the typed passthroughs between strategy detection, AI scoring,
risk validation, and broker execution. Keep them narrow and explicit so future
live trading behavior remains auditable.
"""

from datetime import UTC, datetime
from typing import Literal
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


class BrokerReconciliationSnapshot(BaseModel):
    """Read-only snapshot of broker account state after submissions."""

    account: BrokerAccountStatus
    orders: list[BrokerOrderSummary]
    positions: list[BrokerPositionSummary]


class PipelineRunResult(BaseModel):
    """One local worker cycle result for debugging and dashboard previews."""

    event: MarketEvent
    candidate: TradeCandidate | None
    scored_candidate: ScoredTradeCandidate | None
    risk_decision: RiskDecision | None
    execution_intent: ExecutionIntent | None
    broker_receipt: BrokerOrderReceipt | None
