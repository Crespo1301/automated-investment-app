"""Deterministic risk gate for autonomous trading."""

from app.domain.trading import (
    ExecutionIntent,
    PortfolioState,
    RiskDecision,
    RiskLimits,
    ScoredTradeCandidate,
)
from app.core.config import settings


class RiskEngine:
    """Approve or reject scored candidates using operator-defined limits."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(
        self,
        scored_candidate: ScoredTradeCandidate,
        portfolio_state: PortfolioState,
    ) -> tuple[RiskDecision, ExecutionIntent | None]:
        """Apply hard safety rules before any broker adapter sees an order."""

        candidate = scored_candidate.candidate
        reasons: list[str] = []
        symbol = candidate.symbol.upper()

        if symbol not in self.limits.allowed_symbols:
            reasons.append(f"{symbol} is outside the allowed symbol universe.")

        if portfolio_state.open_positions >= self.limits.max_open_positions:
            reasons.append("Open position limit has already been reached.")

        if portfolio_state.realized_pnl_today <= -self.limits.max_daily_loss:
            reasons.append("Daily loss limit has already been reached.")

        if portfolio_state.trading_mode == "live" and not self.limits.allow_live_trading:
            reasons.append("Live trading is disabled by configuration.")

        if scored_candidate.ai_score.score < settings.ai_min_score:
            reasons.append("AI score is below the minimum approval threshold.")

        if (
            candidate.spread_bps is not None
            and candidate.spread_bps > self.limits.max_entry_spread_bps
        ):
            reasons.append(
                f"Quote spread {candidate.spread_bps:.1f} bps exceeds the {self.limits.max_entry_spread_bps:.1f} bps entry limit."
            )

        # Honor the operator-set cash reserve and per-trade utilization
        # ceiling so the risk gate cannot re-inflate sizing back up to full
        # buying power even if a candidate ever proposed more. The candidate
        # sizing already applies the same buffer in ``_calculate_target_notional``;
        # this is the defense-in-depth copy on the hard gate. The cash
        # reserve is computed as a fraction of portfolio value so the buffer
        # scales with the account.
        reserve_dollars = max(
            0.0,
            portfolio_state.portfolio_value * max(0.0, settings.cash_reserve_percent_of_portfolio),
        )
        spendable_buying_power = max(0.0, portfolio_state.buying_power - reserve_dollars)
        utilization = max(0.0, min(1.0, settings.max_buying_power_utilization_per_trade))
        per_trade_ceiling = spendable_buying_power * utilization
        approved_raw = min(candidate.proposed_notional, per_trade_ceiling)
        # Match the worker's spendable-fallback: if the utilization ceiling
        # alone would block the trade, but spendable buying power is still
        # ≥ $1, deploy the spendable amount instead of skipping. Reserve
        # remains untouched because spendable is already net of it.
        if approved_raw < 1.0 and spendable_buying_power >= 1.0:
            approved_raw = min(candidate.proposed_notional, spendable_buying_power)
        # Floor to two decimals so penny-rounding never overshoots the cap.
        approved_notional = int(approved_raw * 100) / 100
        if approved_notional < 1:
            reasons.append("Approved notional is below Alpaca's $1 fractional minimum.")

        if reasons:
            return (
                RiskDecision(
                    state="rejected",
                    candidate_id=candidate.candidate_id,
                    reasons=reasons,
                ),
                None,
            )

        decision = RiskDecision(
            state="approved",
            candidate_id=candidate.candidate_id,
            approved_notional=approved_notional,
            reasons=[
                "Candidate passed symbol, sizing, exposure, drawdown, and AI threshold checks."
            ],
        )
        intent = ExecutionIntent(
            candidate_id=candidate.candidate_id,
            symbol=symbol,
            side=candidate.side,
            approved_notional=approved_notional,
            mode=portfolio_state.trading_mode,
            client_order_id=f"{candidate.strategy_id}-{candidate.candidate_id}",
        )
        return decision, intent
