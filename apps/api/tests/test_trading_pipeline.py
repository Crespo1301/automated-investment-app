import pytest

from app.core.config import configured_symbols
from app.core.config import settings
from app.domain.trading import AutopilotState, MarketEvent, ScoredTradeCandidate, TradeCandidate
from app.services.ai_scorer import TradeScorer
from app.services.audit_store import get_autopilot_state, get_daily_trade_recap, get_safety_state
from app.services.autopilot import enable_autopilot, run_autopilot_once
from app.services.broker_adapter import (
    AlpacaBroker,
    LocalPaperBroker,
    MissingBrokerCredentialsError,
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
        "strategy_breakout_threshold": settings.strategy_breakout_threshold,
        "strategy_min_volume": settings.strategy_min_volume,
        "strategy_stop_loss_percent": settings.strategy_stop_loss_percent,
        "ai_min_score": settings.ai_min_score,
        "allow_demo_live_entries": settings.allow_demo_live_entries,
        "alpaca_paper": settings.alpaca_paper,
        "duplicate_order_lookback_minutes": settings.duplicate_order_lookback_minutes,
        "openai_api_key": settings.openai_api_key,
        "runtime_data_dir": settings.runtime_data_dir,
    }
    settings.trading_mode = "paper"
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
    settings.strategy_breakout_threshold = 0.0025
    settings.strategy_min_volume = 25_000
    settings.strategy_stop_loss_percent = 0.025
    settings.ai_min_score = 0.55
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


def test_starter_guardrails_match_confirmed_limits() -> None:
    settings.allow_live_trading = False
    limits = get_risk_limits()

    assert limits.target_position_percent == 0.25
    assert limits.max_open_positions == 6
    assert limits.max_live_trades_per_day == 3
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
    assert any(provider.provider == "local-manual" for provider in recap.provider_usage)
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
    assert 0.55 <= scored.ai_score.score <= 0.82
    assert "Local heuristic blended" in scored.ai_score.summary
    assert any("Fallback score is capped" in concern for concern in scored.ai_score.concerns)


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


def test_autopilot_reports_below_minimum_buying_power(monkeypatch) -> None:
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

    assert state.last_action == "entry_skipped:buying_power_below_$1.00_minimum"


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
