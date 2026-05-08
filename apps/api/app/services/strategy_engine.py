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
        take_profit_percent: float = 0.06,
        min_volume: float = 25_000,
    ) -> None:
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self.proposed_notional = proposed_notional
        self.breakout_threshold = breakout_threshold
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent
        self.min_volume = min_volume

    def evaluate(self, event: MarketEvent) -> TradeCandidate | None:
        """Return a trade candidate only when the deterministic setup is met."""

        symbol = event.symbol.upper()
        if symbol not in self.allowed_symbols:
            return None

        if event.event_kind != "bar" or event.previous_close is None:
            return None

        move = (event.price - event.previous_close) / event.previous_close
        effective_volume = self._effective_volume(event)
        if move < self.breakout_threshold or effective_volume < self.min_volume:
            return None

        day_position = self._day_position(event)
        volume_pressure = self._volume_pressure(effective_volume)
        relative_day_volume = self._relative_day_volume(event)
        confidence_hint = self._confidence_hint(
            move=move,
            day_position=day_position,
            volume_pressure=volume_pressure,
            relative_day_volume=relative_day_volume,
        )
        stop_price = event.price * (1 - self.stop_loss_percent)
        take_profit_price = event.price * (1 + self.take_profit_percent)
        return TradeCandidate(
            correlation_id=event.correlation_id,
            strategy_id=self.strategy_id,
            symbol=symbol,
            side="buy",
            proposed_notional=self.proposed_notional,
            proposed_entry=event.price,
            proposed_stop=round(stop_price, 2),
            proposed_take_profit=round(take_profit_price, 2),
            **_candidate_market_context(event),
            trigger_evidence=[
                f"Price moved {move:.2%} above previous close, clearing the {self.breakout_threshold:.2%} early-breakout trigger.",
                f"Intraday volume pressure {effective_volume:,.0f} exceeded minimum {self.min_volume:,.0f}.",
                self._range_evidence(day_position),
                self._relative_volume_evidence(relative_day_volume),
                *_market_context_evidence(event),
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

    def _effective_volume(self, event: MarketEvent) -> float:
        """Use recent intraday volume when available, then fall back to latest volume."""

        return max(event.volume, event.recent_volume or 0)

    def _volume_pressure(self, effective_volume: float) -> float:
        """Return a bounded score for intraday volume pressure."""

        return max(0.0, min(1.0, effective_volume / max(self.min_volume * 4, 1)))

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


class AggressiveStrategyEngine:
    """Multi-lane strategy engine for aggressive small-win compounding."""

    def __init__(
        self,
        allowed_symbols: list[str],
        proposed_notional: float,
        breakout_threshold: float = 0.0025,
        stop_loss_percent: float = 0.025,
        take_profit_percent: float = 0.06,
        high_upside_breakout_threshold: float = 0.012,
        high_upside_min_recent_volume_ratio: float = 3.0,
        high_upside_stop_loss_percent: float = 0.04,
        high_upside_take_profit_percent: float = 0.12,
        min_volume: float = 25_000,
    ) -> None:
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self.proposed_notional = proposed_notional
        self.breakout_threshold = breakout_threshold
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent
        self.high_upside_breakout_threshold = high_upside_breakout_threshold
        self.high_upside_min_recent_volume_ratio = high_upside_min_recent_volume_ratio
        self.high_upside_stop_loss_percent = high_upside_stop_loss_percent
        self.high_upside_take_profit_percent = high_upside_take_profit_percent
        self.min_volume = min_volume
        self.micro_breakout = MicroBreakoutStrategy(
            allowed_symbols=allowed_symbols,
            proposed_notional=proposed_notional,
            breakout_threshold=breakout_threshold,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            min_volume=min_volume,
        )

    def evaluate(self, event: MarketEvent) -> TradeCandidate | None:
        """Return the strongest candidate across all active strategy lanes."""

        candidates = self.evaluate_all(event)
        if not candidates:
            return None

        return max(candidates, key=lambda candidate: candidate.confidence_hint)

    def evaluate_all(self, event: MarketEvent) -> list[TradeCandidate]:
        """Return every strategy candidate produced for this event."""

        candidates = [
            self.micro_breakout.evaluate(event),
            self._vwap_reclaim(event),
            self._opening_range_breakout(event),
            self._relative_volume_spike(event),
            self._pullback_continuation(event),
            self._high_upside_momentum(event),
        ]
        return [candidate for candidate in candidates if candidate is not None]

    def _vwap_reclaim(self, event: MarketEvent) -> TradeCandidate | None:
        symbol = event.symbol.upper()
        if symbol not in self.allowed_symbols or event.vwap is None or event.previous_close is None:
            return None
        if event.price <= event.vwap or not self._has_volume_pressure(event):
            return None

        previous_close = event.previous_bar_close or event.previous_close
        reclaimed = previous_close <= event.vwap
        vwap_move = (event.price - event.vwap) / event.vwap
        close_move = (event.price - event.previous_close) / event.previous_close
        if not reclaimed and vwap_move < 0.0015:
            return None
        if close_move < 0:
            return None

        score = min(0.97, 0.58 + vwap_move * 90 + self._recent_volume_ratio(event) * 0.08)
        return self._candidate(
            event=event,
            strategy_id="vwap_reclaim_v1",
            confidence_hint=score,
            evidence=[
                f"Price reclaimed VWAP by {vwap_move:.2%}.",
                f"Previous bar close was {'below' if reclaimed else 'above'} VWAP.",
                self._recent_volume_evidence(event),
                "Candidate created by VWAP reclaim lane.",
            ],
        )

    def _opening_range_breakout(self, event: MarketEvent) -> TradeCandidate | None:
        symbol = event.symbol.upper()
        if (
            symbol not in self.allowed_symbols
            or event.opening_range_high is None
            or event.previous_close is None
        ):
            return None
        if event.price <= event.opening_range_high or not self._has_volume_pressure(event):
            return None

        range_break = (event.price - event.opening_range_high) / event.opening_range_high
        close_move = (event.price - event.previous_close) / event.previous_close
        if range_break < 0.0005 or close_move < self.breakout_threshold:
            return None

        score = min(0.98, 0.62 + range_break * 120 + close_move * 20 + self._recent_volume_ratio(event) * 0.07)
        return self._candidate(
            event=event,
            strategy_id="opening_range_breakout_v1",
            confidence_hint=score,
            evidence=[
                f"Price broke opening range high by {range_break:.2%}.",
                f"Price is {close_move:.2%} above previous close.",
                self._recent_volume_evidence(event),
                "Candidate created by opening range breakout lane.",
            ],
        )

    def _relative_volume_spike(self, event: MarketEvent) -> TradeCandidate | None:
        symbol = event.symbol.upper()
        if symbol not in self.allowed_symbols or event.previous_close is None:
            return None

        move = (event.price - event.previous_close) / event.previous_close
        recent_ratio = self._recent_volume_ratio(event)
        if move < self.breakout_threshold or recent_ratio < 1.8:
            return None

        score = min(0.96, 0.57 + move * 35 + min(0.25, recent_ratio * 0.06))
        return self._candidate(
            event=event,
            strategy_id="relative_volume_spike_v1",
            confidence_hint=score,
            evidence=[
                f"Recent volume is {recent_ratio:.2f}x the recent average.",
                f"Price moved {move:.2%} above previous close.",
                "Candidate created by relative volume spike lane.",
            ],
        )

    def _pullback_continuation(self, event: MarketEvent) -> TradeCandidate | None:
        symbol = event.symbol.upper()
        if (
            symbol not in self.allowed_symbols
            or event.recent_high is None
            or event.recent_low is None
            or event.previous_close is None
        ):
            return None

        move = (event.price - event.previous_close) / event.previous_close
        pullback_from_high = (event.recent_high - event.recent_low) / event.recent_high
        recovery_from_low = (event.price - event.recent_low) / event.recent_low
        near_high = event.price >= event.recent_high * 0.995
        above_vwap = event.vwap is None or event.price >= event.vwap
        if move < 0 or pullback_from_high < 0.002 or recovery_from_low < 0.002 or not near_high or not above_vwap:
            return None

        score = min(0.95, 0.55 + recovery_from_low * 45 + self._recent_volume_ratio(event) * 0.06)
        return self._candidate(
            event=event,
            strategy_id="pullback_continuation_v1",
            confidence_hint=score,
            evidence=[
                f"Price recovered {recovery_from_low:.2%} from the recent pullback low.",
                f"Recent pullback depth was {pullback_from_high:.2%}.",
                self._recent_volume_evidence(event),
                "Candidate created by pullback continuation lane.",
            ],
        )

    def _high_upside_momentum(self, event: MarketEvent) -> TradeCandidate | None:
        """Seek larger upside setups across the broader operator-approved universe.

        This lane is intentionally stricter than the steady compounder lanes:
        it needs a stronger same-day move, real volume pressure, broad-market
        support, and non-hostile news. The risk engine still owns sizing,
        spread limits, duplicate prevention, PDT checks, and live permission.
        """

        symbol = event.symbol.upper()
        if symbol not in self.allowed_symbols or event.previous_close is None:
            return None

        move = (event.price - event.previous_close) / event.previous_close
        recent_ratio = self._recent_volume_ratio(event)
        if move < self.high_upside_breakout_threshold:
            return None
        if recent_ratio < self.high_upside_min_recent_volume_ratio:
            return None
        if event.market_regime == "risk_off":
            return None
        if event.news_sentiment_hint == "negative":
            return None
        if event.spread_bps is not None and event.spread_bps > 50:
            return None

        range_boost = 0.0
        if event.day_high is not None and event.day_low is not None and event.day_high > event.day_low:
            range_position = (event.price - event.day_low) / (event.day_high - event.day_low)
            range_boost = max(0.0, min(0.12, range_position * 0.12))

        confidence_hint = min(
            0.99,
            0.64 + move * 12 + min(0.14, recent_ratio * 0.025) + range_boost,
        )
        return self._candidate(
            event=event,
            strategy_id="high_upside_momentum_v1",
            confidence_hint=confidence_hint,
            stop_loss_percent=self.high_upside_stop_loss_percent,
            take_profit_percent=self.high_upside_take_profit_percent,
            evidence=[
                f"High-upside lane detected {move:.2%} move above previous close.",
                f"Recent volume is {recent_ratio:.2f}x the recent average, above the {self.high_upside_min_recent_volume_ratio:.2f}x high-upside threshold.",
                f"Broader market regime is {event.market_regime}.",
                f"News sentiment hint is {event.news_sentiment_hint}.",
                "Candidate created by high-upside momentum hunter lane.",
            ],
        )

    def _candidate(
        self,
        *,
        event: MarketEvent,
        strategy_id: str,
        confidence_hint: float,
        evidence: list[str],
        stop_loss_percent: float | None = None,
        take_profit_percent: float | None = None,
    ) -> TradeCandidate:
        stop_loss_percent = self.stop_loss_percent if stop_loss_percent is None else stop_loss_percent
        take_profit_percent = self.take_profit_percent if take_profit_percent is None else take_profit_percent
        stop_price = event.price * (1 - stop_loss_percent)
        take_profit_price = event.price * (1 + take_profit_percent)
        return TradeCandidate(
            correlation_id=event.correlation_id,
            strategy_id=strategy_id,
            symbol=event.symbol.upper(),
            side="buy",
            proposed_notional=self.proposed_notional,
            proposed_entry=event.price,
            proposed_stop=round(stop_price, 2),
            proposed_take_profit=round(take_profit_price, 2),
            **_candidate_market_context(event),
            trigger_evidence=evidence + _market_context_evidence(event),
            confidence_hint=max(0.0, min(0.99, confidence_hint)),
        )

    def _recent_volume_ratio(self, event: MarketEvent) -> float:
        if (
            event.recent_volume is None
            or event.average_recent_volume is None
            or event.average_recent_volume <= 0
        ):
            return 1.0

        return event.recent_volume / max(event.average_recent_volume * 10, 1)

    def _has_volume_pressure(self, event: MarketEvent) -> bool:
        return max(event.volume, event.recent_volume or 0) >= self.min_volume

    def _recent_volume_evidence(self, event: MarketEvent) -> str:
        if event.recent_volume is None or event.average_recent_volume is None:
            return "Recent volume profile was unavailable from intraday bars."

        return f"Recent volume is {self._recent_volume_ratio(event):.2f}x the recent average."


def _candidate_market_context(event: MarketEvent) -> dict[str, object]:
    """Copy optional market context from the event into the candidate."""

    return {
        "spread_bps": event.spread_bps,
        "orderbook_imbalance": event.orderbook_imbalance,
        "intraday_volatility_percent": event.intraday_volatility_percent,
        "volatility_regime": event.volatility_regime,
        "market_move_percent": event.market_move_percent,
        "market_regime": event.market_regime,
        "news_count_24h": event.news_count_24h,
        "latest_news_headline": event.latest_news_headline,
        "news_sentiment_hint": event.news_sentiment_hint,
    }


def _market_context_evidence(event: MarketEvent) -> list[str]:
    """Return concise evidence bullets for spread, depth, volatility, market, and news."""

    evidence: list[str] = []
    if event.spread_bps is not None:
        evidence.append(f"Quote spread is {event.spread_bps:.1f} bps.")
    else:
        evidence.append("Quote spread was unavailable from the market snapshot.")

    if event.orderbook_imbalance is not None:
        evidence.append(f"Top-of-book depth imbalance is {event.orderbook_imbalance:+.2f}.")
    else:
        evidence.append("Order-book depth proxy was unavailable from the market snapshot.")

    if event.intraday_volatility_percent is not None:
        evidence.append(
            f"Intraday volatility regime is {event.volatility_regime} at {event.intraday_volatility_percent:.2f}%."
        )
    else:
        evidence.append("Intraday volatility regime was unavailable.")

    if event.market_move_percent is not None:
        evidence.append(
            f"Broader market regime is {event.market_regime} with benchmark move {event.market_move_percent:.2%}."
        )
    else:
        evidence.append("Broader market context was unavailable.")

    if event.news_count_24h:
        evidence.append(
            f"Recent news context found {event.news_count_24h} headline(s); sentiment hint is {event.news_sentiment_hint}."
        )
    else:
        evidence.append("No recent news headline context was available.")

    return evidence
