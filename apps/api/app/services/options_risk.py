"""Options risk gate, Level-aware.

Level 1 enforcement is the hard contract:

  - Only ``sell_to_open`` is allowed.
  - Only ``covered_call_v1`` and ``cash_secured_put_v1`` are allowed.
  - Covered calls require ≥ ``contracts × 100`` shares of the underlying.
  - Cash-secured puts require ≥ ``contracts × strike × 100`` of cash, after
    the portfolio-scaled cash reserve.
  - Kill switch and operator's options-enabled flag both block.

When Level 2 is approved, this gate's ``allowed_strategies`` and
``allowed_actions`` lists expand. The structure stays the same.
"""

from __future__ import annotations

from app.domain.trading import (
    BrokerAccountStatus,
    BrokerPositionSummary,
    OptionsExecutionIntent,
    OptionsRiskDecision,
    OptionsRiskLimits,
    OptionsTradeCandidate,
    OptionsTradingLevel,
    TradingMode,
)


# Level → (allowed strategies, allowed actions). Single source of truth so
# UI surfaces and tests can assert against this without re-deriving.
LEVEL_PERMISSIONS: dict[int, tuple[set[str], set[str]]] = {
    0: (set(), set()),
    1: (
        {"covered_call_v1", "cash_secured_put_v1"},
        {"sell_to_open", "buy_to_close"},
    ),
    2: (
        {"covered_call_v1", "cash_secured_put_v1", "long_call_v1", "long_put_v1"},
        {"sell_to_open", "buy_to_close", "buy_to_open", "sell_to_close"},
    ),
    3: (
        {"covered_call_v1", "cash_secured_put_v1", "long_call_v1", "long_put_v1"},
        {"sell_to_open", "buy_to_close", "buy_to_open", "sell_to_close"},
    ),
}


class OptionsRiskGate:
    """Approve or reject options candidates against Level rules and account."""

    def __init__(
        self,
        limits: OptionsRiskLimits,
        *,
        kill_switch_enabled: bool = False,
    ) -> None:
        self.limits = limits
        self.kill_switch_enabled = kill_switch_enabled

    def evaluate(
        self,
        candidate: OptionsTradeCandidate,
        account: BrokerAccountStatus,
        positions: list[BrokerPositionSummary],
        *,
        trading_mode: TradingMode = "paper",
    ) -> tuple[OptionsRiskDecision, OptionsExecutionIntent | None]:
        """Apply Level-1 rules and account-state checks."""

        reasons: list[str] = []

        if not self.limits.enabled:
            reasons.append("Options trading is disabled by configuration.")

        if self.kill_switch_enabled:
            reasons.append("Kill switch is enabled — no options orders submitted.")

        level: OptionsTradingLevel = self.limits.max_level  # type: ignore[assignment]
        allowed_strategies, allowed_actions = LEVEL_PERMISSIONS.get(level, (set(), set()))

        if candidate.strategy_id not in allowed_strategies:
            reasons.append(
                f"Strategy {candidate.strategy_id} is not permitted at options Level {level}."
            )
        if candidate.action not in allowed_actions:
            reasons.append(
                f"Action {candidate.action} is not permitted at options Level {level}."
            )

        underlying = candidate.contract.underlying.upper()
        if underlying not in {sym.upper() for sym in self.limits.allowed_underlyings}:
            reasons.append(f"{underlying} is outside the approved options universe.")

        if candidate.strategy_id == "covered_call_v1":
            held = next(
                (
                    p
                    for p in positions
                    if p.symbol.upper() == underlying
                ),
                None,
            )
            required_shares = candidate.contracts * candidate.contract.multiplier
            if held is None or int(held.quantity) < required_shares:
                reasons.append(
                    f"Covered call requires {required_shares} shares of {underlying}; "
                    f"held {int(held.quantity) if held else 0}."
                )

        if candidate.strategy_id == "cash_secured_put_v1":
            reserve_dollars = max(
                0.0,
                account.portfolio_value * max(0.0, self.limits.cash_reserve_percent_of_portfolio),
            )
            spendable_cash = max(0.0, account.cash - reserve_dollars)
            if candidate.collateral_required > spendable_cash:
                reasons.append(
                    f"Cash-secured put needs ${candidate.collateral_required:.2f} collateral; "
                    f"spendable cash is ${spendable_cash:.2f} after the reserve."
                )

        if candidate.contracts > self.limits.max_open_contracts:
            reasons.append(
                f"Requested {candidate.contracts} contracts exceeds max_open_contracts "
                f"({self.limits.max_open_contracts})."
            )

        if reasons:
            return (
                OptionsRiskDecision(
                    state="rejected",
                    candidate_id=candidate.candidate_id,
                    reasons=reasons,
                ),
                None,
            )

        decision = OptionsRiskDecision(
            state="approved",
            candidate_id=candidate.candidate_id,
            approved_contracts=candidate.contracts,
            approved_collateral=candidate.collateral_required,
            reasons=[
                "Options candidate passed level, strategy, action, underlying, and collateral checks."
            ],
        )

        # Default to a limit order at the bid for sell_to_open (collect the
        # full bid). The broker adapter can re-price; this seeds an honest
        # default. For buy_to_open we'd default to ask; here at Level 1 the
        # action is always sell_to_open so bid is correct.
        limit_price = candidate.contract.bid
        intent = OptionsExecutionIntent(
            candidate_id=candidate.candidate_id,
            occ_symbol=candidate.contract.occ_symbol,
            underlying=underlying,
            action=candidate.action,
            contracts=candidate.contracts,
            limit_price=limit_price,
            mode=trading_mode,
            client_order_id=f"{candidate.strategy_id}-{candidate.candidate_id}",
        )
        return decision, intent


def options_limits_from_settings() -> OptionsRiskLimits:
    """Build ``OptionsRiskLimits`` from the live settings module."""

    from app.core.config import configured_options_underlyings, settings

    return OptionsRiskLimits(
        enabled=settings.options_enabled,
        max_level=settings.options_max_level,  # type: ignore[arg-type]
        allowed_underlyings=configured_options_underlyings(),
        min_open_interest=settings.options_min_open_interest,
        max_bid_ask_spread_percent=settings.options_max_bid_ask_spread_percent,
        target_dte_min=settings.options_target_dte_min,
        target_dte_max=settings.options_target_dte_max,
        min_premium_to_collateral_ratio=settings.options_min_premium_to_collateral_ratio,
        max_open_contracts=settings.options_max_open_contracts,
        cash_reserve_percent_of_portfolio=settings.cash_reserve_percent_of_portfolio,
    )
