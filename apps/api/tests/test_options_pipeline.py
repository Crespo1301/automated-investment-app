"""Level 1 options foundation tests.

Covers:
  - domain serialization
  - Level 1 risk gate: only sell_to_open of CC/CSP allowed
  - covered call requires owned shares
  - cash-secured put requires sufficient cash above the reserve
  - liquidity gates (DTE, OI, spread)
  - small-account skip behavior

The broker adapter and AI scorer paths are intentionally NOT covered here
— those land when Alpaca's options chain endpoint is wired in a follow-up.
"""

from datetime import date, datetime, timedelta

from app.domain.trading import (
    BrokerAccountStatus,
    BrokerPositionSummary,
    OptionContract,
    OptionsChainSnapshot,
    OptionsRiskLimits,
    OptionsTradeCandidate,
)
from app.services.options_risk import LEVEL_PERMISSIONS, OptionsRiskGate
from app.services.options_strategy import (
    CashSecuredPutStrategy,
    CoveredCallStrategy,
)


def _today_for_tests() -> date:
    return date(2026, 5, 8)


def _expiration_dte(days: int, *, base: date | None = None) -> str:
    base = base or _today_for_tests()
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def _level1_limits(**overrides) -> OptionsRiskLimits:
    base = dict(
        enabled=True,
        max_level=1,
        allowed_underlyings=["AAPL", "SPY"],
        min_open_interest=500,
        max_bid_ask_spread_percent=0.05,
        target_dte_min=30,
        target_dte_max=45,
        min_premium_to_collateral_ratio=0.005,
        max_open_contracts=2,
        cash_reserve_percent_of_portfolio=0.10,
    )
    base.update(overrides)
    return OptionsRiskLimits(**base)


def _aapl_call(strike: float, dte: int, *, bid=2.10, ask=2.20, oi=2000) -> OptionContract:
    return OptionContract(
        occ_symbol=f"AAPL{(_today_for_tests() + timedelta(days=dte)).strftime('%y%m%d')}C{int(strike * 1000):08d}",
        underlying="AAPL",
        expiration=_expiration_dte(dte),
        strike=strike,
        contract_type="call",
        bid=bid,
        ask=ask,
        open_interest=oi,
    )


def _aapl_put(strike: float, dte: int, *, bid=2.40, ask=2.50, oi=2000) -> OptionContract:
    return OptionContract(
        occ_symbol=f"AAPL{(_today_for_tests() + timedelta(days=dte)).strftime('%y%m%d')}P{int(strike * 1000):08d}",
        underlying="AAPL",
        expiration=_expiration_dte(dte),
        strike=strike,
        contract_type="put",
        bid=bid,
        ask=ask,
        open_interest=oi,
    )


def _aapl_position(quantity: float, current_price: float = 230.0) -> BrokerPositionSummary:
    return BrokerPositionSummary(
        symbol="AAPL",
        quantity=quantity,
        market_value=quantity * current_price,
        cost_basis=quantity * current_price,
        unrealized_pl=0.0,
        unrealized_pl_percent=0.0,
        current_price=current_price,
    )


def _account(*, cash: float, portfolio_value: float | None = None) -> BrokerAccountStatus:
    return BrokerAccountStatus(
        broker="alpaca",
        account_mode="paper",
        account_id_hint="****0001",
        status="ACTIVE",
        currency="USD",
        buying_power=cash,
        cash=cash,
        portfolio_value=portfolio_value if portfolio_value is not None else cash,
    )


def test_level_permissions_table_is_explicit() -> None:
    """LEVEL_PERMISSIONS is the source of truth — guard against drift."""

    assert LEVEL_PERMISSIONS[0] == (set(), set())
    l1_strategies, l1_actions = LEVEL_PERMISSIONS[1]
    assert l1_strategies == {"covered_call_v1", "cash_secured_put_v1"}
    assert "sell_to_open" in l1_actions
    assert "buy_to_open" not in l1_actions  # blocked at Level 1
    l2_strategies, _ = LEVEL_PERMISSIONS[2]
    assert "long_call_v1" in l2_strategies
    assert "long_put_v1" in l2_strategies


def test_covered_call_requires_owned_shares() -> None:
    """A covered call without 100+ owned shares is impossible by definition."""

    chain = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_call(strike=235, dte=37)],
    )
    candidate = CoveredCallStrategy().evaluate_for_position(
        position=_aapl_position(quantity=50),  # < 100
        chain=chain,
        limits=_level1_limits(),
        correlation_id="evt_test",
        today=_today_for_tests(),
    )
    assert candidate is None


def test_covered_call_returns_candidate_when_eligible() -> None:
    chain = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_call(strike=235, dte=37, bid=2.10, ask=2.20, oi=4000)],
    )
    candidate = CoveredCallStrategy().evaluate_for_position(
        position=_aapl_position(quantity=100),
        chain=chain,
        limits=_level1_limits(),
        correlation_id="evt_test",
        today=_today_for_tests(),
    )
    assert candidate is not None
    assert candidate.strategy_id == "covered_call_v1"
    assert candidate.action == "sell_to_open"
    assert candidate.contracts == 1
    assert candidate.expected_credit and candidate.expected_credit > 0
    # Collateral = 100 shares × $230 = $23,000.
    assert candidate.collateral_required == 23_000.0


def test_covered_call_skips_itm_strikes() -> None:
    """Strike at or below underlying price is ITM/ATM — not an OTM CC."""

    chain = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_call(strike=225, dte=37)],
    )
    assert CoveredCallStrategy().evaluate_for_position(
        position=_aapl_position(quantity=100),
        chain=chain,
        limits=_level1_limits(),
        correlation_id="evt_test",
        today=_today_for_tests(),
    ) is None


def test_cash_secured_put_requires_cash_above_reserve() -> None:
    """A small account cannot back a CSP on a $230 underlying."""

    chain = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_put(strike=225, dte=37)],
    )
    candidate = CashSecuredPutStrategy().evaluate_for_underlying(
        chain=chain,
        account=_account(cash=10, portfolio_value=10),  # no chance
        limits=_level1_limits(),
        correlation_id="evt_test",
        today=_today_for_tests(),
    )
    assert candidate is None


def test_cash_secured_put_returns_candidate_when_funded() -> None:
    chain = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_put(strike=225, dte=37, bid=2.40, ask=2.50, oi=5000)],
    )
    candidate = CashSecuredPutStrategy().evaluate_for_underlying(
        chain=chain,
        account=_account(cash=30_000, portfolio_value=30_000),
        limits=_level1_limits(max_open_contracts=1),
        correlation_id="evt_test",
        today=_today_for_tests(),
    )
    assert candidate is not None
    assert candidate.strategy_id == "cash_secured_put_v1"
    assert candidate.action == "sell_to_open"
    assert candidate.collateral_required == 22_500.0  # 225 × 100 × 1


def test_cash_secured_put_respects_cash_reserve() -> None:
    """A 10% portfolio reserve must reduce the cash usable for collateral."""

    chain = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_put(strike=225, dte=37)],
    )
    # cash 22_600 is enough for one $22,500-collateral CSP, but with a
    # 10% reserve on a 100k portfolio (= $10,000 reserved) the spendable
    # falls to $12,600 — below the strike collateral. Lane should skip.
    candidate = CashSecuredPutStrategy().evaluate_for_underlying(
        chain=chain,
        account=_account(cash=22_600, portfolio_value=100_000),
        limits=_level1_limits(),
        correlation_id="evt_test",
        today=_today_for_tests(),
    )
    assert candidate is None


def test_liquidity_gates_block_low_oi_or_wide_spread_or_off_dte() -> None:
    """Each individual gate independently blocks the lane."""

    base_position = _aapl_position(quantity=100)
    limits = _level1_limits()

    # Off-DTE
    chain_off_dte = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_call(strike=235, dte=10)],  # too short
    )
    assert CoveredCallStrategy().evaluate_for_position(
        base_position, chain_off_dte, limits, "evt_test", today=_today_for_tests()
    ) is None

    # Low OI
    chain_low_oi = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_call(strike=235, dte=37, oi=100)],  # < 500
    )
    assert CoveredCallStrategy().evaluate_for_position(
        base_position, chain_low_oi, limits, "evt_test", today=_today_for_tests()
    ) is None

    # Wide spread (bid 2.00, ask 2.50 → 22% spread > 5%)
    chain_wide = OptionsChainSnapshot(
        underlying="AAPL",
        underlying_price=230.0,
        contracts=[_aapl_call(strike=235, dte=37, bid=2.00, ask=2.50)],
    )
    assert CoveredCallStrategy().evaluate_for_position(
        base_position, chain_wide, limits, "evt_test", today=_today_for_tests()
    ) is None


def test_risk_gate_rejects_buy_to_open_at_level_1() -> None:
    """Long calls/puts (Level 2 territory) must be rejected at Level 1."""

    contract = _aapl_call(strike=235, dte=37)
    candidate = OptionsTradeCandidate(
        correlation_id="evt_test",
        strategy_id="long_call_v1",  # Level 2 strategy
        contract=contract,
        action="buy_to_open",  # Level 2 action
        contracts=1,
        expected_debit=220.0,
        collateral_required=220.0,
        trigger_evidence=["test"],
        confidence_hint=0.8,
    )
    decision, intent = OptionsRiskGate(_level1_limits()).evaluate(
        candidate=candidate,
        account=_account(cash=10_000),
        positions=[_aapl_position(quantity=100)],
    )
    assert decision.state == "rejected"
    assert intent is None
    assert any("not permitted at options Level 1" in r for r in decision.reasons)


def test_risk_gate_rejects_when_options_disabled() -> None:
    contract = _aapl_call(strike=235, dte=37)
    candidate = OptionsTradeCandidate(
        correlation_id="evt_test",
        strategy_id="covered_call_v1",
        contract=contract,
        action="sell_to_open",
        contracts=1,
        expected_credit=215.0,
        collateral_required=23_000.0,
        underlying_position_quantity=100,
        trigger_evidence=["test"],
        confidence_hint=0.7,
    )
    limits = _level1_limits(enabled=False)
    decision, _ = OptionsRiskGate(limits).evaluate(
        candidate=candidate,
        account=_account(cash=10_000),
        positions=[_aapl_position(quantity=100)],
    )
    assert decision.state == "rejected"
    assert any("disabled by configuration" in r for r in decision.reasons)


def test_risk_gate_rejects_when_kill_switch_enabled() -> None:
    contract = _aapl_call(strike=235, dte=37)
    candidate = OptionsTradeCandidate(
        correlation_id="evt_test",
        strategy_id="covered_call_v1",
        contract=contract,
        action="sell_to_open",
        contracts=1,
        expected_credit=215.0,
        collateral_required=23_000.0,
        underlying_position_quantity=100,
        trigger_evidence=["test"],
        confidence_hint=0.7,
    )
    decision, _ = OptionsRiskGate(_level1_limits(), kill_switch_enabled=True).evaluate(
        candidate=candidate,
        account=_account(cash=10_000),
        positions=[_aapl_position(quantity=100)],
    )
    assert decision.state == "rejected"
    assert any("Kill switch" in r for r in decision.reasons)


def test_risk_gate_approves_valid_covered_call() -> None:
    contract = _aapl_call(strike=235, dte=37)
    candidate = OptionsTradeCandidate(
        correlation_id="evt_test",
        strategy_id="covered_call_v1",
        contract=contract,
        action="sell_to_open",
        contracts=1,
        expected_credit=215.0,
        collateral_required=23_000.0,
        underlying_position_quantity=100,
        trigger_evidence=["test"],
        confidence_hint=0.7,
    )
    decision, intent = OptionsRiskGate(_level1_limits()).evaluate(
        candidate=candidate,
        account=_account(cash=10_000, portfolio_value=33_000),
        positions=[_aapl_position(quantity=100)],
    )
    assert decision.state == "approved"
    assert intent is not None
    assert intent.action == "sell_to_open"
    assert intent.contracts == 1
    assert intent.client_order_id.startswith("covered_call_v1-")


def test_risk_gate_blocks_csp_when_cash_below_collateral_after_reserve() -> None:
    contract = _aapl_put(strike=225, dte=37)
    candidate = OptionsTradeCandidate(
        correlation_id="evt_test",
        strategy_id="cash_secured_put_v1",
        contract=contract,
        action="sell_to_open",
        contracts=1,
        expected_credit=240.0,
        collateral_required=22_500.0,
        trigger_evidence=["test"],
        confidence_hint=0.7,
    )
    # cash 23_000, portfolio 50_000 → reserve 5_000 → spendable 18_000 < 22_500.
    decision, _ = OptionsRiskGate(_level1_limits()).evaluate(
        candidate=candidate,
        account=_account(cash=23_000, portfolio_value=50_000),
        positions=[],
    )
    assert decision.state == "rejected"
    assert any("Cash-secured put needs" in r for r in decision.reasons)
