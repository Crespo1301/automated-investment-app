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

1. Every score is bounded (cap = ``FALLBACK_CAP``, currently 0.88).
2. Every score carries a concerns list explaining what the heuristic does
   *not* know (no news, spread, depth, regime, broader market context).
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


FALLBACK_CAP = 0.88
UNKNOWN_STRATEGY_CAP = 0.70

STRATEGY_PRIORS = {
    "opening_range_breakout_v1": 0.78,
    "vwap_reclaim_v1": 0.73,
    "relative_volume_spike_v1": 0.71,
    "pullback_continuation_v1": 0.70,
    "micro_breakout_v1": 0.66,
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
NEGATION_TOKENS = {
    "below",
    "under",
    "lost",
    "failed",
    "rejected",
    "broke",  # "broke below"
    "lacks",
    "missing",
    "without",
    "no",
    "not",
}
NEGATION_WINDOW = 3


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

        raw_score = (
            strategy_prior * 0.30
            + confidence_score * 0.28
            + evidence_score * 0.20
            + setup_quality_score * 0.12
            + stop_risk_score * 0.10
        )
        raw_score = max(0.0, raw_score)

        unknown_strategy = candidate.strategy_id not in STRATEGY_PRIORS
        # NOTE: cap concern phrasing must include the literal substring
        # "Fallback score is capped at 0.88" - the test suite asserts on it.
        concerns: list[str] = [
            f"Fallback score is capped at {FALLBACK_CAP:.2f} because no external model context was available.",
            "Fallback scoring does not include news, spread, volatility regime, order-book depth, or broader market confirmation.",
        ]
        if raw_score > FALLBACK_CAP:
            concerns.append(
                f"Heuristic raw score was {raw_score:.2f}; cap is the binding constraint on this candidate."
            )

        applied_cap = FALLBACK_CAP
        if unknown_strategy:
            applied_cap = min(applied_cap, UNKNOWN_STRATEGY_CAP)
            concerns.append(
                f"Strategy '{candidate.strategy_id}' has no registered prior - capped to {UNKNOWN_STRATEGY_CAP:.2f} until a prior is calibrated."
            )

        capped_score = min(applied_cap, raw_score)

        concerns.extend(evidence_notes)
        if evidence_score < 0.55:
            concerns.append("Trigger evidence is thin for aggressive autonomous entries.")
        if stop_risk_score < 0.5:
            concerns.append("Proposed stop distance is wide for this starter strategy.")
        if setup_quality_score < 0.5:
            concerns.append("Setup evidence did not show enough high-conviction momentum structure.")

        # NOTE: summary phrasing must include the literal substring
        # "Local fallback blended" - the test suite asserts on it.
        summary = (
            "Local fallback blended strategy prior, confidence hint, trigger evidence quality, "
            "setup structure, and stop distance."
        )
        return capped_score, raw_score, summary, concerns

    def _evidence_score(self, candidate: TradeCandidate) -> tuple[float, list[str]]:
        """Score the quality and specificity of trigger evidence.

        Uses word-boundary phrase matching with a negation window so
        "below VWAP" doesn't fire the VWAP positive. Completeness is
        specificity-weighted: bullets containing numeric magnitudes count
        more than vague prose.
        """

        words = _tokenize(" ".join(candidate.trigger_evidence))
        notes: list[str] = []
        keyword_score = 0.0

        for phrase, weight in POSITIVE_EVIDENCE_WEIGHTS.items():
            for hit in _contains_phrase(words, phrase):
                if _is_negated(words, hit):
                    keyword_score -= weight
                    notes.append(f"Fallback evidence: '{phrase}' negated nearby, treating as headwind.")
                else:
                    keyword_score += weight

        for phrase, weight in NEGATIVE_EVIDENCE_WEIGHTS.items():
            for hit in _contains_phrase(words, phrase):
                # Negation tokens are themselves the headwind list, so a
                # double-negation ("not below") would currently still penalize.
                # That's intentional: in this corpus "not below" rarely appears
                # and erring conservative is the right default for a fallback.
                keyword_score += weight
                notes.append(f"Fallback evidence penalty matched '{phrase}'.")

        # Specificity-weighted completeness: bullets containing a percent,
        # an x-multiplier, or a digit count more than vague prose.
        specific_count = sum(
            1
            for item in candidate.trigger_evidence
            if re.search(r"\d", item) or "%" in item
        )
        # Cap specificity contribution at five bullets so a flood of weak
        # bullets can't dominate the score.
        completeness = min(1.0, specific_count / 5)

        # Bonus for bullets that name a specific magnitude (% or x-multiplier).
        magnitude_bonus = min(
            0.10,
            sum(1 for item in candidate.trigger_evidence if "%" in item.lower() or "x" in item.lower()) * 0.025,
        )

        score = 0.50 + completeness * 0.22 + keyword_score + magnitude_bonus
        return max(0.0, min(1.0, score)), notes

    def _setup_quality_score(self, candidate: TradeCandidate) -> float:
        """Reward setups with clear aggressive small-win structure.

        Mirrors the negation-aware logic in ``_evidence_score`` so a phrase
        like "lost VWAP" doesn't reward the VWAP setup credit.
        """

        words = _tokenize(" ".join(candidate.trigger_evidence))
        score = 0.45

        def fire(phrase: str, weight: float) -> None:
            nonlocal score
            for hit in _contains_phrase(words, phrase):
                if _is_negated(words, hit):
                    score -= weight
                else:
                    score += weight

        fire("opening range", 0.18)
        fire("vwap", 0.14)
        fire("recent volume", 0.14)
        fire("volume pressure", 0.14)
        fire("above previous close", 0.08)
        fire("recovered", 0.08)
        fire("pullback", 0.08)
        if "unavailable" in words:
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
                "Penalize stale breakouts, weak volume, bad stop distance, or vague evidence.",
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
                "Penalize stale breakouts, weak volume, bad stop distance, or vague evidence.",
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
