from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.core.config import DEFAULT_ALLOWED_SYMBOLS, configured_symbols
from app.core.config import settings
from app.domain.trading import (
    AutopilotState,
    DayTradeGuardResult,
    MarketEvent,
    ScoredTradeCandidate,
    TradeCandidate,
)
from app.services.ai_scorer import TradeScorer
from app.services.audit_store import get_autopilot_state, get_daily_trade_recap, get_safety_state
from app.services.autopilot import enable_autopilot, run_autopilot_once
from app.services.broker_adapter import (
    AlpacaBroker,
    LocalPaperBroker,
    MissingBrokerCredentialsError,
    _detect_day_trade_records,
    missing_alpaca_credential_names,
)
from app.services.local_worker import (
    get_risk_limits,
    run_queue_for_open_cycle,
    run_single_cycle,
)
from app.services.exit_monitor import evaluate_exit_signals
from app.services.protection_plan import build_protection_plan
from app.services.readiness import get_morning_readiness
from app.services.strategy_engine import AggressiveStrategyEngine, MicroBreakoutStrategy
from app.domain.trading import BrokerOrderReceipt, BrokerOrderSummary, BrokerPositionSummary


@pytest.fixture(autouse=True)
def isolate_runtime_settings(tmp_path):
    original = {
        "trading_mode": settings.trading_mode,
        "allowed_symbols": settings.allowed_symbols,
        "position_size_percent": settings.position_size_percent,
        "anthropic_api_key": settings.anthropic_api_key,
        "anthropic_model": settings.anthropic_model,
        "allow_live_trading": settings.allow_live_trading,
        "allow_outside_market_hours": settings.allow_outside_market_hours,
        "autopilot_allow_entries": settings.autopilot_allow_entries,
        "autopilot_allow_exits": settings.autopilot_allow_exits,
        "autopilot_interval_seconds": settings.autopilot_interval_seconds,
        "autopilot_market_open_only": settings.autopilot_market_open_only,
        "autopilot_small_win_percent": settings.autopilot_small_win_percent,
        "autopilot_stop_loss_percent": settings.autopilot_stop_loss_percent,
        "autopilot_take_profit_percent": settings.autopilot_take_profit_percent,
        "minimum_order_notional": settings.minimum_order_notional,
        "max_day_trades_5_business_days": settings.max_day_trades_5_business_days,
        "strategy_breakout_threshold": settings.strategy_breakout_threshold,
        "strategy_min_volume": settings.strategy_min_volume,
        "strategy_stop_loss_percent": settings.strategy_stop_loss_percent,
        "high_upside_breakout_threshold": settings.high_upside_breakout_threshold,
        "high_upside_min_recent_volume_ratio": settings.high_upside_min_recent_volume_ratio,
        "high_upside_stop_loss_percent": settings.high_upside_stop_loss_percent,
        "high_upside_take_profit_percent": settings.high_upside_take_profit_percent,
        "high_upside_max_spread_bps": settings.high_upside_max_spread_bps,
        "high_upside_require_known_market_regime": settings.high_upside_require_known_market_regime,
        "high_upside_require_known_news_sentiment": settings.high_upside_require_known_news_sentiment,
        "max_buying_power_utilization_per_trade": settings.max_buying_power_utilization_per_trade,
        "cash_reserve_percent_of_portfolio": settings.cash_reserve_percent_of_portfolio,
        "ai_min_score": settings.ai_min_score,
        "max_entry_spread_bps": settings.max_entry_spread_bps,
        "max_symbols_per_cycle": settings.max_symbols_per_cycle,
        "allow_demo_live_entries": settings.allow_demo_live_entries,
        "alpaca_paper": settings.alpaca_paper,
        "duplicate_order_lookback_minutes": settings.duplicate_order_lookback_minutes,
        "openai_api_key": settings.openai_api_key,
        "runtime_data_dir": settings.runtime_data_dir,
    }
    settings.trading_mode = "paper"
    settings.allowed_symbols = DEFAULT_ALLOWED_SYMBOLS
    settings.position_size_percent = 0.25
    settings.anthropic_api_key = None
    settings.anthropic_model = "claude-opus-4-7"
    settings.allow_live_trading = False
    settings.allow_outside_market_hours = False
    settings.autopilot_allow_entries = False
    settings.autopilot_allow_exits = False
    settings.autopilot_interval_seconds = 30
    settings.autopilot_market_open_only = True
    settings.autopilot_small_win_percent = 1.5
    settings.autopilot_stop_loss_percent = 2
    settings.autopilot_take_profit_percent = 3
    settings.minimum_order_notional = 1
    settings.max_day_trades_5_business_days = 3
    settings.strategy_breakout_threshold = 0.0025
    settings.strategy_min_volume = 25_000
    settings.strategy_stop_loss_percent = 0.025
    settings.high_upside_breakout_threshold = 0.012
    settings.high_upside_min_recent_volume_ratio = 3
    settings.high_upside_stop_loss_percent = 0.04
    settings.high_upside_take_profit_percent = 0.12
    settings.high_upside_max_spread_bps = 50
    settings.high_upside_require_known_market_regime = True
    settings.high_upside_require_known_news_sentiment = False
    settings.max_buying_power_utilization_per_trade = 0.5
    settings.cash_reserve_percent_of_portfolio = 0.10
    settings.ai_min_score = 0.55
    settings.max_entry_spread_bps = 75
    settings.max_symbols_per_cycle = 80
    settings.allow_demo_live_entries = False
    settings.alpaca_paper = True
    settings.duplicate_order_lookback_minutes = 390
    settings.openai_api_key = None
    settings.runtime_data_dir = str(tmp_path)
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_confirmed_watchlist_defaults_are_loaded() -> None:
    symbols = configured_symbols()

    assert {"SPY", "QQQ", "SMH", "XLK", "NVDA", "AAPL", "MSFT", "AMZN"}.issubset(symbols)
    assert len(symbols) >= 30
    assert {"PLTR", "COIN", "HOOD", "MSTR", "ARKK", "XBI"}.issubset(symbols)


def test_starter_guardrails_match_confirmed_limits() -> None:
    settings.allow_live_trading = False
    limits = get_risk_limits()

    assert limits.target_position_percent == 0.25
    assert limits.max_open_positions == 6
    assert limits.max_day_trades_5_business_days == 3
    assert 2 <= limits.max_daily_loss <= 2.25
    assert limits.allow_live_trading is False


def test_aggressive_strategy_uses_range_and_volume_context() -> None:
    strategy = MicroBreakoutStrategy(
        allowed_symbols=["SPY"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
    )

    candidate = strategy.evaluate(
        MarketEvent(
            source="test",
            symbol="SPY",
            event_kind="bar",
            price=100.30,
            previous_close=100,
            volume=35_000,
            day_low=99.8,
            day_high=100.35,
            day_volume=40_000_000,
            previous_volume=60_000_000,
        )
    )

    assert candidate is not None
    assert candidate.confidence_hint > 0.70
    assert any("current day's range" in item for item in candidate.trigger_evidence)
    assert any("prior session" in item for item in candidate.trigger_evidence)


def test_aggressive_strategy_detects_opening_range_breakout() -> None:
    strategy = MicroBreakoutStrategy(
        allowed_symbols=["SPY"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
    )

    engine = AggressiveStrategyEngine(
        allowed_symbols=["SPY"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
    )
    event = MarketEvent(
        source="test",
        symbol="SPY",
        event_kind="bar",
        price=101,
        previous_close=100,
        volume=50_000,
        opening_range_high=100.5,
        opening_range_low=99.5,
        recent_volume=700_000,
        average_recent_volume=50_000,
    )

    candidates = engine.evaluate_all(event)

    assert strategy.evaluate(event) is not None
    assert any(candidate.strategy_id == "opening_range_breakout_v1" for candidate in candidates)


def test_aggressive_strategy_detects_vwap_reclaim() -> None:
    engine = AggressiveStrategyEngine(
        allowed_symbols=["QQQ"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
    )
    event = MarketEvent(
        source="test",
        symbol="QQQ",
        event_kind="bar",
        price=101,
        previous_close=100,
        previous_bar_close=99.95,
        volume=75_000,
        vwap=100.1,
        recent_volume=600_000,
        average_recent_volume=40_000,
    )

    candidates = engine.evaluate_all(event)

    assert any(candidate.strategy_id == "vwap_reclaim_v1" for candidate in candidates)


def test_target_notional_respects_buying_power_utilization_cap() -> None:
    """Per-trade sizing must never exceed the utilization ceiling, even if
    the percent-of-portfolio target is higher."""

    from app.services.local_worker import _calculate_target_notional

    target = _calculate_target_notional(
        portfolio_value=20,
        buying_power=4,
        target_position_percent=0.25,
        max_buying_power_utilization=0.5,
        cash_reserve_percent_of_portfolio=0,
    )
    # desired = 20 * 0.25 = 5.0; ceiling = 4 * 0.5 = 2.0; min = 2.0.
    assert target == 2.0


def test_target_notional_honors_portfolio_scaled_cash_reserve() -> None:
    """The cash reserve scales with portfolio value so the buffer doesn't
    cliff at Alpaca's $1 minimum as the portfolio grows."""

    from app.services.local_worker import _calculate_target_notional

    # Small account: 10% of $20 = $2 reserve.
    small = _calculate_target_notional(
        portfolio_value=20,
        buying_power=10,
        target_position_percent=0.25,
        max_buying_power_utilization=0.5,
        cash_reserve_percent_of_portfolio=0.10,
    )
    # spendable = 10 - 2 = 8; ceiling = 8 * 0.5 = 4.0; desired = 5.0; min = 4.0.
    assert small == 4.0

    # Larger account: same 10% reserve grows with portfolio.
    large = _calculate_target_notional(
        portfolio_value=1000,
        buying_power=500,
        target_position_percent=0.25,
        max_buying_power_utilization=0.5,
        cash_reserve_percent_of_portfolio=0.10,
    )
    # reserve = 1000 * 0.10 = 100; spendable = 500 - 100 = 400; ceiling = 200;
    # desired = 250; min = 200.
    assert large == 200.0


def test_target_notional_never_eats_all_remaining_buying_power() -> None:
    """Simulate consecutive entries on a small account. The cash reserve
    must be preserved every step. Sizing decays as buying power drops,
    falling back to ``spendable`` when the utilization ceiling alone would
    block a trade — but never touching the reserve."""

    from app.services.local_worker import _calculate_target_notional

    portfolio_value = 10.0
    buying_power = 10.0
    bp_before_each: list[float] = []
    sizes: list[float] = []
    for _ in range(6):
        bp_before_each.append(buying_power)
        size = _calculate_target_notional(
            portfolio_value=portfolio_value,
            buying_power=buying_power,
            target_position_percent=0.25,
            max_buying_power_utilization=0.5,
            cash_reserve_percent_of_portfolio=0.10,
        )
        sizes.append(size)
        buying_power -= size

    reserve = portfolio_value * 0.10
    for size, bp_at_entry in zip(sizes, bp_before_each):
        spendable_at_entry = max(0.0, bp_at_entry - reserve)
        # Hard invariant: no trade ever consumes more than spendable
        # buying power (i.e. the cash reserve is never touched).
        assert size <= spendable_at_entry + 1e-9, (size, spendable_at_entry)
    # Buying power never falls below the reserve.
    assert buying_power >= reserve - 1e-9
    # At least one late trade stepped down from the initial $2.50 target.
    assert min(sizes) < sizes[0]


def test_target_notional_falls_back_to_spendable_when_ceiling_blocks() -> None:
    """When the utilization ceiling alone would push the trade below $1
    but spendable buying power is still ≥ $1, the trade should size at the
    full spendable rather than being skipped. The cash reserve must remain
    intact."""

    from app.services.local_worker import _calculate_target_notional

    # portfolio=$10, BP=$2, reserve=$1, spendable=$1, ceiling=$0.50.
    # Without the fallback this would be $0.50 (skipped <$1).
    # With the fallback: trade sizes at $1 (the full spendable). Reserve
    # untouched.
    target = _calculate_target_notional(
        portfolio_value=10,
        buying_power=2,
        target_position_percent=0.25,
        max_buying_power_utilization=0.5,
        cash_reserve_percent_of_portfolio=0.10,
    )
    assert target == 1.0


def test_target_notional_skips_when_spendable_below_one_dollar() -> None:
    """If spendable buying power is itself below the $1 minimum, the trade
    is properly skipped — no fallback can save it."""

    from app.services.local_worker import _calculate_target_notional

    # portfolio=$10, BP=$1.50, reserve=$1, spendable=$0.50.
    target = _calculate_target_notional(
        portfolio_value=10,
        buying_power=1.5,
        target_position_percent=0.25,
        max_buying_power_utilization=0.5,
        cash_reserve_percent_of_portfolio=0.10,
    )
    assert target < 1.0


def _high_upside_engine() -> AggressiveStrategyEngine:
    return AggressiveStrategyEngine(
        allowed_symbols=["PLTR"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
        high_upside_breakout_threshold=0.012,
        high_upside_min_recent_volume_ratio=3,
        high_upside_stop_loss_percent=0.04,
        high_upside_take_profit_percent=0.12,
        high_upside_max_spread_bps=50,
        high_upside_require_known_market_regime=True,
        high_upside_require_known_news_sentiment=False,
    )


def _high_upside_event(**overrides):
    base = dict(
        source="test",
        symbol="PLTR",
        event_kind="bar",
        price=25.75,
        previous_close=25,
        volume=150_000,
        day_low=24.9,
        day_high=25.8,
        recent_volume=120_000,
        average_recent_volume=30_000,  # ratio = 4x with the corrected math
        spread_bps=8,
        market_regime="risk_on",
        news_sentiment_hint="positive",
    )
    base.update(overrides)
    return MarketEvent(**base)


def _has_high_upside(candidates) -> bool:
    return any(c.strategy_id == "high_upside_momentum_v1" for c in candidates)


def test_high_upside_blocks_when_market_regime_risk_off() -> None:
    engine = _high_upside_engine()
    event = _high_upside_event(market_regime="risk_off")
    assert not _has_high_upside(engine.evaluate_all(event))


def test_high_upside_blocks_when_market_regime_unknown_by_default() -> None:
    engine = _high_upside_engine()
    event = _high_upside_event(market_regime="unknown")
    assert not _has_high_upside(engine.evaluate_all(event))


def test_high_upside_blocks_when_news_sentiment_negative() -> None:
    engine = _high_upside_engine()
    event = _high_upside_event(news_sentiment_hint="negative")
    assert not _has_high_upside(engine.evaluate_all(event))


def test_high_upside_blocks_when_spread_above_configured_limit() -> None:
    engine = _high_upside_engine()
    event = _high_upside_event(spread_bps=51)
    assert not _has_high_upside(engine.evaluate_all(event))


def test_high_upside_volume_threshold_uses_corrected_ratio() -> None:
    """Corrected ``_recent_volume_ratio`` should be ``recent / average``.

    A recent_volume of 4x average must pass a 3x threshold; without the bug
    fix this would have required 30x.
    """

    engine = _high_upside_engine()
    event = _high_upside_event(recent_volume=120_000, average_recent_volume=30_000)
    assert _has_high_upside(engine.evaluate_all(event))


def test_high_upside_confidence_no_longer_pegs_near_one() -> None:
    """At-threshold setups should score in the 0.55–0.85 band, not 0.97+."""

    engine = _high_upside_engine()
    event = _high_upside_event(
        price=25.30,  # 1.2% move = exactly the threshold
        recent_volume=90_000,
        average_recent_volume=30_000,  # 3x = threshold
    )
    candidate = next(
        c for c in engine.evaluate_all(event) if c.strategy_id == "high_upside_momentum_v1"
    )
    assert 0.50 <= candidate.confidence_hint <= 0.85


def test_aggressive_strategy_detects_high_upside_momentum() -> None:
    engine = AggressiveStrategyEngine(
        allowed_symbols=["PLTR"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
        high_upside_breakout_threshold=0.012,
        high_upside_min_recent_volume_ratio=3,
        high_upside_stop_loss_percent=0.04,
        high_upside_take_profit_percent=0.12,
    )
    event = MarketEvent(
        source="test",
        symbol="PLTR",
        event_kind="bar",
        price=25.75,
        previous_close=25,
        volume=150_000,
        day_low=24.9,
        day_high=25.8,
        recent_volume=1_200_000,
        average_recent_volume=30_000,
        spread_bps=8,
        market_regime="risk_on",
        news_sentiment_hint="positive",
    )

    candidates = engine.evaluate_all(event)
    candidate = next(
        item for item in candidates if item.strategy_id == "high_upside_momentum_v1"
    )

    assert candidate.confidence_hint > 0.80
    assert candidate.proposed_stop == 24.72
    assert candidate.proposed_take_profit == 28.84


def test_local_worker_approves_demo_candidate_in_paper_mode() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False
    result = run_single_cycle()

    assert result.candidate is not None
    assert result.candidate.symbol == "SPY"
    assert result.candidate.proposed_notional == 2.5
    assert result.risk_decision is not None
    assert result.risk_decision.state == "approved"
    assert result.execution_intent is not None
    assert result.execution_intent.mode == "paper"
    assert result.execution_intent.approved_notional == 2.5
    assert result.broker_receipt is not None
    assert result.broker_receipt.status == "accepted_local_paper"


def test_local_worker_defaults_to_no_real_broker_submission() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False
    result = run_single_cycle()

    assert result.broker_receipt is not None
    assert result.broker_receipt.broker_order_id.startswith("local_order_")


def test_daily_recap_counts_strategy_and_provider_usage() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False

    run_single_cycle()
    recap = get_daily_trade_recap()

    assert recap.pipeline_runs == 1
    assert recap.candidate_count == 1
    assert recap.approved_count == 1
    assert recap.submitted_orders == 1
    assert any(provider.provider == "local" for provider in recap.provider_usage)
    assert any(strategy.strategy_id == "micro_breakout_v1" for strategy in recap.strategy_usage)


def test_local_broker_account_status_is_redacted_demo_shape() -> None:
    status = LocalPaperBroker().get_account_status()

    assert status.broker == "local-paper"
    assert status.account_mode == "paper"
    assert status.account_id_hint == "local"
    assert status.buying_power == 10


def test_missing_alpaca_credentials_reports_env_names() -> None:
    error = MissingBrokerCredentialsError(
        ["INVESTMENT_APP_ALPACA_API_KEY", "INVESTMENT_APP_ALPACA_SECRET_KEY"]
    )

    assert "INVESTMENT_APP_ALPACA_API_KEY" in error.missing_names
    assert "INVESTMENT_APP_ALPACA_SECRET_KEY" in error.missing_names


def test_day_trade_detection_respects_order_sequence() -> None:
    market_date = datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).date()
    eastern = ZoneInfo("America/New_York")
    today = datetime.combine(market_date, time(10, 0), tzinfo=eastern).astimezone(UTC)
    orders = [
        BrokerOrderSummary(
            broker_order_id="nvda_sell",
            symbol="NVDA",
            side="OrderSide.SELL",
            order_type="OrderType.MARKET",
            status="OrderStatus.FILLED",
            filled_quantity=0.01,
            filled_at=today,
        ),
        BrokerOrderSummary(
            broker_order_id="nvda_buy",
            symbol="NVDA",
            side="OrderSide.BUY",
            order_type="OrderType.MARKET",
            status="OrderStatus.FILLED",
            filled_quantity=0.01,
            filled_at=today.replace(hour=16),
        ),
        BrokerOrderSummary(
            broker_order_id="spy_buy",
            symbol="SPY",
            side="OrderSide.BUY",
            order_type="OrderType.MARKET",
            status="OrderStatus.FILLED",
            filled_quantity=0.01,
            filled_at=today.replace(hour=17),
        ),
        BrokerOrderSummary(
            broker_order_id="spy_sell",
            symbol="SPY",
            side="OrderSide.SELL",
            order_type="OrderType.MARKET",
            status="OrderStatus.FILLED",
            filled_quantity=0.01,
            filled_at=today.replace(hour=18),
        ),
    ]

    records = _detect_day_trade_records(orders)

    assert [record.symbol for record in records] == ["SPY"]


def test_local_heuristic_score_is_bounded_and_explainable() -> None:
    candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="micro_breakout_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=[
            "Price moved above previous close.",
            "Observed volume exceeded minimum.",
            "Candidate created by deterministic strategy.",
        ],
        confidence_hint=0.74,
    )

    scored = TradeScorer().score(candidate)

    assert scored.ai_score.model_name == "local-manual"
    assert 0.55 <= scored.ai_score.score <= 0.88
    assert "Local fallback blended" in scored.ai_score.summary
    assert any("Fallback score is capped at 0.88" in concern for concern in scored.ai_score.concerns)


def test_local_heuristic_negation_does_not_reward_phrases() -> None:
    """Negation tokens before a positive keyword should flip the contribution.

    Without negation handling, "price lost VWAP" would still earn the VWAP
    setup credit because the substring appears. Verify the post-fix scorer
    rates a negated phrase strictly worse than the positive form.
    """

    positive = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="vwap_reclaim_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=[
            "Price reclaimed VWAP cleanly.",
            "Recent volume is 1.80x the recent average.",
        ],
        confidence_hint=0.74,
    )
    negated = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="vwap_reclaim_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=[
            "Price lost VWAP cleanly.",
            "Recent volume is 1.80x the recent average.",
        ],
        confidence_hint=0.74,
    )

    positive_score = TradeScorer().score(positive).ai_score.score
    negated_score = TradeScorer().score(negated).ai_score.score
    assert positive_score > negated_score


def test_local_heuristic_caps_unknown_strategy_harder() -> None:
    """A strategy without a registered prior must be capped tighter than 0.88
    so a brand-new lane can't ride alongside calibrated lanes on day one."""

    candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="brand_new_lane_v0",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.95,
        trigger_evidence=[
            "Price broke opening range high by 0.42%.",
            "Recent volume is 2.40x the recent average.",
            "Price is 1.20% above previous close.",
        ],
        confidence_hint=0.95,
    )

    scored = TradeScorer().score(candidate).ai_score
    assert scored.score <= 0.70 + 1e-9
    assert any("no registered prior" in concern for concern in scored.concerns)


def test_local_heuristic_surfaces_raw_score_when_cap_binds() -> None:
    """When the heuristic raw score would exceed the cap, surface the raw
    value as a binding-constraint concern so the operator sees the cap as
    the actual decision boundary, not background noise."""

    candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="opening_range_breakout_v1",
        symbol="AAPL",
        side="buy",
        proposed_notional=2,
        proposed_entry=290,
        proposed_stop=287.5,
        trigger_evidence=[
            "Price broke opening range high by 0.42%.",
            "Price is 1.20% above previous close.",
            "Recent volume is 2.40x the recent average.",
            "VWAP held through the pullback.",
            "Volume pressure stayed bid-side after the break.",
        ],
        confidence_hint=0.95,
    )

    scored = TradeScorer().score(candidate).ai_score
    assert scored.raw_score is not None
    if scored.raw_score > 0.88:
        assert any("binding constraint" in concern for concern in scored.concerns)
    assert scored.score <= 0.88


def test_local_heuristic_provenance_is_local() -> None:
    candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="micro_breakout_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=["Price moved above previous close."],
        confidence_hint=0.74,
    )

    scored = TradeScorer().score(candidate).ai_score
    assert scored.score_provenance == "local"


def test_local_heuristic_rewards_favorable_risk_reward() -> None:
    base = {
        "correlation_id": "evt_test",
        "strategy_id": "opening_range_breakout_v1",
        "symbol": "AAPL",
        "side": "buy",
        "proposed_notional": 2,
        "proposed_entry": 100,
        "proposed_stop": 98,
        "trigger_evidence": [
            "Price broke opening range high by 0.42%.",
            "Recent volume is 2.40x the recent average.",
            "Price is 1.20% above previous close.",
        ],
        "confidence_hint": 0.82,
    }
    poor_rr = TradeCandidate(**base, proposed_take_profit=101)
    strong_rr = TradeCandidate(**base, proposed_take_profit=105)

    poor_score = TradeScorer().score(poor_rr).ai_score.score
    strong_score = TradeScorer().score(strong_rr).ai_score.score

    assert strong_score > poor_score


def test_local_heuristic_rewards_clean_market_context() -> None:
    base = {
        "correlation_id": "evt_test",
        "strategy_id": "opening_range_breakout_v1",
        "symbol": "AAPL",
        "side": "buy",
        "proposed_notional": 2,
        "proposed_entry": 100,
        "proposed_stop": 98,
        "proposed_take_profit": 105,
        "trigger_evidence": [
            "Price broke opening range high by 0.42%.",
            "Recent volume is 2.40x the recent average.",
            "Price is 1.20% above previous close.",
        ],
        "confidence_hint": 0.82,
    }
    clean_context = TradeCandidate(
        **base,
        spread_bps=3.5,
        orderbook_imbalance=0.42,
        intraday_volatility_percent=0.34,
        volatility_regime="normal",
        market_move_percent=0.006,
        market_regime="risk_on",
        news_count_24h=2,
        latest_news_headline="AAPL shares rise after analyst upgrade",
        news_sentiment_hint="positive",
    )
    noisy_context = TradeCandidate(
        **base,
        spread_bps=82,
        orderbook_imbalance=-0.46,
        intraday_volatility_percent=1.4,
        volatility_regime="extreme",
        market_move_percent=-0.008,
        market_regime="risk_off",
        news_count_24h=1,
        latest_news_headline="AAPL shares fall after demand warning",
        news_sentiment_hint="negative",
    )

    clean_score = TradeScorer().score(clean_context).ai_score.score
    noisy = TradeScorer().score(noisy_context).ai_score

    assert clean_score > noisy.score
    assert any("wide" in concern.lower() for concern in noisy.concerns)


def test_strategy_candidates_copy_market_context() -> None:
    strategy = MicroBreakoutStrategy(
        allowed_symbols=["SPY"],
        proposed_notional=2.5,
        breakout_threshold=0.0025,
        min_volume=25_000,
        stop_loss_percent=0.025,
    )
    event = MarketEvent(
        source="test",
        symbol="SPY",
        event_kind="bar",
        price=101,
        previous_close=100,
        volume=50_000,
        spread_bps=4.2,
        orderbook_imbalance=0.31,
        intraday_volatility_percent=0.38,
        volatility_regime="normal",
        market_move_percent=0.005,
        market_regime="risk_on",
        news_count_24h=1,
        latest_news_headline="SPY advances with broad market strength",
        news_sentiment_hint="positive",
    )

    candidate = strategy.evaluate(event)

    assert candidate is not None
    assert candidate.spread_bps == 4.2
    assert candidate.orderbook_imbalance == 0.31
    assert candidate.volatility_regime == "normal"
    assert candidate.market_regime == "risk_on"
    assert candidate.news_sentiment_hint == "positive"
    assert any("Quote spread is 4.2 bps" in item for item in candidate.trigger_evidence)


def test_alpaca_quote_context_uses_top_of_book_proxy() -> None:
    class Quote:
        bid_price = 100
        ask_price = 100.05
        bid_size = 300
        ask_size = 100

    broker = object.__new__(AlpacaBroker)
    context = broker._quote_context(Quote())

    assert context["bid_price"] == 100
    assert context["ask_price"] == 100.05
    assert context["quote_depth"] == 400
    assert context["orderbook_imbalance"] == 0.5
    assert 4.9 < context["spread_bps"] < 5.1


def test_local_heuristic_rewards_stronger_setup_evidence() -> None:
    weak_candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="micro_breakout_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=[
            "Price moved above previous close.",
            "Day range position was unavailable from the market snapshot.",
        ],
        confidence_hint=0.70,
    )
    strong_candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="opening_range_breakout_v1",
        symbol="AAPL",
        side="buy",
        proposed_notional=2,
        proposed_entry=290,
        proposed_stop=284.2,
        trigger_evidence=[
            "Price broke opening range high by 0.42%.",
            "Price is 1.20% above previous close.",
            "Recent volume is 2.40x the recent average.",
            "Candidate created by opening range breakout lane.",
        ],
        confidence_hint=0.82,
    )

    weak_score = TradeScorer().score(weak_candidate).ai_score.score
    strong_score = TradeScorer().score(strong_candidate).ai_score.score

    assert strong_score > weak_score
    assert strong_score >= 0.75


def test_trade_scorer_falls_back_from_claude_to_openai(monkeypatch) -> None:
    settings.anthropic_api_key = "test-anthropic"
    settings.openai_api_key = "test-openai"
    candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="micro_breakout_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=["Price moved above previous close."],
        confidence_hint=0.74,
    )

    def fail_anthropic(self, candidate):
        raise RuntimeError("anthropic down")

    def succeed_openai(self, candidate):
        return ScoredTradeCandidate(
            candidate=candidate,
            ai_score=TradeScorer()._score_with_fallback(
                candidate,
                summary="",
                concerns=[],
                model_name=settings.openai_model,
            ).ai_score,
        )

    monkeypatch.setattr(TradeScorer, "_score_with_anthropic", fail_anthropic)
    monkeypatch.setattr(TradeScorer, "_score_with_openai", succeed_openai)

    scored = TradeScorer().score(candidate)

    assert scored.ai_score.model_name == settings.openai_model


def test_trade_scorer_falls_back_to_manual_when_models_fail(monkeypatch) -> None:
    settings.anthropic_api_key = "test-anthropic"
    settings.openai_api_key = "test-openai"
    candidate = TradeCandidate(
        correlation_id="evt_test",
        strategy_id="micro_breakout_v1",
        symbol="SPY",
        side="buy",
        proposed_notional=2,
        proposed_entry=105,
        proposed_stop=103.42,
        trigger_evidence=["Price moved above previous close."],
        confidence_hint=0.74,
    )

    monkeypatch.setattr(
        TradeScorer,
        "_score_with_anthropic",
        lambda self, candidate: (_ for _ in ()).throw(RuntimeError("anthropic down")),
    )
    monkeypatch.setattr(
        TradeScorer,
        "_score_with_openai",
        lambda self, candidate: (_ for _ in ()).throw(RuntimeError("openai down")),
    )

    scored = TradeScorer().score(candidate)

    assert scored.ai_score.model_name == "local-manual-anthropic-openai-fallback"


def test_queue_for_open_requires_live_permission() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False

    result = run_queue_for_open_cycle()

    assert result.risk_decision is not None
    assert result.risk_decision.state == "rejected"
    assert result.execution_intent is None
    assert result.broker_receipt is None
    assert any("Queue-for-open requires live trading mode" in reason for reason in result.risk_decision.reasons)


def test_autopilot_defaults_to_disabled_runtime_state() -> None:
    state = get_autopilot_state()

    assert state.enabled is False
    assert state.interval_seconds == settings.autopilot_interval_seconds
    assert state.market_open_only is True
    assert state.entry_execution_enabled is False
    assert state.exit_execution_enabled is False


def test_autopilot_state_syncs_interval_from_config(tmp_path) -> None:
    settings.runtime_data_dir = str(tmp_path)
    settings.autopilot_interval_seconds = 30
    stale_state = AutopilotState(enabled=True, interval_seconds=300)
    (tmp_path / "autopilot-state.json").write_text(
        stale_state.model_dump_json(),
        encoding="utf-8",
    )

    state = get_autopilot_state()

    assert state.interval_seconds == 30


def test_autopilot_tick_requires_live_permission_and_fails_closed() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False
    enable_autopilot("test arm")

    state = run_autopilot_once()
    safety = get_safety_state()

    assert state.enabled is False
    assert state.last_action == "disabled_by_config_error"
    assert safety.kill_switch_enabled is True
    assert safety.reason is not None
    assert "requires live trading mode" in safety.reason


def test_autopilot_live_tick_waits_when_entry_execution_is_locked(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.autopilot_allow_entries = False
    enable_autopilot("test arm")

    class FakeClock:
        is_open = True
        next_open = None

    class FakeBroker:
        def get_market_clock(self):
            return FakeClock()

        def get_reconciliation_snapshot(self, order_limit=50):
            class Snapshot:
                positions = []
                orders = []

            return Snapshot()

    monkeypatch.setattr("app.services.autopilot.get_active_alpaca_broker", lambda: FakeBroker())

    state = run_autopilot_once()

    assert state.enabled is True
    assert state.last_action is not None
    assert state.last_action.startswith("entry_execution_locked")


def test_autopilot_reports_exits_checked_before_below_minimum_entry_skip(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.autopilot_allow_entries = True
    enable_autopilot("test arm")

    class FakeClock:
        is_open = True
        next_open = None

    class FakeAccount:
        buying_power = 0.64
        portfolio_value = 10
        account_mode = "live"

    class FakeBroker:
        def get_market_clock(self):
            return FakeClock()

        def get_reconciliation_snapshot(self, order_limit=50):
            class Snapshot:
                positions = []
                orders = []

            return Snapshot()

        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return []

        def list_recent_orders(self, limit=50):
            return []

    monkeypatch.setattr("app.services.autopilot.get_active_alpaca_broker", lambda: FakeBroker())
    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    state = run_autopilot_once()

    assert state.last_action == "exit_checked_entry_skipped:buying_power_below_$1.00_minimum"


def test_live_cycle_rejects_synthetic_demo_entry(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.allow_demo_live_entries = False

    class FakeAccount:
        buying_power = 10
        portfolio_value = 10
        account_mode = "live"

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return []

        def list_recent_orders(self, limit=50):
            return []

        def get_market_clock(self):
            class FakeClock:
                is_open = True
                next_open = None

            return FakeClock()

        def has_open_duplicate_order(self, **kwargs):
            return None

    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    result = run_single_cycle(
        event=MarketEvent(
            source="local-demo",
            symbol="SPY",
            event_kind="bar",
            price=105.0,
            previous_close=104.0,
            volume=350_000,
        )
    )

    assert result.risk_decision is not None
    assert result.risk_decision.state == "rejected"
    assert result.execution_intent is None
    assert result.broker_receipt is None
    assert any("synthetic local-demo" in reason for reason in result.risk_decision.reasons)


def test_live_cycle_uses_real_market_data_events(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.allow_demo_live_entries = False

    class FakeAccount:
        buying_power = 10
        portfolio_value = 10
        account_mode = "live"

    class FakeClock:
        is_open = True
        next_open = None

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return []

        def list_recent_orders(self, limit=50):
            return []

        def get_market_clock(self):
            return FakeClock()

        def has_open_duplicate_order(self, **kwargs):
            return None

        def list_watchlist_market_events(self, symbols):
            return [
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol="SPY",
                    event_kind="bar",
                    price=104.4,
                    previous_close=104.0,
                    volume=350_000,
                    day_low=103.5,
                    day_high=106,
                    day_volume=30_000_000,
                    previous_volume=80_000_000,
                ),
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol="QQQ",
                    event_kind="bar",
                    price=106.0,
                    previous_close=104.0,
                    volume=400_000,
                    day_low=103.8,
                    day_high=106.05,
                    day_volume=90_000_000,
                    previous_volume=75_000_000,
                ),
            ]

        def submit_order(self, intent):
            return BrokerOrderReceipt(
                broker_order_id="broker_order_1",
                intent_id=intent.intent_id,
                status="accepted",
                symbol=intent.symbol,
                side=intent.side,
                submitted_notional=intent.approved_notional,
                raw_message="submitted",
            )

    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    result = run_single_cycle()

    assert result.event.source == "alpaca-snapshot"
    assert result.candidate is not None
    assert result.candidate.symbol == "QQQ"
    assert result.risk_decision is not None
    assert result.risk_decision.state == "approved"
    assert result.execution_intent is not None
    assert result.execution_intent.symbol == "QQQ"
    assert result.execution_intent.approved_notional == 2.5
    assert result.broker_receipt is not None


def test_live_cycle_rejects_extreme_entry_spread(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.allow_demo_live_entries = False
    settings.max_entry_spread_bps = 75

    class FakeAccount:
        buying_power = 10
        portfolio_value = 10
        account_mode = "live"

    class FakeClock:
        is_open = True
        next_open = None

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return []

        def list_recent_orders(self, limit=50):
            return []

        def get_market_clock(self):
            return FakeClock()

        def has_open_duplicate_order(self, **kwargs):
            return None

        def list_watchlist_market_events(self, symbols):
            return [
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol="WMT",
                    event_kind="bar",
                    price=131.05,
                    previous_close=130.24,
                    volume=50_000,
                    recent_high=131.06,
                    recent_low=130.28,
                    vwap=130.78,
                    recent_volume=60_000,
                    average_recent_volume=6_000,
                    spread_bps=480.2,
                    market_regime="risk_on",
                )
            ]

        def submit_order(self, intent):
            raise AssertionError("wide-spread entries should not reach broker submission")

    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    result = run_single_cycle()

    assert result.candidate is not None
    assert result.risk_decision is not None
    assert result.risk_decision.state == "rejected"
    assert result.execution_intent is None
    assert result.broker_receipt is None
    assert any("spread" in reason.lower() for reason in result.risk_decision.reasons)


def test_live_cycle_does_not_block_normal_buys_after_four_orders(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.allow_demo_live_entries = False

    class FakeAccount:
        buying_power = 10
        portfolio_value = 10
        account_mode = "live"

    class FakeClock:
        is_open = True
        next_open = None

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return []

        def list_recent_orders(self, limit=50):
            now = datetime.now(UTC)
            return [
                BrokerOrderSummary(
                    broker_order_id=f"order_{index}",
                    symbol=symbol,
                    side="OrderSide.BUY",
                    order_type="OrderType.MARKET",
                    status="OrderStatus.FILLED",
                    submitted_notional=2,
                    filled_quantity=0.01,
                    submitted_at=now,
                    filled_at=now,
                )
                for index, symbol in enumerate(["SPY", "NVDA", "AAPL", "COST"], start=1)
            ]

        def get_market_clock(self):
            return FakeClock()

        def has_open_duplicate_order(self, **kwargs):
            return None

        def list_watchlist_market_events(self, symbols):
            return [
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol="AMZN",
                    event_kind="bar",
                    price=230,
                    previous_close=226,
                    volume=50_000,
                    opening_range_high=228,
                    recent_volume=60_000,
                    average_recent_volume=6_000,
                )
            ]

        def submit_order(self, intent):
            return BrokerOrderReceipt(
                broker_order_id="broker_order_1",
                intent_id=intent.intent_id,
                status="accepted",
                symbol=intent.symbol,
                side=intent.side,
                submitted_notional=intent.approved_notional,
                raw_message="submitted",
            )

    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    result = run_single_cycle()

    assert result.risk_decision is not None
    assert result.risk_decision.state == "approved"
    assert result.execution_intent is not None
    assert result.execution_intent.symbol == "AMZN"


def test_live_cycle_skips_existing_position_symbol(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.allow_demo_live_entries = False

    class FakeAccount:
        buying_power = 10
        portfolio_value = 10
        account_mode = "live"

    class FakeClock:
        is_open = True
        next_open = None

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return [
                BrokerPositionSummary(
                    symbol="NVDA",
                    quantity=0.01,
                    market_value=2,
                    cost_basis=2,
                    unrealized_pl=0,
                    unrealized_pl_percent=0,
                    current_price=200,
                )
            ]

        def list_recent_orders(self, limit=50):
            return []

        def get_market_clock(self):
            return FakeClock()

        def has_open_duplicate_order(self, **kwargs):
            return None

        def list_watchlist_market_events(self, symbols):
            return [
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol="NVDA",
                    event_kind="bar",
                    price=206,
                    previous_close=196,
                    volume=50_000,
                    opening_range_high=201,
                    recent_volume=80_000,
                    average_recent_volume=7_000,
                ),
                MarketEvent(
                    source="alpaca-snapshot",
                    symbol="AMZN",
                    event_kind="bar",
                    price=230,
                    previous_close=226,
                    volume=50_000,
                    opening_range_high=228,
                    recent_volume=60_000,
                    average_recent_volume=6_000,
                ),
            ]

        def submit_order(self, intent):
            return BrokerOrderReceipt(
                broker_order_id="broker_order_1",
                intent_id=intent.intent_id,
                status="accepted",
                symbol=intent.symbol,
                side=intent.side,
                submitted_notional=intent.approved_notional,
                raw_message="submitted",
            )

    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    result = run_single_cycle()

    assert result.candidate is not None
    assert result.candidate.symbol == "AMZN"
    assert result.execution_intent is not None
    assert result.execution_intent.symbol == "AMZN"


def test_live_cycle_does_not_score_when_buying_power_is_below_fractional_minimum(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True

    class FakeAccount:
        buying_power = 0.64
        portfolio_value = 10
        account_mode = "live"

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def list_positions(self):
            return []

        def list_recent_orders(self, limit=50):
            return []

        def list_watchlist_market_events(self, symbols):
            raise AssertionError("market events should not be fetched below $1 buying power")

    monkeypatch.setattr("app.services.local_worker.get_active_alpaca_broker", lambda: FakeBroker())

    result = run_single_cycle()

    assert result.event.source == "portfolio-guard"
    assert result.candidate is None
    assert result.scored_candidate is None
    assert result.execution_intent is None
    assert result.broker_receipt is None


def test_readiness_blocks_entries_below_minimum_buying_power(monkeypatch) -> None:
    settings.trading_mode = "live"
    settings.allow_live_trading = True
    settings.autopilot_allow_entries = True
    settings.autopilot_allow_exits = True
    settings.alpaca_paper = False
    enable_autopilot("test arm")

    class FakeAccount:
        buying_power = 0.64

        def model_dump(self, mode="json"):
            return {"buying_power": self.buying_power}

    class FakeBroker:
        def get_account_status(self):
            return FakeAccount()

        def get_market_clock(self):
            from app.domain.trading import MarketClockStatus

            return MarketClockStatus(is_open=True)

        def has_market_data_access(self, symbols):
            return True, None

    monkeypatch.setattr("app.services.readiness.get_active_alpaca_broker", lambda: FakeBroker())

    result = get_morning_readiness()

    assert result["ready_for_autonomous_entries"] is False
    assert any("below the $1.00 minimum" in blocker for blocker in result["blockers"])


def test_exit_monitor_detects_stop_loss_signal() -> None:
    signals = evaluate_exit_signals(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.02,
                market_value=1.95,
                cost_basis=2,
                unrealized_pl=-0.05,
                unrealized_pl_percent=-0.02,
                current_price=97.5,
            )
        ],
        orders=[],
        execution_allowed=False,
    )

    assert len(signals) == 1
    assert signals[0].reason == "stop_loss"
    assert signals[0].execution_allowed is False


def test_exit_monitor_skips_sub_dollar_position() -> None:
    signals = evaluate_exit_signals(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.005,
                market_value=0.49,
                cost_basis=0.5,
                unrealized_pl=-0.01,
                unrealized_pl_percent=-0.02,
                current_price=97.5,
            )
        ],
        orders=[],
        execution_allowed=True,
    )

    assert signals == []


def test_exit_monitor_detects_take_profit_signal() -> None:
    signals = evaluate_exit_signals(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.01,
                market_value=1.04,
                cost_basis=1,
                unrealized_pl=0.04,
                unrealized_pl_percent=0.04,
                current_price=104,
            )
        ],
        orders=[],
        execution_allowed=True,
    )

    assert len(signals) == 1
    assert signals[0].reason == "take_profit"
    assert signals[0].execution_allowed is True


def test_exit_monitor_detects_small_win_signal() -> None:
    settings.autopilot_take_profit_percent = 6
    signals = evaluate_exit_signals(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.01,
                market_value=1.02,
                cost_basis=1,
                unrealized_pl=0.02,
                unrealized_pl_percent=0.02,
                current_price=102,
            )
        ],
        orders=[],
        execution_allowed=True,
    )

    assert len(signals) == 1
    assert signals[0].reason == "small_win"
    assert signals[0].execution_allowed is True


def test_exit_monitor_skips_position_with_open_sell_order() -> None:
    signals = evaluate_exit_signals(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.01,
                market_value=1.04,
                cost_basis=1,
                unrealized_pl=0.04,
                unrealized_pl_percent=0.04,
                current_price=104,
            )
        ],
        orders=[
            BrokerOrderSummary(
                broker_order_id="order_1",
                symbol="SPY",
                side="OrderSide.SELL",
                order_type="OrderType.MARKET",
                status="OrderStatus.ACCEPTED",
                filled_quantity=0,
            )
        ],
        execution_allowed=True,
    )

    assert signals == []


def test_exit_check_does_not_execute_when_market_is_closed() -> None:
    from app.domain.trading import BrokerAccountStatus, BrokerReconciliationSnapshot, MarketClockStatus
    from app.services.exit_monitor import run_exit_check

    class FakeBroker:
        submitted = False

        def get_market_clock(self):
            return MarketClockStatus(is_open=False)

        def get_reconciliation_snapshot(self, order_limit=50):
            return BrokerReconciliationSnapshot(
                account=BrokerAccountStatus(
                    broker="test",
                    account_mode="live",
                    account_id_hint="local",
                    status="active",
                    currency="USD",
                    buying_power=10,
                    cash=10,
                    portfolio_value=10,
                ),
                orders=[],
                positions=[
                    BrokerPositionSummary(
                        symbol="SPY",
                        quantity=0.01,
                        market_value=1.04,
                        cost_basis=1,
                        unrealized_pl=0.04,
                        unrealized_pl_percent=0.04,
                        current_price=104,
                    )
                ],
            )

        def submit_position_market_sell(self, symbol):
            self.submitted = True
            raise AssertionError("sell should not be submitted while market is closed")

    settings.autopilot_allow_exits = True
    settings.allow_outside_market_hours = False
    broker = FakeBroker()

    result = run_exit_check(broker, execute=True)

    assert broker.submitted is False
    assert result.signals
    assert result.submitted_receipts == []
    assert any("regular market is closed" in note for note in result.notes)


def test_exit_check_blocks_fourth_rolling_day_trade() -> None:
    from app.domain.trading import BrokerAccountStatus, BrokerReconciliationSnapshot, MarketClockStatus
    from app.services.exit_monitor import run_exit_check

    class FakeBroker:
        submitted = False

        def get_market_clock(self):
            return MarketClockStatus(is_open=True)

        def get_day_trade_guard(self, symbol):
            return DayTradeGuardResult(
                symbol=symbol,
                would_be_day_trade=True,
                allowed=False,
                day_trades_5_business_days=3,
                max_day_trades_5_business_days=3,
                records=[],
                reason="Day trade blocked to avoid exceeding the rolling five-business-day PDT limit.",
            )

        def get_reconciliation_snapshot(self, order_limit=50):
            return BrokerReconciliationSnapshot(
                account=BrokerAccountStatus(
                    broker="test",
                    account_mode="live",
                    account_id_hint="local",
                    status="active",
                    currency="USD",
                    buying_power=10,
                    cash=10,
                    portfolio_value=10,
                ),
                orders=[],
                positions=[
                    BrokerPositionSummary(
                        symbol="AAPL",
                        quantity=0.01,
                        market_value=3,
                        cost_basis=2.9,
                        unrealized_pl=0.1,
                        unrealized_pl_percent=0.03,
                        current_price=300,
                    )
                ],
            )

        def submit_position_market_sell(self, symbol):
            self.submitted = True
            raise AssertionError("sell should be blocked by PDT guard")

    settings.autopilot_allow_exits = True
    broker = FakeBroker()

    result = run_exit_check(broker, execute=True)

    assert broker.submitted is False
    assert result.submitted_receipts == []
    assert result.signals[0].execution_allowed is False
    assert any("PDT limit" in note for note in result.notes)


def test_protection_plan_marks_open_position_without_sell_order_unprotected() -> None:
    plan = build_protection_plan(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.01,
                market_value=5,
                cost_basis=5,
                unrealized_pl=0,
                unrealized_pl_percent=0,
                current_price=500,
            )
        ],
        orders=[],
    )

    assert plan.status == "unprotected"
    assert plan.plans[0].suggested_stop_price == 490
    assert plan.plans[0].broker_protection_supported is False
    assert plan.plans[0].protection_action == "app_managed"


def test_protection_plan_marks_whole_share_position_as_broker_oco_candidate() -> None:
    plan = build_protection_plan(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=1,
                market_value=500,
                cost_basis=500,
                unrealized_pl=0,
                unrealized_pl_percent=0,
                current_price=500,
            )
        ],
        orders=[],
    )

    assert plan.status == "unprotected"
    assert plan.plans[0].broker_protection_supported is True
    assert plan.plans[0].protection_action == "broker_oco"


def test_protection_plan_marks_position_with_open_sell_order_for_review() -> None:
    plan = build_protection_plan(
        positions=[
            BrokerPositionSummary(
                symbol="SPY",
                quantity=0.01,
                market_value=5,
                cost_basis=5,
                unrealized_pl=0,
                unrealized_pl_percent=0,
                current_price=500,
            )
        ],
        orders=[
            BrokerOrderSummary(
                broker_order_id="order_1",
                symbol="SPY",
                side="OrderSide.SELL",
                order_type="OrderType.MARKET",
                status="OrderStatus.ACCEPTED",
                filled_quantity=0,
            )
        ],
    )

    assert plan.status == "ready"
    assert plan.plans[0].status == "protected"
    assert plan.plans[0].protection_action == "none"


def test_broker_oco_protection_blocks_fractional_positions() -> None:
    broker = AlpacaBroker.__new__(AlpacaBroker)
    broker.list_positions = lambda: [
        BrokerPositionSummary(
            symbol="NVDA",
            quantity=0.038244901,
            market_value=7.88,
            cost_basis=7.89,
            unrealized_pl=-0.01,
            unrealized_pl_percent=-0.001,
            current_price=205.98,
        )
    ]
    broker._has_open_sell_order = lambda symbol: False

    with pytest.raises(ValueError, match="fractional quantity"):
        broker.submit_position_oco_protection("NVDA")
