"""Initial deterministic strategy lane."""

from app.domain.trading import MarketEvent, TradeCandidate


class MicroBreakoutStrategy:
    """Aggressive breakout detector for the confirmed liquid watchlist.

    The strategy looks for earlier momentum setups instead of waiting for only
    obvious moves. It still requires a deterministic price and volume trigger so
    the AI layer judges real candidates instead of inventing trades from scratch.
    """

    strategy_id = "micro_breakout_v1"

    def __init__(
        self,
        allowed_symbols: list[str],
        proposed_notional: float,
        breakout_threshold: float = 0.0025,
        stop_loss_percent: float = 0.025,
        min_volume: float = 25_000,
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

        day_position = self._day_position(event)
        volume_pressure = self._volume_pressure(event)
        relative_day_volume = self._relative_day_volume(event)
        confidence_hint = self._confidence_hint(
            move=move,
            day_position=day_position,
            volume_pressure=volume_pressure,
            relative_day_volume=relative_day_volume,
        )
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
                f"Price moved {move:.2%} above previous close, clearing the {self.breakout_threshold:.2%} early-breakout trigger.",
                f"Latest bar volume {event.volume:,.0f} exceeded minimum {self.min_volume:,.0f}.",
                self._range_evidence(day_position),
                self._relative_volume_evidence(relative_day_volume),
                "Candidate created by aggressive liquid-watchlist breakout strategy.",
            ],
            confidence_hint=confidence_hint,
        )

    def _day_position(self, event: MarketEvent) -> float | None:
        """Return where price sits inside the current day's high-low range."""

        if event.day_high is None or event.day_low is None:
            return None

        day_range = event.day_high - event.day_low
        if day_range <= 0:
            return None

        return max(0.0, min(1.0, (event.price - event.day_low) / day_range))

    def _volume_pressure(self, event: MarketEvent) -> float:
        """Return a bounded score for latest-bar volume pressure."""

        return max(0.0, min(1.0, event.volume / max(self.min_volume * 4, 1)))

    def _relative_day_volume(self, event: MarketEvent) -> float | None:
        """Compare today's running volume with the prior session when available."""

        if (
            event.day_volume is None
            or event.previous_volume is None
            or event.previous_volume <= 0
        ):
            return None

        return max(0.0, min(3.0, event.day_volume / event.previous_volume))

    def _confidence_hint(
        self,
        *,
        move: float,
        day_position: float | None,
        volume_pressure: float,
        relative_day_volume: float | None,
    ) -> float:
        """Rank candidates by momentum, volume pressure, and range strength."""

        range_score = day_position if day_position is not None else 0.5
        relative_volume_score = (
            min(1.0, relative_day_volume / 1.5)
            if relative_day_volume is not None
            else 0.5
        )
        raw_score = (
            0.42
            + move * 45
            + volume_pressure * 0.12
            + range_score * 0.18
            + relative_volume_score * 0.10
        )
        return max(0.0, min(0.97, raw_score))

    def _range_evidence(self, day_position: float | None) -> str:
        if day_position is None:
            return "Day range position was unavailable from the market snapshot."

        return f"Price sits in the {day_position:.0%} zone of the current day's range."

    def _relative_volume_evidence(self, relative_day_volume: float | None) -> str:
        if relative_day_volume is None:
            return "Relative day-volume comparison was unavailable from the market snapshot."

        return f"Running day volume is {relative_day_volume:.2f}x the prior session volume."
