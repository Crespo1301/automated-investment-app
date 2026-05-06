"""Local worker cycle for developing the autonomous trading loop."""

from datetime import UTC, datetime

from app.core.config import configured_symbols, settings
from app.domain.trading import (
    MarketEvent,
    PipelineRunResult,
    PortfolioState,
    RiskDecision,
    RiskLimits,
)
from app.services.ai_scorer import TradeScorer
from app.services.audit_store import get_safety_state, record_pipeline_run
from app.services.broker_adapter import (
    AlpacaBroker,
    get_active_alpaca_broker,
    get_alpaca_paper_broker,
    get_broker,
)
from app.services.risk_engine import RiskEngine
from app.services.strategy_engine import MicroBreakoutStrategy


def get_risk_limits() -> RiskLimits:
    """Build risk limits from the current environment configuration."""

    return RiskLimits(
        allowed_symbols=configured_symbols(),
        max_notional_per_trade=settings.max_notional_per_trade,
        max_open_positions=settings.max_open_positions,
        max_live_trades_per_day=settings.max_live_trades_per_day,
        max_daily_loss=settings.max_daily_loss,
        allow_live_trading=settings.allow_live_trading,
        allow_outside_market_hours=settings.allow_outside_market_hours,
        duplicate_order_lookback_minutes=settings.duplicate_order_lookback_minutes,
    )


def get_default_portfolio_state() -> PortfolioState:
    """Create the starter portfolio state for a $10 account."""

    return PortfolioState(
        open_positions=0,
        live_trades_today=0,
        realized_pnl_today=0,
        buying_power=10,
        trading_mode="live" if settings.trading_mode == "live" else "paper",
    )


def get_portfolio_state_from_broker(broker: AlpacaBroker) -> PortfolioState:
    """Build the risk-gate portfolio state from the active broker snapshot."""

    account = broker.get_account_status()
    positions = broker.list_positions()
    recent_orders = broker.list_recent_orders(limit=50)
    today = datetime.now(UTC).date()
    trades_today = 0

    for order in recent_orders:
        submitted_at = order.submitted_at
        if submitted_at is None:
            continue

        if submitted_at.astimezone(UTC).date() != today:
            continue

        if order.status.lower() in {
            "new",
            "accepted",
            "pending_new",
            "partially_filled",
            "filled",
        }:
            trades_today += 1

    return PortfolioState(
        open_positions=len(positions),
        live_trades_today=trades_today,
        realized_pnl_today=0,
        buying_power=account.buying_power,
        trading_mode=account.account_mode,
    )


def run_single_cycle(
    event: MarketEvent | None = None,
    use_alpaca_paper: bool = False,
) -> PipelineRunResult:
    """Run one end-to-end candidate evaluation cycle.

    This is the safe local development loop: market event, deterministic
    strategy, advisory AI score, hard risk review, and paper broker receipt.
    """

    event = event or MarketEvent(
        source="local-demo",
        symbol="SPY",
        event_kind="bar",
        price=105.0,
        previous_close=104.0,
        volume=350_000,
    )

    limits = get_risk_limits()
    portfolio_state = get_default_portfolio_state()
    strategy = MicroBreakoutStrategy(
        allowed_symbols=limits.allowed_symbols,
        proposed_notional=limits.max_notional_per_trade,
    )

    candidate = strategy.evaluate(event)
    if candidate is None:
        return PipelineRunResult(
            event=event,
            candidate=None,
            scored_candidate=None,
            risk_decision=None,
            execution_intent=None,
            broker_receipt=None,
        )

    scored_candidate = TradeScorer().score(candidate)
    broker = None
    if use_alpaca_paper:
        broker = get_alpaca_paper_broker()
        portfolio_state = get_portfolio_state_from_broker(broker)
    elif settings.trading_mode == "live" and settings.allow_live_trading:
        broker = get_active_alpaca_broker()
        portfolio_state = get_portfolio_state_from_broker(broker)

    risk_decision, execution_intent = RiskEngine(limits).evaluate(
        scored_candidate,
        portfolio_state,
    )
    safety_state = get_safety_state()
    if execution_intent is not None and safety_state.kill_switch_enabled:
        risk_decision = RiskDecision(
            state="rejected",
            candidate_id=candidate.candidate_id,
            reasons=[
                "Operator kill switch is enabled.",
                safety_state.reason or "No kill switch reason was provided.",
            ],
        )
        execution_intent = None

    if execution_intent is not None and broker is not None and settings.trading_mode == "live":
        clock = broker.get_market_clock()
        if not clock.is_open and not settings.allow_outside_market_hours:
            risk_decision = RiskDecision(
                state="rejected",
                candidate_id=candidate.candidate_id,
                reasons=[
                    "Market is closed and outside-hours order queueing is disabled.",
                    f"Next open: {clock.next_open.isoformat() if clock.next_open else 'unknown'}.",
                ],
            )
            execution_intent = None

    if execution_intent is not None and broker is not None and settings.trading_mode == "live":
        duplicate_order = broker.has_open_duplicate_order(
            symbol=execution_intent.symbol,
            side=execution_intent.side,
            notional=execution_intent.approved_notional,
            strategy_prefix=f"{candidate.strategy_id}-",
        )
        if duplicate_order is not None:
            risk_decision = RiskDecision(
                state="rejected",
                candidate_id=candidate.candidate_id,
                reasons=[
                    "A matching open broker order already exists.",
                    f"Duplicate order id: {duplicate_order.broker_order_id}.",
                    f"Duplicate status: {duplicate_order.status}.",
                ],
            )
            execution_intent = None

    broker_receipt = None
    if execution_intent is not None:
        broker = broker or (get_alpaca_paper_broker() if use_alpaca_paper else get_broker())
        broker_receipt = broker.submit_order(execution_intent)
    result = PipelineRunResult(
        event=event,
        candidate=candidate,
        scored_candidate=scored_candidate,
        risk_decision=risk_decision,
        execution_intent=execution_intent,
        broker_receipt=broker_receipt,
    )
    record_pipeline_run(result)
    return result
