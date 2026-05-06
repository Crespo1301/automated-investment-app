"""Claude-first scoring adapter with layered model failover."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.domain.trading import AIScore, ScoredTradeCandidate, TradeCandidate


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

        score, heuristic_summary, heuristic_concerns = self._local_heuristic_score(candidate)
        return ScoredTradeCandidate(
            candidate=candidate,
            ai_score=AIScore(
                model_name=model_name,
                score=score,
                summary=f"{summary} {heuristic_summary}",
                concerns=concerns + heuristic_concerns,
            ),
        )

    def _local_heuristic_score(self, candidate: TradeCandidate) -> tuple[float, str, list[str]]:
        """Score a candidate with transparent, bounded local rules."""

        confidence_score = max(0.0, min(1.0, candidate.confidence_hint))
        evidence_score = min(1.0, len(candidate.trigger_evidence) / 4)
        provenance_score = 1.0 if candidate.strategy_id else 0.0
        stop_risk_score = self._stop_risk_score(candidate)
        raw_score = (
            confidence_score * 0.50
            + evidence_score * 0.20
            + stop_risk_score * 0.20
            + provenance_score * 0.10
        )
        capped_score = min(0.82, max(0.0, raw_score))
        concerns = [
            "Fallback score is capped at 0.82 because no external model context was available.",
            "Fallback scoring does not include news, spread, volatility regime, or live market depth.",
        ]
        if stop_risk_score < 0.5:
            concerns.append("Proposed stop distance is wide for this starter strategy.")

        summary = (
            "Local heuristic blended strategy confidence, trigger evidence, stop distance, "
            "and strategy provenance."
        )
        return capped_score, summary, concerns

    def _stop_risk_score(self, candidate: TradeCandidate) -> float:
        """Return a bounded score for stop distance relative to entry."""

        if candidate.proposed_entry <= 0 or candidate.proposed_stop <= 0:
            return 0.0

        if candidate.side == "buy":
            risk_percent = (candidate.proposed_entry - candidate.proposed_stop) / candidate.proposed_entry
        else:
            risk_percent = (candidate.proposed_stop - candidate.proposed_entry) / candidate.proposed_entry

        if risk_percent <= 0:
            return 0.0
        if risk_percent <= 0.015:
            return 1.0
        if risk_percent <= 0.03:
            return 0.75
        if risk_percent <= 0.05:
            return 0.4
        return 0.1

    def _score_with_anthropic(self, candidate: TradeCandidate) -> ScoredTradeCandidate:
        """Call Anthropic and coerce the answer back into the narrow score schema."""

        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        prompt = {
            "task": "Score this candidate trade for a small autonomous trading account.",
            "rules": [
                "Return only JSON.",
                "Do not propose a different order size.",
                "Do not bypass risk limits.",
                "Score should be between 0 and 1.",
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
            "task": "Score this candidate trade for a small autonomous trading account.",
            "rules": [
                "Return only JSON.",
                "Do not propose a different order size.",
                "Do not bypass risk limits.",
                "Score should be between 0 and 1.",
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
