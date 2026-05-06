from app.core.config import configured_symbols
from app.services.broker_adapter import (
    LocalPaperBroker,
    MissingBrokerCredentialsError,
    missing_alpaca_credential_names,
)
from app.services.local_worker import get_risk_limits, run_single_cycle


def test_confirmed_watchlist_defaults_are_loaded() -> None:
    assert configured_symbols() == ["SPY", "QQQ", "NVDA", "TSLA", "AAPL"]


def test_starter_guardrails_match_confirmed_limits() -> None:
    limits = get_risk_limits()

    assert limits.max_notional_per_trade == 2
    assert limits.max_open_positions == 1
    assert limits.max_live_trades_per_day == 3
    assert limits.max_daily_loss == 2
    assert limits.allow_live_trading is False


def test_local_worker_approves_demo_candidate_in_paper_mode() -> None:
    result = run_single_cycle()

    assert result.candidate is not None
    assert result.risk_decision is not None
    assert result.risk_decision.state == "approved"
    assert result.execution_intent is not None
    assert result.execution_intent.mode == "paper"
    assert result.broker_receipt is not None
    assert result.broker_receipt.status == "accepted_local_paper"


def test_local_worker_defaults_to_no_real_broker_submission() -> None:
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
