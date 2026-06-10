"""Local worker cycle for developing the autonomous trading loop."""

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

from app.core.config import (
    configured_high_vol_symbols,
    configured_pdt_capped_swing_strategies,
    configured_swing_safe_strategies,
    configured_symbols,
    settings,
)
from app.domain.trading import (
    MarketEvent,
    PipelineRunResult,
    PortfolioState,
    RiskDecision,
    RiskLimits,
    ScoredTradeCandidate,
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
from app.services.coid import coid_prefix_for
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
    fallback_event, lane_candidates = _select_lane_candidates(
        events,
        strategy,
        blocked_symbols=blocked_entry_symbols,
    )
    if not lane_candidates:
        return PipelineRunResult(
            event=fallback_event,
            candidate=None,
            scored_candidate=None,
            risk_decision=None,
            execution_intent=None,
            broker_receipt=None,
        )

    # Score the strongest candidate from every lane and let the scorer pick
    # the winner. Selection used to be a raw confidence_hint max, which is
    # not comparable across lanes; scoring each lane's best makes evidence
    # quality, stop/reward, and market context the real tiebreaker. At most
    # one candidate per strategy lane is scored (<= 6 scoring calls/cycle).
    scorer = TradeScorer()
    scored_lane_results: list[
        tuple[MarketEvent, TradeCandidate, ScoredTradeCandidate]
    ] = []
    for lane_event, lane_candidate in lane_candidates:
        sized_candidate = _apply_regime_sizing(
            _apply_symbol_volatility_sizing(lane_candidate)
        )
        scored_lane_results.append(
            (lane_event, sized_candidate, scorer.score(sized_candidate))
        )

    event, candidate, scored_candidate = max(
        scored_lane_results,
        key=lambda result: result[2].ai_score.score,
    )

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

    if execution_intent is not None and _pdt_traps_new_entry(
        portfolio_state.day_trades_5_business_days,
        limits.max_day_trades_5_business_days,
        candidate.strategy_id,
        candidate.symbol,
        candidate.spread_bps,
        scored_candidate.ai_score.score,
    ):
        risk_decision = RiskDecision(
            state="rejected",
            candidate_id=candidate.candidate_id,
            reasons=[
                "PDT count is at the rolling five-business-day cap; a same-day"
                " stop-loss could not be honored.",
                f"day_trades_5_business_days={portfolio_state.day_trades_5_business_days}"
                f"/{limits.max_day_trades_5_business_days};"
                f" strategy={candidate.strategy_id} and symbol={candidate.symbol} do not pass PDT slot allocation.",
            ],
        )
        execution_intent = None
    elif execution_intent is not None and _is_pdt_capped_swing_entry(
        portfolio_state.day_trades_5_business_days,
        limits.max_day_trades_5_business_days,
        candidate.strategy_id,
        candidate.symbol,
        candidate.spread_bps,
        scored_candidate.ai_score.score,
    ):
        multiplier = max(0.0, min(1.0, settings.pdt_capped_swing_position_size_multiplier))
        approved_notional = max(
            settings.minimum_order_notional,
            execution_intent.approved_notional * multiplier,
        )
        approved_notional = min(execution_intent.approved_notional, approved_notional)
        execution_intent = execution_intent.model_copy(
            update={"approved_notional": int(approved_notional * 100) / 100}
        )
        risk_decision = risk_decision.model_copy(
            update={
                "approved_notional": execution_intent.approved_notional,
                "reasons": [
                    *risk_decision.reasons,
                    (
                        "PDT-capped swing entry allowed: reduced size, low/medium-vol symbol, "
                        "tight spread, and strong score."
                    ),
                ],
            }
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
            strategy_prefix=coid_prefix_for(candidate.strategy_id),
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
        window = _cycle_symbols(limits.allowed_symbols)
        movers = _live_mover_symbols(broker)
        if movers:
            # Movers go first and are deduped against the rotating window so
            # they are scanned EVERY tick (not only when their bucket comes up),
            # while the total stays bounded by max_symbols_per_cycle.
            keep = max(0, settings.max_symbols_per_cycle - len(movers))
            symbols = list(dict.fromkeys(movers + window[:keep]))
        else:
            symbols = window
        return broker.list_watchlist_market_events(symbols)

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


def _live_mover_symbols(broker: AlpacaBroker | None) -> list[str]:
    """Return today's liquid top-gainers for the offense lane.

    Pulls Alpaca's live movers through the broker's read-only screener so the
    momentum lane can catch breakouts the static universe would miss. A screener
    failure must NEVER stall the autopilot cycle, so any error degrades to "no
    movers" and the cycle proceeds on the static rotating universe.
    """

    if broker is None or not settings.mover_scanner_enabled:
        return []
    try:
        movers = broker.list_intraday_movers(
            top=settings.mover_scanner_top,
            min_price=settings.mover_scanner_min_price,
            min_change_percent=settings.mover_scanner_min_change_percent,
            max_change_percent=settings.mover_scanner_max_change_percent,
        )
    except Exception as exc:  # screener hiccup must not break trading
        logger.warning("mover scanner unavailable this cycle: %s", exc)
        return []
    return movers[: settings.mover_scanner_max_symbols]


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


def _event_move_percent(event: MarketEvent) -> float:
    """Absolute intraday move (%) of an event vs its previous close.

    Returns a large sentinel when move data is missing so the momentum gate
    never blocks an entry merely because price/previous-close is unavailable.
    """

    previous_close = getattr(event, "previous_close", None)
    price = getattr(event, "price", None)
    if not previous_close or price is None:
        return 999.0
    return abs((price / previous_close - 1.0) * 100.0)


def _select_lane_candidates(
    events: list[MarketEvent],
    strategy: AggressiveStrategyEngine,
    blocked_symbols: set[str] | None = None,
) -> tuple[MarketEvent, list[tuple[MarketEvent, TradeCandidate]]]:
    """Return the strongest candidate per strategy lane across the cycle's events.

    Returns ``(fallback_event, lane_candidates)``. ``fallback_event`` is only
    used to populate a no-candidate PipelineRunResult. ``lane_candidates``
    holds at most one ``(event, candidate)`` pair per ``strategy_id`` - the
    highest-confidence candidate that lane produced this cycle.

    Selecting per lane (rather than a single global ``max`` over raw
    ``confidence_hint``) is what lets every lane compete downstream on the
    scorer's full judgment. ``confidence_hint`` is not calibrated across
    lanes - each lane has a different floor and ceiling - so a raw cross-lane
    max structurally crowned opening_range_breakout_v1 and made the autopilot
    a one-lane bot.
    """

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
        return fallback_event, []

    min_move = max(0.0, settings.min_entry_move_percent)
    best_by_lane: dict[str, tuple[MarketEvent, TradeCandidate]] = {}
    for market_event in events:
        # Momentum gate: skip flat, drifting names so the autopilot stops
        # opening mechanical positions that just bleed and crowd out movers.
        # Real movers clear the floor; ~0% drift cannot. Founded buy-market
        # trades use a separate path and are not gated here.
        if min_move > 0 and _event_move_percent(market_event) < min_move:
            continue
        for candidate in strategy.evaluate_all(market_event):
            if candidate.symbol.upper() in blocked_symbols:
                continue
            existing = best_by_lane.get(candidate.strategy_id)
            if existing is None or candidate.confidence_hint > existing[1].confidence_hint:
                best_by_lane[candidate.strategy_id] = (market_event, candidate)

    return events[0], list(best_by_lane.values())


def _blocked_entry_symbols(broker: AlpacaBroker | None) -> set[str]:
    """Return symbols that should not receive another autonomous buy right now."""

    if broker is None or settings.trading_mode != "live":
        return set()

    blocked = {position.symbol.upper() for position in broker.list_positions()}
    now = datetime.now(UTC)
    buy_cutoff = now - _duplicate_lookback_delta()
    sell_cutoff = now - timedelta(
        minutes=max(0, settings.reentry_cooldown_minutes_after_sell)
    )
    for order in broker.list_recent_orders(limit=50):
        submitted_at = order.submitted_at
        if submitted_at is None:
            continue
        submitted_at = submitted_at.astimezone(UTC)

        side = order.side.split(".")[-1].lower()
        status = order.status.split(".")[-1].lower()
        if (
            side == "buy"
            and status in _entry_blocking_order_statuses()
            and submitted_at >= buy_cutoff
        ):
            blocked.add(order.symbol.upper())
        elif side == "sell" and submitted_at >= sell_cutoff:
            # Rotation cooldown: a name we just exited (stop, take-profit, or
            # manual rotation) must not be auto-rebought for a window, so freed
            # slots/cash stay open for fresh movers instead of refilling the
            # same drift name.
            blocked.add(order.symbol.upper())

    return blocked


def _pdt_traps_new_entry(
    day_trade_count: int,
    max_day_trades: int,
    strategy_id: str,
    symbol: str,
    spread_bps: float | None = None,
    score: float | None = None,
) -> bool:
    if max_day_trades <= 0:
        return False
    slots_remaining = max(0, max_day_trades - day_trade_count)
    normalized_symbol = symbol.upper()

    if (
        normalized_symbol in configured_high_vol_symbols()
        and slots_remaining < settings.high_vol_min_pdt_slots_for_entry
    ):
        return True

    if not settings.block_entries_when_pdt_maxed:
        return False
    if slots_remaining > 0:
        return False
    if _is_pdt_capped_swing_entry(
        day_trade_count,
        max_day_trades,
        strategy_id,
        symbol,
        spread_bps,
        score,
    ):
        return False
    return strategy_id not in configured_swing_safe_strategies()


def _is_pdt_capped_swing_entry(
    day_trade_count: int,
    max_day_trades: int,
    strategy_id: str,
    symbol: str,
    spread_bps: float | None,
    score: float | None,
) -> bool:
    if max_day_trades <= 0 or day_trade_count < max_day_trades:
        return False
    if strategy_id not in configured_pdt_capped_swing_strategies():
        return False
    if symbol.upper() in configured_high_vol_symbols():
        return False
    if spread_bps is None or spread_bps > settings.pdt_capped_swing_max_spread_bps:
        return False
    if score is None or score < settings.pdt_capped_swing_min_score:
        return False
    return True


def _apply_symbol_volatility_sizing(candidate: TradeCandidate) -> TradeCandidate:
    if candidate.symbol.upper() not in configured_high_vol_symbols():
        return candidate

    multiplier = max(0.0, min(1.0, settings.high_vol_position_size_multiplier))
    adjusted_notional = candidate.proposed_notional * multiplier
    if candidate.proposed_notional >= settings.minimum_order_notional:
        adjusted_notional = max(settings.minimum_order_notional, adjusted_notional)

    if adjusted_notional >= candidate.proposed_notional:
        return candidate

    return candidate.model_copy(
        update={
            "proposed_notional": round(adjusted_notional, 2),
            "trigger_evidence": [
                *candidate.trigger_evidence,
                (
                    f"{candidate.symbol} is high-volatility tier; proposed notional reduced "
                    f"by {multiplier:.0%}."
                ),
            ],
        }
    )


def _apply_regime_sizing(candidate: TradeCandidate) -> TradeCandidate:
    """Trim entry notional when the broader market or volatility regime is hostile.

    Stacks multiplicatively with ``_apply_symbol_volatility_sizing``. Both
    clamp to the fractional minimum, so at very small NAV (entries already
    near $1) this is a no-op and the scorer's regime dampener carries the
    defense; it bites once the account is large enough for sizing to matter.
    """

    multiplier = 1.0
    reasons: list[str] = []
    if candidate.market_regime == "risk_off":
        multiplier *= max(0.0, min(1.0, settings.risk_off_position_size_multiplier))
        reasons.append("risk-off market regime")
    if candidate.volatility_regime == "extreme":
        multiplier *= max(0.0, min(1.0, settings.extreme_vol_position_size_multiplier))
        reasons.append("extreme volatility regime")

    if not reasons or multiplier >= 1.0:
        return candidate

    adjusted_notional = candidate.proposed_notional * multiplier
    if candidate.proposed_notional >= settings.minimum_order_notional:
        adjusted_notional = max(settings.minimum_order_notional, adjusted_notional)
    if adjusted_notional >= candidate.proposed_notional:
        return candidate

    return candidate.model_copy(
        update={
            "proposed_notional": round(adjusted_notional, 2),
            "trigger_evidence": [
                *candidate.trigger_evidence,
                (
                    f"Entry notional reduced {1 - multiplier:.0%} for "
                    f"{' and '.join(reasons)}."
                ),
            ],
        }
    )


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
