"""Local worker cycle for developing the autonomous trading loop."""

from datetime import UTC, datetime

from app.core.config import configured_symbols, settings
from app.domain.trading import (
    MarketEvent,
    PipelineRunResult,
    PortfolioState,
    RiskDecision,
    RiskLimits,
    TradeCandidate,
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
from app.services.strategy_engine import AggressiveStrategyEngine


def get_risk_limits() -> RiskLimits:
    """Build risk limits from the current environment configuration."""

    return RiskLimits(
        allowed_symbols=configured_symbols(),
        target_position_percent=settings.position_size_percent,
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
        portfolio_value=10,
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
        portfolio_value=account.portfolio_value,
        trading_mode=account.account_mode,
    )


def run_single_cycle(
    event: MarketEvent | None = None,
    use_alpaca_paper: bool = False,
    queue_for_open: bool = False,
) -> PipelineRunResult:
    """Run one end-to-end candidate evaluation cycle.

    This is the safe local development loop: market event, deterministic
    strategy, advisory AI score, hard risk review, and paper broker receipt.
    """

    limits = get_risk_limits()
    portfolio_state = get_default_portfolio_state()
    broker = None
    if use_alpaca_paper:
        broker = get_alpaca_paper_broker()
        portfolio_state = get_portfolio_state_from_broker(broker)
    elif settings.trading_mode == "live" and settings.allow_live_trading:
        broker = get_active_alpaca_broker()
        portfolio_state = get_portfolio_state_from_broker(broker)

    target_notional = _calculate_target_notional(
        portfolio_value=portfolio_state.portfolio_value,
        buying_power=portfolio_state.buying_power,
        target_position_percent=limits.target_position_percent,
    )
    strategy = AggressiveStrategyEngine(
        allowed_symbols=limits.allowed_symbols,
        proposed_notional=target_notional,
        breakout_threshold=settings.strategy_breakout_threshold,
        stop_loss_percent=settings.strategy_stop_loss_percent,
        min_volume=settings.strategy_min_volume,
    )

    events = _get_cycle_events(event=event, broker=broker, limits=limits)
    selected_event, candidate = _select_best_candidate(events, strategy)
    if candidate is None:
        return PipelineRunResult(
            event=selected_event,
            candidate=None,
            scored_candidate=None,
            risk_decision=None,
            execution_intent=None,
            broker_receipt=None,
        )

    event = selected_event
    scored_candidate = TradeScorer().score(candidate)

    risk_decision, execution_intent = RiskEngine(limits).evaluate(
        scored_candidate,
        portfolio_state,
    )
    if queue_for_open and (
        settings.trading_mode != "live" or not settings.allow_live_trading
    ):
        risk_decision = RiskDecision(
            state="rejected",
            candidate_id=candidate.candidate_id,
            reasons=[
                "Queue-for-open requires live trading mode and explicit live permission.",
            ],
        )
        execution_intent = None

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

    if (
        execution_intent is not None
        and settings.trading_mode == "live"
        and event.source == "local-demo"
        and not settings.allow_demo_live_entries
    ):
        risk_decision = RiskDecision(
            state="rejected",
            candidate_id=candidate.candidate_id,
            reasons=[
                "Live entries from the synthetic local-demo market event are disabled.",
                "Wire real Alpaca market data before enabling autonomous entries.",
            ],
        )
        execution_intent = None

    if execution_intent is not None and broker is not None and settings.trading_mode == "live":
        clock = broker.get_market_clock()
        if queue_for_open:
            if clock.is_open:
                risk_decision = RiskDecision(
                    state="rejected",
                    candidate_id=candidate.candidate_id,
                    reasons=[
                        "Regular market is already open. Use the normal live-cycle action instead.",
                    ],
                )
                execution_intent = None
            else:
                execution_intent = execution_intent.model_copy(
                    update={"session_policy": "regular_open_queue"}
                )
        elif not clock.is_open and not settings.allow_outside_market_hours:
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


def run_queue_for_open_cycle(event: MarketEvent | None = None) -> PipelineRunResult:
    """Run one guarded cycle that can queue a regular-session order for open."""

    return run_single_cycle(event=event, queue_for_open=True)


def _get_cycle_events(
    event: MarketEvent | None,
    broker: AlpacaBroker | None,
    limits: RiskLimits,
) -> list[MarketEvent]:
    """Return the market events that should be evaluated for this cycle."""

    if event is not None:
        return [event]

    if broker is not None and settings.trading_mode == "live" and settings.allow_live_trading:
        return broker.list_watchlist_market_events(limits.allowed_symbols)

    return [
        MarketEvent(
            source="local-demo",
            symbol="SPY",
            event_kind="bar",
            price=105.0,
            previous_close=104.0,
            volume=350_000,
        )
    ]


def _select_best_candidate(
    events: list[MarketEvent],
    strategy: AggressiveStrategyEngine,
) -> tuple[MarketEvent, TradeCandidate | None]:
    """Choose the strongest candidate from the current cycle's events."""

    if not events:
        fallback_event = MarketEvent(
            source="local-demo",
            symbol="SPY",
            event_kind="bar",
            price=105.0,
            previous_close=104.0,
            volume=350_000,
        )
        return fallback_event, None

    selected_event = events[0]
    selected_candidate = None
    for market_event in events:
        for candidate in strategy.evaluate_all(market_event):
            if (
                selected_candidate is None
                or candidate.confidence_hint > selected_candidate.confidence_hint
            ):
                selected_event = market_event
                selected_candidate = candidate

    return selected_event, selected_candidate


def _calculate_target_notional(
    portfolio_value: float,
    buying_power: float,
    target_position_percent: float,
) -> float:
    """Size each new entry as a percent of the current portfolio."""

    desired_notional = max(1.0, portfolio_value * target_position_percent)
    return round(min(desired_notional, buying_power), 2)
