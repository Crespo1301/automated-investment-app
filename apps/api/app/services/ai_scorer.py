"""Claude-first scoring adapter with layered model failover.

Provenance tiers
----------------
- ``anthropic``: Claude API (primary). Requires funded key.
- ``openai``: OpenAI API (secondary). Requires funded key.
- ``local``: deterministic local fallback. Always available, bounded.

Local fallback design
---------------------
The local heuristic is intentionally explainable. While provider keys are
unfunded, this layer carries scoring, so its contract is:

1. Every score is bounded by the configured fallback cap (default 0.80,
   env override ``INVESTMENT_APP_FALLBACK_SCORE_CAP``).
2. Every score carries a concerns list explaining missing context and binding
   constraints. When news, spread, depth, volatility, or broader market context
   are available, the fallback uses them.
3. The cap is reported as a binding constraint only when the raw blended
   score actually exceeds it - otherwise it's noted as background.
4. Strategy lanes without a registered prior are capped harder
   (``UNKNOWN_STRATEGY_CAP``) so a brand-new lane can't ride alongside
   battle-tested setups on day one.

The candidate contract includes ``proposed_take_profit`` so the local fallback
can reward favorable R:R (TP-distance / stop-distance) alongside stop tightness.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import settings
from app.domain.trading import AIScore, ScoredTradeCandidate, TradeCandidate


UNKNOWN_STRATEGY_CAP = 0.70


def _fallback_cap() -> float:
    """Resolve the fallback cap at call time so env-driven overrides via
    ``INVESTMENT_APP_FALLBACK_SCORE_CAP`` are honored without restarting."""

    return float(getattr(settings, "fallback_score_cap", 0.80))

# Per-lane priors, deliberately compressed (0.68-0.72 spread, was 0.62-0.78).
# A wide prior spread, at the 0.27 blend weight, structurally crowned
# opening_range_breakout_v1 before evidence/setup/stop/market context could
# weigh in - the autopilot became a one-lane bot. With selection now scoring
# the best candidate per lane (see local_worker._select_lane_candidates), the
# prior should reflect only a mild track-record tilt, not pre-decide the lane.
STRATEGY_PRIORS = {
    "opening_range_breakout_v1": 0.72,
    "vwap_reclaim_v1": 0.71,
    "relative_volume_spike_v1": 0.70,
    "pullback_continuation_v1": 0.70,
    "micro_breakout_v1": 0.69,
    "high_upside_momentum_v1": 0.68,
}

# Phrases that the evidence/setup scorers reward. Keys must match
# ``re.escape``-able tokens; matching is word-boundary so "vwap" only
# matches the standalone token and not, e.g., "subvwap".
POSITIVE_EVIDENCE_WEIGHTS = {
    "opening range": 0.05,
    "vwap": 0.04,
    "reclaimed": 0.04,
    "recent volume": 0.04,
    "volume is": 0.03,
    "volume pressure": 0.03,
    "above previous close": 0.03,
    "recovered": 0.03,
    "prior session": 0.02,
    "current day's range": 0.02,
}

NEGATIVE_EVIDENCE_WEIGHTS = {
    "unavailable": -0.04,
    "weak": -0.04,
    "stale": -0.05,
    "below": -0.03,
    "wide": -0.03,
}

# Negation tokens that, when they appear within ``NEGATION_WINDOW`` words
# *before* a positive phrase, flip the contribution to negative.
# Example: "price reclaimed VWAP" → +0.04. "price lost VWAP" → -0.04.
# Without this, "below VWAP" would simultaneously add +0.04 (vwap) and
# -0.03 (below), netting +0.01 when it should net negative.
#
# Note: ``broke`` is intentionally NOT in this set. In the strategy-engine
# evidence corpus, "broke" is overwhelmingly bullish ("broke opening range
# high", "broke resistance"). The negation case "broke below" is already
# caught by the ``below`` token sitting immediately before the positive
# phrase, so listing ``broke`` here would only generate false negatives.
NEGATION_TOKENS = {
    "below",
    "under",
    "lost",
    "failed",
    "rejected",
    "lacks",
    "missing",
    "without",
    "no",
    "not",
}
NEGATION_WINDOW = 3

# Tokens at the start of a bullet that flag the bullet as describing
# *historical* setup context rather than current signal direction. When a
# bullet leads with one of these, scoring skips both negation flips and
# headwind penalties inside that bullet — otherwise lanes like vwap_reclaim
# get double-punished for the bullet "Previous bar close was below VWAP",
# which is the bullish setup pre-condition, not a live headwind.
HISTORICAL_CONTEXT_TOKENS = {"previous", "prior", "earlier", "before"}
HISTORICAL_CONTEXT_HEAD_WINDOW = 4


def _tokenize(text: str) -> list[str]:
    """Return lower-cased word tokens from a free-form evidence string."""

    return re.findall(r"[a-z0-9%]+(?:'[a-z]+)?", text.lower())


def _contains_phrase(haystack_words: list[str], phrase: str) -> list[int]:
    """Return start indices where ``phrase`` (lower-cased) appears as
    consecutive whole words inside ``haystack_words``."""

    parts = phrase.lower().split()
    if not parts:
        return []
    hits: list[int] = []
    n = len(haystack_words)
    m = len(parts)
    for i in range(n - m + 1):
        if haystack_words[i : i + m] == parts:
            hits.append(i)
    return hits


def _is_negated(haystack_words: list[str], start: int) -> bool:
    """True if any negation token appears within NEGATION_WINDOW words
    immediately before ``start``."""

    window_start = max(0, start - NEGATION_WINDOW)
    return any(token in NEGATION_TOKENS for token in haystack_words[window_start:start])


def _is_historical_bullet(words: list[str]) -> bool:
    """True when a bullet leads with a historical-context token.

    Strategy-engine bullets like ``"Previous bar close was below VWAP."``
    describe the *setup pre-condition* that justifies the bullish entry.
    Treating them as live headwinds double-penalizes valid candidates.
    """

    return any(token in HISTORICAL_CONTEXT_TOKENS for token in words[:HISTORICAL_CONTEXT_HEAD_WINDOW])


class TradeScorer:
    """Score trade candidates without changing order size or risk policy."""

    def score(self, candidate: TradeCandidate) -> ScoredTradeCandidate:
        """Return an advisory score for a candidate."""

        if settings.anthropic_api_key:
            try:
                return self._score_with_anthropic(candidate)
            except Exception as anthropic_exc:
                if settings.openai_api_key:
                    try:
                        return self._score_with_openai(candidate)
                    except Exception as openai_exc:
                        return self._score_with_fallback(
                            candidate,
                            summary=(
                                "Claude scoring was unavailable, then OpenAI scoring was unavailable, "
                                "so the worker failed closed into the manual heuristic score."
                            ),
                            concerns=[
                                f"Claude scoring error: {anthropic_exc.__class__.__name__}.",
                                f"OpenAI scoring error: {openai_exc.__class__.__name__}.",
                                "Review provider billing, quota, and rate-limit posture before relying on model scoring.",
                            ],
                            model_name="local-manual-anthropic-openai-fallback",
                        )

                return self._score_with_fallback(
                    candidate,
                    summary=(
                        "Claude scoring was unavailable and OpenAI was not configured, "
                        "so the worker failed closed into the manual heuristic score."
                    ),
                    concerns=[
                        f"Claude scoring error: {anthropic_exc.__class__.__name__}.",
                        "OpenAI fallback was unavailable because no OpenAI key is configured.",
                    ],
                    model_name="local-manual-anthropic-fallback",
                )

        if settings.openai_api_key:
            try:
                return self._score_with_openai(candidate)
            except Exception as openai_exc:
                return self._score_with_fallback(
                    candidate,
                    summary=(
                        "OpenAI scoring was unavailable, so the worker failed closed "
                        "into the manual heuristic score."
                    ),
                    concerns=[
                        f"OpenAI scoring error: {openai_exc.__class__.__name__}.",
                        "Review API billing/quota before relying on model scoring.",
                    ],
                    model_name="local-manual-openai-fallback",
                )

        return self._score_with_fallback(
            candidate,
            summary=(
                "Claude and OpenAI keys are not configured, so the worker used the "
                "manual heuristic score."
            ),
            concerns=[
                "No live model context was used.",
                "Do not treat this as production-grade signal validation.",
            ],
            model_name="local-manual",
        )

    def _score_with_fallback(
        self,
        candidate: TradeCandidate,
        summary: str,
        concerns: list[str],
        model_name: str,
    ) -> ScoredTradeCandidate:
        """Return an explainable deterministic fallback score."""

        score, raw_score, heuristic_summary, heuristic_concerns = self._local_heuristic_score(
            candidate
        )
        joined_summary = f"{summary} {heuristic_summary}" if summary else heuristic_summary
        return ScoredTradeCandidate(
            candidate=candidate,
            ai_score=AIScore(
                model_name=model_name,
                score=score,
                raw_score=raw_score,
                score_provenance="local",
                summary=joined_summary,
                concerns=concerns + heuristic_concerns,
            ),
        )

    def _local_heuristic_score(
        self, candidate: TradeCandidate
    ) -> tuple[float, float, str, list[str]]:
        """Score a candidate with transparent, bounded local rules.

        Returns ``(capped_score, raw_score, summary, concerns)``.

        Reward strong intraday setup evidence; fail closed on weak provenance,
        vague evidence, or unhealthy stop distance.
        """

        confidence_score = max(0.0, min(1.0, candidate.confidence_hint))
        strategy_prior = STRATEGY_PRIORS.get(candidate.strategy_id, 0.58)
        evidence_score, evidence_notes = self._evidence_score(candidate)
        stop_risk_score = self._stop_risk_score(candidate)
        setup_quality_score = self._setup_quality_score(candidate)
        market_context_score, market_context_notes = self._market_context_score(candidate)

        raw_score = (
            strategy_prior * 0.27
            + confidence_score * 0.24
            + evidence_score * 0.18
            + setup_quality_score * 0.11
            + stop_risk_score * 0.10
            + market_context_score * 0.10
        )
        raw_score = max(0.0, raw_score)

        # Regime dampener: a risk-off broader market or an extreme intraday
        # volatility regime multiplicatively haircuts the blended score. The
        # market-context component alone only moved the score ~0.01, which
        # was not enough to stand the bot down in hostile tape. Applied
        # before the cap so a dampened score also clears the cap less often.
        regime_notes: list[str] = []
        if candidate.market_regime == "risk_off":
            risk_off_multiplier = max(0.0, min(1.0, settings.risk_off_score_multiplier))
            raw_score *= risk_off_multiplier
            regime_notes.append(
                f"Risk-off market regime applied a x{risk_off_multiplier:.2f} score dampener."
            )
        if candidate.volatility_regime == "extreme":
            extreme_vol_multiplier = max(
                0.0, min(1.0, settings.extreme_volatility_score_multiplier)
            )
            raw_score *= extreme_vol_multiplier
            regime_notes.append(
                f"Extreme volatility regime applied a x{extreme_vol_multiplier:.2f} score dampener."
            )

        unknown_strategy = candidate.strategy_id not in STRATEGY_PRIORS
        fallback_cap = _fallback_cap()
        concerns: list[str] = [
            f"Fallback score is capped at {fallback_cap:.2f} because no external model context was available.",
            "Fallback used deterministic market-context checks for spread, top-of-book depth, volatility, broader market regime, and news when available.",
        ]
        concerns.extend(regime_notes)
        if raw_score > fallback_cap:
            concerns.append(
                f"Heuristic raw score was {raw_score:.2f}; cap is the binding constraint on this candidate."
            )

        applied_cap = fallback_cap
        if unknown_strategy:
            applied_cap = min(applied_cap, UNKNOWN_STRATEGY_CAP)
            concerns.append(
                f"Strategy '{candidate.strategy_id}' has no registered prior - capped to {UNKNOWN_STRATEGY_CAP:.2f} until a prior is calibrated."
            )

        capped_score = min(applied_cap, raw_score)

        concerns.extend(evidence_notes)
        concerns.extend(market_context_notes)
        if evidence_score < 0.55:
            concerns.append("Trigger evidence is thin for aggressive autonomous entries.")
        if stop_risk_score < 0.5:
            concerns.append("Proposed stop distance is wide for this starter strategy.")
        if setup_quality_score < 0.5:
            concerns.append("Setup evidence did not show enough high-conviction momentum structure.")
        if market_context_score < 0.45:
            concerns.append("Market context showed enough friction to reduce fallback conviction.")

        # NOTE: summary phrasing must include the literal substring
        # "Local fallback blended" - the test suite asserts on it.
        summary = (
            "Local fallback blended strategy prior, confidence hint, trigger evidence quality, "
            "setup structure, stop distance, and market context."
        )
        return capped_score, raw_score, summary, concerns

    def _evidence_score(self, candidate: TradeCandidate) -> tuple[float, list[str]]:
        """Score the quality and specificity of trigger evidence.

        Bullets are processed individually so historical-context bullets
        (e.g. "Previous bar close was below VWAP") don't fire negation
        flips or headwind penalties on what is actually a bullish
        pre-condition. Completeness is specificity-weighted: bullets with
        numeric magnitudes count more than vague prose.
        """

        notes: list[str] = []
        keyword_score = 0.0
        specific_count = 0
        magnitude_count = 0

        for bullet in candidate.trigger_evidence:
            words = _tokenize(bullet)
            historical = _is_historical_bullet(words)

            for phrase, weight in POSITIVE_EVIDENCE_WEIGHTS.items():
                for hit in _contains_phrase(words, phrase):
                    if not historical and _is_negated(words, hit):
                        keyword_score -= weight
                        notes.append(
                            f"Fallback evidence: '{phrase}' negated nearby, treating as headwind."
                        )
                    else:
                        keyword_score += weight

            if not historical:
                for phrase, weight in NEGATIVE_EVIDENCE_WEIGHTS.items():
                    for hit in _contains_phrase(words, phrase):
                        keyword_score += weight
                        notes.append(f"Fallback evidence penalty matched '{phrase}'.")

            if re.search(r"\d", bullet) or "%" in bullet:
                specific_count += 1
            lowered = bullet.lower()
            if "%" in lowered or "x" in lowered:
                magnitude_count += 1

        # Cap specificity contribution at five bullets so a flood of weak
        # bullets can't dominate the score.
        completeness = min(1.0, specific_count / 5)
        magnitude_bonus = min(0.10, magnitude_count * 0.025)

        score = 0.50 + completeness * 0.22 + keyword_score + magnitude_bonus
        return max(0.0, min(1.0, score)), notes

    def _setup_quality_score(self, candidate: TradeCandidate) -> float:
        """Reward setups with clear aggressive small-win structure.

        Mirrors the per-bullet, historical-context-aware logic in
        ``_evidence_score`` so a phrase like "lost VWAP" doesn't reward
        the VWAP setup credit, but a historical pre-condition bullet
        like "Previous bar close was below VWAP" doesn't sabotage it.
        """

        score = 0.45
        weights = (
            ("opening range", 0.18),
            ("vwap", 0.14),
            ("recent volume", 0.14),
            ("volume pressure", 0.14),
            ("above previous close", 0.08),
            ("recovered", 0.08),
            ("pullback", 0.08),
        )
        any_unavailable = False

        for bullet in candidate.trigger_evidence:
            words = _tokenize(bullet)
            historical = _is_historical_bullet(words)
            if "unavailable" in words:
                any_unavailable = True
            for phrase, weight in weights:
                for hit in _contains_phrase(words, phrase):
                    if not historical and _is_negated(words, hit):
                        score -= weight
                    else:
                        score += weight

        if any_unavailable:
            score -= 0.12

        return max(0.0, min(1.0, score))

    def _stop_risk_score(self, candidate: TradeCandidate) -> float:
        """Return a bounded score for stop distance and risk/reward."""

        if candidate.proposed_entry <= 0 or candidate.proposed_stop <= 0:
            return 0.0

        if candidate.side == "buy":
            risk_percent = (candidate.proposed_entry - candidate.proposed_stop) / candidate.proposed_entry
            take_profit_distance = (
                candidate.proposed_take_profit - candidate.proposed_entry
                if candidate.proposed_take_profit is not None
                else None
            )
        else:
            risk_percent = (candidate.proposed_stop - candidate.proposed_entry) / candidate.proposed_entry
            take_profit_distance = (
                candidate.proposed_entry - candidate.proposed_take_profit
                if candidate.proposed_take_profit is not None
                else None
            )

        if risk_percent <= 0:
            return 0.0
        stop_distance = abs(candidate.proposed_entry - candidate.proposed_stop)
        if risk_percent <= 0.015:
            tight_stop_score = 1.0
        elif risk_percent <= 0.03:
            tight_stop_score = 0.75
        elif risk_percent <= 0.05:
            tight_stop_score = 0.4
        else:
            tight_stop_score = 0.1

        if take_profit_distance is None or take_profit_distance <= 0 or stop_distance <= 0:
            return tight_stop_score

        risk_reward_ratio = take_profit_distance / stop_distance
        if risk_reward_ratio >= 2.0:
            reward_score = 1.0
        elif risk_reward_ratio >= 1.5:
            reward_score = 0.8
        elif risk_reward_ratio >= 1.0:
            reward_score = 0.55
        else:
            reward_score = 0.2

        return max(0.0, min(1.0, tight_stop_score * 0.55 + reward_score * 0.45))

    def _market_context_score(self, candidate: TradeCandidate) -> tuple[float, list[str]]:
        """Score liquidity, regime, and news context without needing a model."""

        score = 0.50
        notes: list[str] = []

        if candidate.spread_bps is None:
            notes.append("Spread context unavailable; fallback treated liquidity as neutral.")
        elif candidate.spread_bps <= 5:
            score += 0.10
        elif candidate.spread_bps <= 15:
            score += 0.04
        elif candidate.spread_bps <= 30:
            score -= 0.04
            notes.append(f"Spread was {candidate.spread_bps:.1f} bps, which is only moderate for fast entries.")
        elif candidate.spread_bps <= 75:
            score -= 0.12
            notes.append(f"Spread was wide at {candidate.spread_bps:.1f} bps.")
        else:
            score -= 0.22
            notes.append(f"Spread was extremely wide at {candidate.spread_bps:.1f} bps.")

        if candidate.orderbook_imbalance is None:
            notes.append("Top-of-book depth context unavailable; fallback treated depth as neutral.")
        elif candidate.orderbook_imbalance >= 0.35:
            score += 0.08
        elif candidate.orderbook_imbalance >= 0.20:
            score += 0.05
        elif candidate.orderbook_imbalance <= -0.35:
            score -= 0.10
            notes.append(f"Top-of-book imbalance was ask-heavy at {candidate.orderbook_imbalance:+.2f}.")
        elif candidate.orderbook_imbalance <= -0.20:
            score -= 0.06
            notes.append(f"Top-of-book imbalance leaned against the entry at {candidate.orderbook_imbalance:+.2f}.")

        if candidate.volatility_regime == "unknown":
            notes.append("Volatility regime unavailable; fallback treated volatility as neutral.")
        elif candidate.volatility_regime == "normal":
            score += 0.06
        elif candidate.volatility_regime == "elevated":
            score += 0.02
        elif candidate.volatility_regime == "calm":
            score -= 0.02
            notes.append("Volatility regime was calm, which can limit fast small-win follow-through.")
        elif candidate.volatility_regime == "extreme":
            score -= 0.12
            notes.append("Volatility regime was extreme, which increases slippage and stop-out risk.")

        if candidate.market_regime == "unknown":
            notes.append("Broader market regime unavailable; fallback treated index confirmation as neutral.")
        elif candidate.market_regime == "risk_on":
            score += 0.08
        elif candidate.market_regime == "neutral":
            score += 0.02
        elif candidate.market_regime == "risk_off":
            score -= 0.10
            notes.append("Broader market regime was risk-off during a long entry setup.")

        if candidate.news_sentiment_hint == "positive":
            score += 0.05
        elif candidate.news_sentiment_hint == "neutral":
            score += 0.01
        elif candidate.news_sentiment_hint == "negative":
            score -= 0.08
            notes.append("Recent news sentiment hint was negative.")
        elif candidate.news_count_24h is None:
            notes.append("News context unavailable; fallback treated headlines as neutral.")

        return max(0.0, min(1.0, score)), notes

    def _score_with_anthropic(self, candidate: TradeCandidate) -> ScoredTradeCandidate:
        """Call Anthropic and coerce the answer back into the narrow score schema."""

        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        prompt = {
            "task": (
                "Score this candidate trade for an aggressive small-account strategy "
                "that looks for overlooked momentum, volume pressure, and range-breakout setups."
            ),
            "rules": [
                "Return only JSON.",
                "Do not propose a different order size.",
                "Do not bypass risk limits.",
                "Score should be between 0 and 1.",
                "Reward asymmetric upside and early momentum when evidence is strong.",
                "Use supplied spread, top-of-book depth, volatility, market regime, and news context when present.",
                "Penalize stale breakouts, weak volume, bad stop distance, wide spread, risk-off context, or vague evidence.",
            ],
            "candidate": candidate.model_dump(mode="json"),
        }
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=600,
            messages=[{"role": "user", "content": json.dumps(prompt)}],
        )
        payload = self._extract_json(response)
        return ScoredTradeCandidate(
            candidate=candidate,
            ai_score=AIScore(
                model_name=settings.anthropic_model,
                score=float(payload.get("score", candidate.confidence_hint)),
                score_provenance="anthropic",
                summary=str(payload.get("summary", "Model returned no summary.")),
                concerns=[
                    str(concern)
                    for concern in payload.get("concerns", ["No concerns returned."])
                ],
            ),
        )

    def _score_with_openai(self, candidate: TradeCandidate) -> ScoredTradeCandidate:
        """Call OpenAI and coerce the answer back into the narrow score schema."""

        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        prompt = {
            "task": (
                "Score this candidate trade for an aggressive small-account strategy "
                "that looks for overlooked momentum, volume pressure, and range-breakout setups."
            ),
            "rules": [
                "Return only JSON.",
                "Do not propose a different order size.",
                "Do not bypass risk limits.",
                "Score should be between 0 and 1.",
                "Reward asymmetric upside and early momentum when evidence is strong.",
                "Use supplied spread, top-of-book depth, volatility, market regime, and news context when present.",
                "Penalize stale breakouts, weak volume, bad stop distance, wide spread, risk-off context, or vague evidence.",
            ],
            "candidate": candidate.model_dump(mode="json"),
        }
        response = client.responses.create(
            model=settings.openai_model,
            input=json.dumps(prompt),
        )
        payload = self._extract_json(response)
        return ScoredTradeCandidate(
            candidate=candidate,
            ai_score=AIScore(
                model_name=settings.openai_model,
                score=float(payload.get("score", candidate.confidence_hint)),
                score_provenance="openai",
                summary=str(payload.get("summary", "Model returned no summary.")),
                concerns=[
                    str(concern)
                    for concern in payload.get("concerns", ["No concerns returned."])
                ],
            ),
        )

    def _extract_json(self, response: Any) -> dict[str, Any]:
        """Extract a JSON object from Anthropic or OpenAI responses."""

        raw_text = getattr(response, "output_text", "") or ""
        if not raw_text:
            content = getattr(response, "content", None)
            if isinstance(content, list):
                raw_text = "".join(
                    getattr(block, "text", "")
                    for block in content
                    if getattr(block, "type", "") == "text"
                )

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return {
                "score": 0.0,
                "summary": "Model output was not valid JSON, so scoring failed closed.",
                "concerns": ["Malformed model response."],
            }

        if isinstance(parsed, dict):
            return parsed

        return {
            "score": 0.0,
            "summary": "Model output was JSON but not an object, so scoring failed closed.",
            "concerns": ["Unexpected model response shape."],
        }
