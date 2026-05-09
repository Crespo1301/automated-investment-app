"""Options strategy lanes for Level 1 (covered call, cash-secured put).

Foundation status
-----------------
This module is the deterministic logic that turns an option chain snapshot
into an ``OptionsTradeCandidate``. It does NOT fetch chains, score with
external models, or submit orders — those are wired by the broker adapter
and the AI scorer in later passes. The lanes here are designed so the
broker integration only has to:

  1. Populate ``OptionsChainSnapshot`` from Alpaca's options chain endpoint.
  2. Pass the snapshot plus current account/positions into ``evaluate``.
  3. Hand resulting candidates to ``OptionsRiskGate``.

NOTE for Claude follow-up: when Alpaca Level 2 is approved, add a new lane
``LongDirectionalStrategy`` that scores buy_to_open of long calls/puts off
the same chain snapshot, gated by underlying confidence (re-using the
equity strategy lanes' confidence_hint as a directional input).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from app.domain.trading import (
    BrokerAccountStatus,
    BrokerPositionSummary,
    OptionContract,
    OptionsChainSnapshot,
    OptionsRiskLimits,
    OptionsTradeCandidate,
)


def _dte(expiration: str, *, today: date | None = None) -> int:
    """Days to expiration. Returns -1 if the string can't be parsed."""

    today = today or date.today()
    try:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    except ValueError:
        return -1
    return (exp_date - today).days


def _bid_ask_spread_percent(contract: OptionContract) -> float | None:
    """Return the bid-ask spread as a fraction of mid-price, or None."""

    if contract.bid is None or contract.ask is None:
        return None
    if contract.ask <= 0:
        return None
    mid = (contract.bid + contract.ask) / 2
    if mid <= 0:
        return None
    return (contract.ask - contract.bid) / mid


def _premium_per_contract(contract: OptionContract) -> float | None:
    """Mid-price × multiplier. None if quote data is missing."""

    if contract.bid is None or contract.ask is None or contract.ask <= 0:
        return None
    mid = (contract.bid + contract.ask) / 2
    if mid <= 0:
        return None
    return mid * contract.multiplier


def _passes_liquidity_gates(
    contract: OptionContract,
    limits: OptionsRiskLimits,
    *,
    today: date | None = None,
) -> tuple[bool, str | None]:
    """Return ``(passes, reason_if_failed)`` for liquidity / DTE gates.

    Centralized so both Level 1 lanes share identical gate semantics.
    """

    dte = _dte(contract.expiration, today=today)
    if dte < limits.target_dte_min or dte > limits.target_dte_max:
        return False, f"DTE {dte} outside [{limits.target_dte_min}, {limits.target_dte_max}]"
    if contract.open_interest is None or contract.open_interest < limits.min_open_interest:
        return (
            False,
            f"Open interest {contract.open_interest} below floor {limits.min_open_interest}.",
        )
    spread_pct = _bid_ask_spread_percent(contract)
    if spread_pct is None:
        return False, "Bid/ask quote unavailable."
    if spread_pct > limits.max_bid_ask_spread_percent:
        return (
            False,
            f"Bid-ask spread {spread_pct:.2%} exceeds max {limits.max_bid_ask_spread_percent:.2%}.",
        )
    return True, None


class CoveredCallStrategy:
    """Sell out-of-the-money calls against shares already owned.

    Level 1 path. For each open equity position with ≥ 100 shares of an
    approved underlying, search the chain for the call contract that:

      - sits OTM (strike > current_price),
      - meets DTE / open-interest / spread gates,
      - delivers at least the configured premium-to-collateral yield.

    Among candidates, the one with the highest premium yield wins.
    """

    strategy_id = "covered_call_v1"

    def evaluate_for_position(
        self,
        position: BrokerPositionSummary,
        chain: OptionsChainSnapshot,
        limits: OptionsRiskLimits,
        correlation_id: str,
        *,
        today: date | None = None,
    ) -> OptionsTradeCandidate | None:
        """Return the best call to sell against this position, or None."""

        underlying = position.symbol.upper()
        if underlying != chain.underlying.upper():
            return None
        if int(position.quantity) < 100:
            return None
        if underlying not in {sym.upper() for sym in limits.allowed_underlyings}:
            return None

        underlying_price = chain.underlying_price or position.current_price
        if underlying_price is None or underlying_price <= 0:
            return None

        max_contracts = min(
            int(position.quantity) // 100,
            limits.max_open_contracts,
        )
        if max_contracts < 1:
            return None

        best: tuple[float, OptionContract, float, float] | None = None
        for contract in _calls(chain.contracts):
            if contract.strike <= underlying_price:
                continue
            ok, _reason = _passes_liquidity_gates(contract, limits, today=today)
            if not ok:
                continue
            premium = _premium_per_contract(contract)
            if premium is None:
                continue
            collateral_per_contract = underlying_price * contract.multiplier
            yield_ratio = premium / collateral_per_contract
            if yield_ratio < limits.min_premium_to_collateral_ratio:
                continue
            if best is None or yield_ratio > best[0]:
                best = (yield_ratio, contract, premium, collateral_per_contract)

        if best is None:
            return None

        yield_ratio, contract, premium, collateral_per_contract = best
        return OptionsTradeCandidate(
            correlation_id=correlation_id,
            strategy_id="covered_call_v1",
            contract=contract,
            action="sell_to_open",
            contracts=max_contracts,
            expected_credit=round(premium * max_contracts, 2),
            collateral_required=round(collateral_per_contract * max_contracts, 2),
            underlying_position_quantity=position.quantity,
            trigger_evidence=[
                f"{underlying} held {position.quantity:.0f} shares — covered call eligible.",
                f"Strike {contract.strike:.2f} sits {(contract.strike / underlying_price - 1):.2%} OTM at {_dte(contract.expiration, today=today)} DTE.",
                f"Premium yield is {yield_ratio:.2%} of collateral.",
                f"Open interest {contract.open_interest}, spread {(_bid_ask_spread_percent(contract) or 0):.2%}.",
                "Candidate created by covered call lane (Level 1).",
            ],
            confidence_hint=min(0.92, 0.55 + yield_ratio * 30),
        )


class CashSecuredPutStrategy:
    """Sell out-of-the-money puts backed by cash.

    Level 1 path. For each approved underlying, search the chain for an
    OTM put that meets the same gates. Cash collateral required per
    contract is ``strike × 100``. Confidence rewards higher premium yield
    on the cash tied up.
    """

    strategy_id = "cash_secured_put_v1"

    def evaluate_for_underlying(
        self,
        chain: OptionsChainSnapshot,
        account: BrokerAccountStatus,
        limits: OptionsRiskLimits,
        correlation_id: str,
        *,
        today: date | None = None,
    ) -> OptionsTradeCandidate | None:
        """Return the best put to sell on this underlying, or None."""

        underlying = chain.underlying.upper()
        if underlying not in {sym.upper() for sym in limits.allowed_underlyings}:
            return None
        underlying_price = chain.underlying_price
        if underlying_price is None or underlying_price <= 0:
            return None

        # Reserve a portfolio-scaled cash floor before computing affordable
        # collateral so the CSP lane can never zero the cash buffer.
        reserve_dollars = max(
            0.0,
            account.portfolio_value * max(0.0, limits.cash_reserve_percent_of_portfolio),
        )
        spendable_cash = max(0.0, account.cash - reserve_dollars)
        if spendable_cash <= 0:
            return None

        best: tuple[float, OptionContract, float, float, int] | None = None
        for contract in _puts(chain.contracts):
            if contract.strike >= underlying_price:
                continue
            ok, _reason = _passes_liquidity_gates(contract, limits, today=today)
            if not ok:
                continue
            premium = _premium_per_contract(contract)
            if premium is None:
                continue
            collateral_per_contract = contract.strike * contract.multiplier
            if collateral_per_contract <= 0:
                continue
            affordable = int(spendable_cash // collateral_per_contract)
            if affordable < 1:
                continue
            contracts = min(affordable, limits.max_open_contracts)
            yield_ratio = premium / collateral_per_contract
            if yield_ratio < limits.min_premium_to_collateral_ratio:
                continue
            if best is None or yield_ratio > best[0]:
                best = (yield_ratio, contract, premium, collateral_per_contract, contracts)

        if best is None:
            return None

        yield_ratio, contract, premium, collateral_per_contract, contracts = best
        return OptionsTradeCandidate(
            correlation_id=correlation_id,
            strategy_id="cash_secured_put_v1",
            contract=contract,
            action="sell_to_open",
            contracts=contracts,
            expected_credit=round(premium * contracts, 2),
            collateral_required=round(collateral_per_contract * contracts, 2),
            underlying_position_quantity=0.0,
            trigger_evidence=[
                f"{underlying} cash-secured put: strike {contract.strike:.2f} sits {(1 - contract.strike / underlying_price):.2%} below spot.",
                f"DTE {_dte(contract.expiration, today=today)}, OI {contract.open_interest}, spread {(_bid_ask_spread_percent(contract) or 0):.2%}.",
                f"Premium yield is {yield_ratio:.2%} of cash collateral.",
                f"Spendable cash ${spendable_cash:.2f} supports {contracts} contract(s).",
                "Candidate created by cash-secured put lane (Level 1).",
            ],
            confidence_hint=min(0.92, 0.55 + yield_ratio * 30),
        )


def _calls(contracts: Iterable[OptionContract]) -> Iterable[OptionContract]:
    return (c for c in contracts if c.contract_type == "call")


def _puts(contracts: Iterable[OptionContract]) -> Iterable[OptionContract]:
    return (c for c in contracts if c.contract_type == "put")
