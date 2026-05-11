"""Local worker cycle for developing the autonomous trading loop."""

from datetime import UTC, datetime, timedelta

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
        max_day_trades_5_business_days=settings.max_day_trades_5_business_days,
        max_daily_loss=settings.max_daily_loss,
        max_entry_spread_bps=settings.max_entry_spread_bps,
        allow_live_trading=settings.allow_live_trading,
        allow_outside_market_hours=settings.allow_outside_market_hours,
        duplicate_order_lookback_minutes=settings.duplicate_order_lookback_minutes,
    )


def get_default_portfolio_state() -> PortfolioState:
    """Create the starter portfolio state for a $10 account."""

    return PortfolioState(
        open_positions=0,
        realized_pnl_today=0,
        buying_power=10,
        portfolio_value=10,
        trading_mode="live" if settings.trading_mode == "live" else "paper",
    )


def get_portfolio_state_from_broker(broker: AlpacaBroker) -> PortfolioState:
    """Build the risk-gate portfolio state from the active broker snapshot."""

    account = broker.get_account_status()
    positions = broker.list_positions()
    return PortfolioState(
        open_positions=len(positions),
        day_trades_5_business_days=_broker_day_trade_count(broker),
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
    if target_notional < 1:
        return PipelineRunResult(
            event=_portfolio_minimum_event(),
            candidate=None,
            scored_candidate=None,
            risk_decision=None,
            execution_intent=None,
            broker_receipt=None,
        )

    # High-upside lane uses its own smaller envelope so a losing hunter
    # trade is a smaller drawdown. ``_calculate_target_notional`` applies
    # the same buying-power and cash-reserve clamps, so if 15% of the
    # portfolio falls below $1 the lane will simply skip — that's the
    # honest behavior at very small accounts.
    high_upside_target_notional = _calculate_target_notional(
        portfolio_value=portfolio_state.portfolio_value,
        buying_power=portfolio_state.buying_power,
        target_position_percent=settings.high_upside_position_size_percent,
    )

    blocked_entry_symbols = _blocked_entry_symbols(broker)
    strategy = AggressiveStrategyEngine(
        allowed_symbols=limits.allowed_symbols,
        proposed_notional=target_notional,
        breakout_threshold=settings.strategy_breakout_threshold,
        stop_loss_percent=settings.strategy_stop_loss_percent,
        take_profit_percent=settings.autopilot_take_profit_percent / 100,
        high_upside_breakout_threshold=settings.high_upside_breakout_threshold,
        high_upside_min_recent_volume_ratio=settings.high_upside_min_recent_volume_ratio,
        high_upside_stop_loss_percent=settings.high_upside_stop_loss_percent,
        high_upside_take_profit_percent=settings.high_upside_take_profit_percent,
        high_upside_max_spread_bps=settings.high_upside_max_spread_bps,
        high_upside_require_known_market_regime=settings.high_upside_require_known_market_regime,
        high_upside_require_known_news_sentiment=settings.high_upside_require_known_news_sentiment,
        high_upside_proposed_notional=high_upside_target_notional,
        min_volume=settings.strategy_min_volume,
    )

    events = _get_cycle_events(event=event, broker=broker, limits=limits)
    selected_event, candidate = _select_best_candidate(
        events,
        strategy,
        blocked_symbols=blocked_entry_symbols,
    )
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
        return broker.list_watchlist_market_events(_cycle_symbols(limits.allowed_symbols))

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


def _cycle_symbols(symbols: list[str]) -> list[str]:
    """Rotate broad universes so each tick scans a bounded symbol window.

    Alpaca snapshots and news calls are relatively heavy when pointed at a very
    large universe. Rotation lets the bot cover many symbols across the day
    without trying to request the whole market every 30 seconds.

    Buckets advance every ``max(30, autopilot_interval_seconds)`` seconds. Each
    bucket also rotates the *order* within the window via a stride offset so
    symbols don't always get scanned in the same fixed sequence — the symbol
    at index 0 isn't permanently first inside its bucket. This reduces bias if
    a slow Alpaca response truncates the bucket mid-scan.
    """

    unique_symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols))
    limit = max(1, settings.max_symbols_per_cycle)
    if len(unique_symbols) <= limit:
        return unique_symbols

    bucket = int(datetime.now(UTC).timestamp() // max(30, settings.autopilot_interval_seconds))
    start = (bucket * limit) % len(unique_symbols)
    window = unique_symbols[start:] + unique_symbols[:start]
    selected = window[:limit]
    # Stride-shuffle the selected window so first-in-window position rotates
    # bucket-to-bucket even when the same symbols are being scanned.
    stride_offset = bucket % limit
    return selected[stride_offset:] + selected[:stride_offset]


def _select_best_candidate(
    events: list[MarketEvent],
    strategy: AggressiveStrategyEngine,
    blocked_symbols: set[str] | None = None,
) -> tuple[MarketEvent, TradeCandidate | None]:
    """Choose the strongest candidate from the current cycle's events."""

    blocked_symbols = blocked_symbols or set()
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
            if candidate.symbol.upper() in blocked_symbols:
                continue
            if (
                selected_candidate is None
                or candidate.confidence_hint > selected_candidate.confidence_hint
            ):
                selected_event = market_event
                selected_candidate = candidate

    return selected_event, selected_candidate


def _blocked_entry_symbols(broker: AlpacaBroker | None) -> set[str]:
    """Return symbols that should not receive another autonomous buy right now."""

    if broker is None or settings.trading_mode != "live":
        return set()

    blocked = {position.symbol.upper() for position in broker.list_positions()}
    cutoff = datetime.now(UTC) - _duplicate_lookback_delta()
    for order in broker.list_recent_orders(limit=50):
        submitted_at = order.submitted_at
        if submitted_at is not None and submitted_at.astimezone(UTC) < cutoff:
            continue

        side = order.side.split(".")[-1].lower()
        status = order.status.split(".")[-1].lower()
        if side == "buy" and status in _entry_blocking_order_statuses():
            blocked.add(order.symbol.upper())

    return blocked


def _broker_day_trade_count(broker: AlpacaBroker | None) -> int:
    if broker is None or not hasattr(broker, "get_day_trade_guard"):
        return 0

    return broker.get_day_trade_guard("SPY").day_trades_5_business_days


def _duplicate_lookback_delta():
    return timedelta(minutes=max(1, settings.duplicate_order_lookback_minutes))


def _entry_blocking_order_statuses() -> set[str]:
    return {
        "accepted",
        "new",
        "pending_new",
        "partially_filled",
        "pending_replace",
        "pending_cancel",
        "filled",
    }


def _portfolio_minimum_event() -> MarketEvent:
    return MarketEvent(
        source="portfolio-guard",
        symbol="CASH",
        event_kind="bar",
        price=1,
        previous_close=1,
        volume=0,
        session_state="regular",
    )


def _calculate_target_notional(
    portfolio_value: float,
    buying_power: float,
    target_position_percent: float,
    max_buying_power_utilization: float | None = None,
    cash_reserve_percent_of_portfolio: float | None = None,
) -> float:
    """Size each new entry as a percent of the current portfolio.

    Three constraints, narrowest wins:

    1. ``portfolio_value × target_position_percent`` — the per-trade target.
    2. ``(buying_power - portfolio_value × cash_reserve_percent_of_portfolio)
       × max_buying_power_utilization`` — keeps a portfolio-scaled cash
       buffer untouched and prevents any single trade from eating more than
       a fraction of remaining buying power. Defaults are read from
       settings when omitted, so legacy callers keep working unchanged.
    3. ``$1`` Alpaca fractional minimum — anything below skips the trade.
    """

    if max_buying_power_utilization is None:
        max_buying_power_utilization = settings.max_buying_power_utilization_per_trade
    if cash_reserve_percent_of_portfolio is None:
        cash_reserve_percent_of_portfolio = settings.cash_reserve_percent_of_portfolio

    desired_notional = max(1.0, portfolio_value * target_position_percent)
    reserve_dollars = max(0.0, portfolio_value * max(0.0, cash_reserve_percent_of_portfolio))
    spendable = max(0.0, buying_power - reserve_dollars)
    utilization = max(0.0, min(1.0, max_buying_power_utilization))
    per_trade_ceiling = spendable * utilization

    raw = min(desired_notional, per_trade_ceiling)
    # Fallback: if the per-trade utilization ceiling alone would push the
    # trade below Alpaca's $1 fractional minimum, but the full *spendable*
    # buying power (above the cash reserve) is still ≥ $1, size the trade
    # at the full spendable instead of skipping. Better to deploy one
    # remaining trade than hard-stop. The cash reserve is preserved
    # because we still subtract it before computing spendable.
    if raw < 1.0 and spendable >= 1.0:
        raw = min(desired_notional, spendable)

    # Floor to two decimals (do not round up) — the spending cap must never
    # be overshot by penny-rounding.
    return int(raw * 100) / 100
