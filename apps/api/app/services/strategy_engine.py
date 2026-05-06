"""Initial deterministic strategy lane."""

from app.domain.trading import MarketEvent, TradeCandidate


class MicroBreakoutStrategy:
    """Small-capital breakout detector for the confirmed starter watchlist.

    The strategy is intentionally simple: it only emits a candidate when price is
    above the previous close by a minimum threshold and volume is non-trivial.
    This gives the AI and risk layers a deterministic event to evaluate without
    letting the model invent trades from scratch.
    """

    strategy_id = "micro_breakout_v1"

    def __init__(
        self,
        allowed_symbols: list[str],
        proposed_notional: float,
        breakout_threshold: float = 0.004,
        stop_loss_percent: float = 0.015,
        min_volume: float = 100_000,
    ) -> None:
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self.proposed_notional = proposed_notional
        self.breakout_threshold = breakout_threshold
        self.stop_loss_percent = stop_loss_percent
        self.min_volume = min_volume

    def evaluate(self, event: MarketEvent) -> TradeCandidate | None:
        """Return a trade candidate only when the deterministic setup is met."""

        symbol = event.symbol.upper()
        if symbol not in self.allowed_symbols:
            return None

        if event.event_kind != "bar" or event.previous_close is None:
            return None

        move = (event.price - event.previous_close) / event.previous_close
        if move < self.breakout_threshold or event.volume < self.min_volume:
            return None

        stop_price = event.price * (1 - self.stop_loss_percent)
        return TradeCandidate(
            correlation_id=event.correlation_id,
            strategy_id=self.strategy_id,
            symbol=symbol,
            side="buy",
            proposed_notional=self.proposed_notional,
            proposed_entry=event.price,
            proposed_stop=round(stop_price, 2),
            trigger_evidence=[
                f"Price moved {move:.2%} above previous close.",
                f"Observed volume {event.volume:,.0f} exceeded minimum {self.min_volume:,.0f}.",
                "Candidate created by deterministic micro-breakout strategy.",
            ],
            confidence_hint=min(0.95, 0.55 + move * 20),
        )

