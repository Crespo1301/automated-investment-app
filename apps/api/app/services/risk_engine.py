"""Deterministic risk gate for autonomous trading."""

from app.domain.trading import (
    ExecutionIntent,
    PortfolioState,
    RiskDecision,
    RiskLimits,
    ScoredTradeCandidate,
)


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

        if candidate.proposed_notional > self.limits.max_notional_per_trade:
            reasons.append(
                "Proposed notional exceeds max notional per trade "
                f"of ${self.limits.max_notional_per_trade:.2f}."
            )

        if portfolio_state.open_positions >= self.limits.max_open_positions:
            reasons.append("Open position limit has already been reached.")

        if portfolio_state.live_trades_today >= self.limits.max_live_trades_per_day:
            reasons.append("Daily live trade count limit has already been reached.")

        if portfolio_state.realized_pnl_today <= -self.limits.max_daily_loss:
            reasons.append("Daily loss limit has already been reached.")

        if portfolio_state.trading_mode == "live" and not self.limits.allow_live_trading:
            reasons.append("Live trading is disabled by configuration.")

        if scored_candidate.ai_score.score < 0.55:
            reasons.append("AI score is below the minimum approval threshold.")

        if candidate.proposed_notional > portfolio_state.buying_power:
            reasons.append("Buying power is below proposed notional.")

        if reasons:
            return (
                RiskDecision(
                    state="rejected",
                    candidate_id=candidate.candidate_id,
                    reasons=reasons,
                ),
                None,
            )

        approved_notional = min(
            candidate.proposed_notional,
            self.limits.max_notional_per_trade,
            portfolio_state.buying_power,
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

