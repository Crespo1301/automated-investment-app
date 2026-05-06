"""Local worker cycle for developing the autonomous trading loop."""

from app.core.config import configured_symbols, settings
from app.domain.trading import MarketEvent, PipelineRunResult, PortfolioState, RiskLimits
from app.services.ai_scorer import TradeScorer
from app.services.broker_adapter import get_alpaca_paper_broker, get_broker
from app.services.risk_engine import RiskEngine
from app.services.strategy_engine import MicroBreakoutStrategy


def get_risk_limits() -> RiskLimits:
    """Build risk limits from the current environment configuration."""

    return RiskLimits(
        allowed_symbols=configured_symbols(),
        max_notional_per_trade=settings.max_notional_per_trade,
        max_open_positions=settings.max_open_positions,
        max_live_trades_per_day=settings.max_live_trades_per_day,
        max_daily_loss=settings.max_daily_loss,
        allow_live_trading=settings.allow_live_trading,
    )


def get_default_portfolio_state() -> PortfolioState:
    """Create the starter portfolio state for a $10 account."""

    return PortfolioState(
        open_positions=0,
        live_trades_today=0,
        realized_pnl_today=0,
        buying_power=10,
        trading_mode="live" if settings.trading_mode == "live" else "paper",
    )


def run_single_cycle(
    event: MarketEvent | None = None,
    use_alpaca_paper: bool = False,
) -> PipelineRunResult:
    """Run one end-to-end candidate evaluation cycle.

    This is the safe local development loop: market event, deterministic
    strategy, advisory AI score, hard risk review, and paper broker receipt.
    """

    event = event or MarketEvent(
        source="local-demo",
        symbol="NVDA",
        event_kind="bar",
        price=105.0,
        previous_close=104.0,
        volume=350_000,
    )

    limits = get_risk_limits()
    portfolio_state = get_default_portfolio_state()
    strategy = MicroBreakoutStrategy(
        allowed_symbols=limits.allowed_symbols,
        proposed_notional=limits.max_notional_per_trade,
    )

    candidate = strategy.evaluate(event)
    if candidate is None:
        return PipelineRunResult(
            event=event,
            candidate=None,
            scored_candidate=None,
            risk_decision=None,
            execution_intent=None,
            broker_receipt=None,
        )

    scored_candidate = TradeScorer().score(candidate)
    risk_decision, execution_intent = RiskEngine(limits).evaluate(
        scored_candidate,
        portfolio_state,
    )
    broker_receipt = None
    if execution_intent is not None:
        broker = get_alpaca_paper_broker() if use_alpaca_paper else get_broker()
        broker_receipt = broker.submit_order(execution_intent)

    return PipelineRunResult(
        event=event,
        candidate=candidate,
        scored_candidate=scored_candidate,
        risk_decision=risk_decision,
        execution_intent=execution_intent,
        broker_receipt=broker_receipt,
    )
