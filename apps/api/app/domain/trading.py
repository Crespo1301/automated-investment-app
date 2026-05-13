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
ScoreProvenance = Literal["anthropic", "openai", "local"]

# Options primitives. Level 1 (Alpaca approval today) allows only
# ``sell_to_open`` of ``covered_call_v1`` and ``cash_secured_put_v1``.
# Level 2 will add ``long_call_v1`` / ``long_put_v1`` (``buy_to_open``).
# Level 3 adds multi-leg spreads (out of scope for the foundation).
OptionContractType = Literal["call", "put"]
OptionAction = Literal[
    "buy_to_open",
    "sell_to_open",
    "buy_to_close",
    "sell_to_close",
]
OptionsStrategyId = Literal[
    "covered_call_v1",
    "cash_secured_put_v1",
    "long_call_v1",
    "long_put_v1",
]
OptionsTradingLevel = Literal[0, 1, 2, 3]
VolatilityRegime = Literal["unknown", "calm", "normal", "elevated", "extreme"]
MarketRegime = Literal["unknown", "risk_on", "neutral", "risk_off"]
NewsSentimentHint = Literal["unknown", "positive", "neutral", "negative"]


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
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    day_volume: float | None = None
    previous_volume: float | None = None
    vwap: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    recent_high: float | None = None
    recent_low: float | None = None
    recent_volume: float | None = None
    average_recent_volume: float | None = None
    previous_bar_close: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    spread_bps: float | None = None
    quote_depth: float | None = None
    orderbook_imbalance: float | None = None
    intraday_volatility_percent: float | None = None
    volatility_regime: VolatilityRegime = "unknown"
    market_move_percent: float | None = None
    market_regime: MarketRegime = "unknown"
    news_count_24h: int | None = None
    latest_news_headline: str | None = None
    news_sentiment_hint: NewsSentimentHint = "unknown"
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
    proposed_take_profit: float | None = None
    spread_bps: float | None = None
    orderbook_imbalance: float | None = None
    intraday_volatility_percent: float | None = None
    volatility_regime: VolatilityRegime = "unknown"
    market_move_percent: float | None = None
    market_regime: MarketRegime = "unknown"
    news_count_24h: int | None = None
    latest_news_headline: str | None = None
    news_sentiment_hint: NewsSentimentHint = "unknown"
    trigger_evidence: list[str]
    confidence_hint: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AIScore(BaseModel):
    """AI enrichment that stays advisory rather than authoritative."""

    model_name: str
    score: float = Field(ge=0, le=1)
    summary: str
    concerns: list[str]
    # Tier label for downstream grouping (recap, dashboard provider posture)
    # without parsing model_name strings. Defaults to "local" so the
    # deterministic fallback path needs no touch.
    score_provenance: ScoreProvenance = "local"
    # Raw heuristic score before the fallback cap, set on local-tier scores.
    # Lets the dashboard show when the 0.88 cap is binding vs. background.
    raw_score: float | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScoredTradeCandidate(BaseModel):
    """Trade candidate after AI enrichment."""

    candidate: TradeCandidate
    ai_score: AIScore


class PortfolioState(BaseModel):
    """Current portfolio state needed by the risk gate."""

    open_positions: int = 0
    day_trades_5_business_days: int = 0
    realized_pnl_today: float = 0
    buying_power: float = 10
    portfolio_value: float = 10
    trading_mode: TradingMode = "paper"


class RiskLimits(BaseModel):
    """Operator-defined guardrails for autonomous execution."""

    allowed_symbols: list[str]
    target_position_percent: float
    max_open_positions: int
    max_day_trades_5_business_days: int = 3
    max_daily_loss: float
    max_entry_spread_bps: float = 75.0
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
    daytrade_count: int | None = None


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


class DayTradeRecord(BaseModel):
    """One locally detected same-day round trip."""

    symbol: str
    trade_date: str
    opened_at: datetime
    closed_at: datetime


class DayTradeGuardResult(BaseModel):
    """PDT-aware guard result for an attempted sell."""

    symbol: str
    would_be_day_trade: bool
    allowed: bool
    day_trades_5_business_days: int
    local_day_trades_5_business_days: int = 0
    broker_day_trades_5_business_days: int | None = None
    count_source: str = "local"
    max_day_trades_5_business_days: int
    records: list[DayTradeRecord]
    reason: str


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
    broker_protection_supported: bool = False
    protection_action: Literal["none", "app_managed", "broker_oco"] = "none"
    status: Literal["protected", "needs_review", "unprotected"]
    notes: list[str]


class ExitSignal(BaseModel):
    """Autopilot exit signal for one open position."""

    symbol: str
    reason: Literal["stop_loss", "small_win", "take_profit"]
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


class ProfitLockEntry(BaseModel):
    """A position whose take-profit signal was held by the PDT cap."""

    symbol: str
    locked_at: datetime | None = None
    block_reason: str
    average_entry_price: float | None = None
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pl: float | None = None


class ProfitLockReport(BaseModel):
    """Operator-facing summary of profit-locked carries."""

    entries: list[ProfitLockEntry]
    notes: list[str]


class DefragmentationCandidate(BaseModel):
    """Stale tiny lot safe to liquidate without consuming a PDT slot."""

    symbol: str
    market_value: float
    unrealized_pl: float
    last_buy_filled_at: datetime
    age_minutes: int


class DefragmentationReport(BaseModel):
    """Pre-open defragmentation worklist for buying-power reclaim."""

    candidates: list[DefragmentationCandidate]
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


class ProviderUsageSummary(BaseModel):
    """Daily scoring provider usage summary."""

    provider: str
    count: int


class StrategyUsageSummary(BaseModel):
    """Daily strategy lane usage summary."""

    strategy_id: str
    candidates: int
    approved: int
    submitted: int


class DailyTradeRecap(BaseModel):
    """Local daily recap for compounding review."""

    date: str
    starting_portfolio_value: float | None = None
    ending_portfolio_value: float | None = None
    portfolio_delta: float | None = None
    pipeline_runs: int = 0
    candidate_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    pdt_rejected_count: int = 0
    spread_rejected_count: int = 0
    submitted_orders: int = 0
    provider_usage: list[ProviderUsageSummary]
    strategy_usage: list[StrategyUsageSummary]
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


# ---------------------------------------------------------------------------
# Options primitives
# ---------------------------------------------------------------------------
#
# These models are deliberately separate from ``TradeCandidate`` /
# ``ExecutionIntent`` so the equity pipeline stays untouched. The options
# pipeline will reuse the same audit, kill-switch, and PDT plumbing once a
# broker adapter populates option chains and submits option orders.


class OptionContract(BaseModel):
    """One listed option contract from the chain.

    ``occ_symbol`` follows the OCC standard format (e.g.
    ``AAPL250620C00230000``) and is what Alpaca submits orders against.
    Greeks are optional because the broker may not always provide them.
    """

    occ_symbol: str
    underlying: str
    expiration: str  # ISO date "YYYY-MM-DD"
    strike: float
    contract_type: OptionContractType
    multiplier: int = 100
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    delta: float | None = None
    implied_volatility: float | None = None


class OptionsChainSnapshot(BaseModel):
    """Filtered option chain for a single underlying at a moment in time."""

    underlying: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    underlying_price: float | None = None
    contracts: list[OptionContract]


class OptionsTradeCandidate(BaseModel):
    """Strategy-created options candidate before risk review.

    For Level 1 strategies (``covered_call_v1``, ``cash_secured_put_v1``)
    the action is always ``sell_to_open``. ``expected_credit`` is the
    premium received per contract (mid-price × multiplier × contracts).
    ``collateral_required`` is the dollar collateral the broker will
    encumber:

      - covered call: ``contracts × 100 × underlying_price`` worth of
        already-held shares (cash impact = $0; positions are encumbered).
      - cash-secured put: ``contracts × 100 × strike`` cash held aside.
    """

    candidate_id: str = Field(default_factory=lambda: new_id("optcand"))
    correlation_id: str
    strategy_id: OptionsStrategyId
    contract: OptionContract
    action: OptionAction
    contracts: int = Field(ge=1)
    expected_credit: float | None = None
    expected_debit: float | None = None
    collateral_required: float
    underlying_position_quantity: float = 0.0
    trigger_evidence: list[str]
    confidence_hint: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OptionsRiskDecision(BaseModel):
    """Risk-engine output for an options candidate."""

    decision_id: str = Field(default_factory=lambda: new_id("optrisk"))
    state: RiskState
    candidate_id: str
    approved_contracts: int = 0
    approved_collateral: float = 0.0
    reasons: list[str]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OptionsExecutionIntent(BaseModel):
    """Final broker-facing options instruction after risk approval."""

    intent_id: str = Field(default_factory=lambda: new_id("optintent"))
    candidate_id: str
    occ_symbol: str
    underlying: str
    action: OptionAction
    contracts: int
    order_type: Literal["market", "limit"] = "limit"
    limit_price: float | None = None
    time_in_force: Literal["day", "gtc"] = "day"
    mode: TradingMode
    client_order_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OptionsRiskLimits(BaseModel):
    """Operator-defined options guardrails (level, eligibility, gates)."""

    enabled: bool = False
    max_level: OptionsTradingLevel = 1
    allowed_underlyings: list[str]
    min_open_interest: int = 500
    max_bid_ask_spread_percent: float = 0.05
    target_dte_min: int = 30
    target_dte_max: int = 45
    min_premium_to_collateral_ratio: float = 0.005
    max_open_contracts: int = 2
    cash_reserve_percent_of_portfolio: float = 0.10
