import pytest

from app.core.config import configured_symbols
from app.core.config import settings
from app.domain.trading import TradeCandidate
from app.services.ai_scorer import TradeScorer
from app.services.audit_store import get_autopilot_state, get_safety_state
from app.services.autopilot import enable_autopilot, run_autopilot_once
from app.services.broker_adapter import (
    LocalPaperBroker,
    MissingBrokerCredentialsError,
    missing_alpaca_credential_names,
)
from app.services.local_worker import (
    get_risk_limits,
    run_queue_for_open_cycle,
    run_single_cycle,
)


@pytest.fixture(autouse=True)
def isolate_runtime_settings(tmp_path):
    original = {
        "trading_mode": settings.trading_mode,
        "allow_live_trading": settings.allow_live_trading,
        "allow_outside_market_hours": settings.allow_outside_market_hours,
        "alpaca_paper": settings.alpaca_paper,
        "openai_api_key": settings.openai_api_key,
        "runtime_data_dir": settings.runtime_data_dir,
    }
    settings.trading_mode = "paper"
    settings.allow_live_trading = False
    settings.allow_outside_market_hours = False
    settings.alpaca_paper = True
    settings.openai_api_key = None
    settings.runtime_data_dir = str(tmp_path)
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_confirmed_watchlist_defaults_are_loaded() -> None:
    assert configured_symbols() == ["SPY", "QQQ", "NVDA", "TSLA", "AAPL"]


def test_starter_guardrails_match_confirmed_limits() -> None:
    settings.allow_live_trading = False
    limits = get_risk_limits()

    assert limits.max_notional_per_trade == 2
    assert limits.max_open_positions == 1
    assert limits.max_live_trades_per_day == 3
    assert limits.max_daily_loss == 2
    assert limits.allow_live_trading is False


def test_local_worker_approves_demo_candidate_in_paper_mode() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False
    result = run_single_cycle()

    assert result.candidate is not None
    assert result.candidate.symbol == "SPY"
    assert result.risk_decision is not None
    assert result.risk_decision.state == "approved"
    assert result.execution_intent is not None
    assert result.execution_intent.mode == "paper"
    assert result.broker_receipt is not None
    assert result.broker_receipt.status == "accepted_local_paper"


def test_local_worker_defaults_to_no_real_broker_submission() -> None:
    settings.trading_mode = "paper"
    settings.allow_live_trading = False
    result = run_single_cycle()

    assert result.broker_receipt is not None
    assert result.broker_receipt.broker_order_id.startswith("local_order_")


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

    assert scored.ai_score.model_name == "local-heuristic"
    assert 0.55 <= scored.ai_score.score <= 0.82
    assert "Local heuristic blended" in scored.ai_score.summary
    assert any("Fallback score is capped" in concern for concern in scored.ai_score.concerns)


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
