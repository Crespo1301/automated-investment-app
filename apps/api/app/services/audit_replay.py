"""Replay recorded pipeline runs through the current scorer.

Why this exists
---------------
Both Claude and OpenAI scoring tiers are durably unavailable while provider
billing is unfunded, which means the deterministic local fallback is the
production scorer. Without a live model, the only honest way to iterate on
the fallback is to re-score historical candidates and compare against the
score that was recorded at the time.

``pipeline-runs.jsonl`` carries the full ``MarketEvent``, ``TradeCandidate``,
``AIScore``, and ``RiskDecision`` for every run. ``replay_pipeline_runs``
streams that file, rebuilds each ``TradeCandidate``, re-scores it with
``TradeScorer``, and emits a compact diff report grouped by strategy plus
flagged "decision flips" — runs whose historical score would now cross the
configured AI threshold in the opposite direction.

This is a read-only analysis helper. It never touches the broker, never
writes new audit rows, and never mutates risk state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.domain.trading import TradeCandidate
from app.services.ai_scorer import TradeScorer
from app.services.audit_store import runtime_dir


@dataclass
class ReplayDiff:
    """One historical row re-scored with the current scorer."""

    candidate_id: str
    strategy_id: str
    symbol: str
    historical_score: float
    historical_provenance: str
    current_score: float
    current_provenance: str
    historical_decision: str
    would_flip_decision: bool

    @property
    def delta(self) -> float:
        return self.current_score - self.historical_score


@dataclass
class StrategyAggregate:
    """Per-strategy aggregate of replay diffs."""

    strategy_id: str
    sample_count: int = 0
    delta_sum: float = 0.0
    delta_abs_sum: float = 0.0
    flip_count: int = 0
    max_positive_delta: float = 0.0
    max_negative_delta: float = 0.0

    def add(self, diff: ReplayDiff) -> None:
        self.sample_count += 1
        self.delta_sum += diff.delta
        self.delta_abs_sum += abs(diff.delta)
        if diff.would_flip_decision:
            self.flip_count += 1
        if diff.delta > self.max_positive_delta:
            self.max_positive_delta = diff.delta
        if diff.delta < self.max_negative_delta:
            self.max_negative_delta = diff.delta

    @property
    def average_delta(self) -> float:
        return self.delta_sum / self.sample_count if self.sample_count else 0.0

    @property
    def average_abs_delta(self) -> float:
        return self.delta_abs_sum / self.sample_count if self.sample_count else 0.0


@dataclass
class ReplayReport:
    """Complete replay report shaped for CLI and JSON dumping."""

    rows_scanned: int = 0
    rows_replayed: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    diffs: list[ReplayDiff] = field(default_factory=list)
    aggregates: dict[str, StrategyAggregate] = field(default_factory=dict)
    threshold_used: float = 0.0

    def add_skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def add_diff(self, diff: ReplayDiff) -> None:
        self.rows_replayed += 1
        self.diffs.append(diff)
        bucket = self.aggregates.setdefault(
            diff.strategy_id, StrategyAggregate(strategy_id=diff.strategy_id)
        )
        bucket.add(diff)

    def to_summary(self) -> dict[str, Any]:
        """Compact, JSON-friendly summary for CLI output."""

        notable = sorted(self.diffs, key=lambda d: abs(d.delta), reverse=True)[:5]
        flips = [d for d in self.diffs if d.would_flip_decision]
        return {
            "rows_scanned": self.rows_scanned,
            "rows_replayed": self.rows_replayed,
            "rows_skipped": self.rows_skipped,
            "skip_reasons": self.skip_reasons,
            "threshold_used": self.threshold_used,
            "decision_flip_count": len(flips),
            "by_strategy": [
                {
                    "strategy_id": agg.strategy_id,
                    "sample_count": agg.sample_count,
                    "average_delta": round(agg.average_delta, 4),
                    "average_abs_delta": round(agg.average_abs_delta, 4),
                    "max_positive_delta": round(agg.max_positive_delta, 4),
                    "max_negative_delta": round(agg.max_negative_delta, 4),
                    "decision_flips": agg.flip_count,
                }
                for agg in sorted(self.aggregates.values(), key=lambda a: a.strategy_id)
            ],
            "top_score_movers": [
                {
                    "candidate_id": d.candidate_id,
                    "strategy_id": d.strategy_id,
                    "symbol": d.symbol,
                    "historical_score": round(d.historical_score, 4),
                    "current_score": round(d.current_score, 4),
                    "delta": round(d.delta, 4),
                    "would_flip_decision": d.would_flip_decision,
                    "historical_provenance": d.historical_provenance,
                }
                for d in notable
            ],
            "decision_flips": [
                {
                    "candidate_id": d.candidate_id,
                    "strategy_id": d.strategy_id,
                    "symbol": d.symbol,
                    "historical_score": round(d.historical_score, 4),
                    "current_score": round(d.current_score, 4),
                    "historical_decision": d.historical_decision,
                }
                for d in flips
            ],
        }


def _iter_pipeline_rows(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                # Defensive: a partially-flushed line should not crash the
                # whole replay — count it as a skip via the caller.
                yield {"__malformed__": True, "raw": stripped[:200]}


def replay_pipeline_runs(
    *,
    limit: int | None = None,
    only_local_tier: bool = True,
    only_with_market_context: bool = False,
    threshold: float | None = None,
    runs_path: Path | None = None,
) -> ReplayReport:
    """Re-score every pipeline run on disk and report the deltas.

    Parameters
    ----------
    limit:
        Optional cap on rows replayed (most recent ``limit`` rows). ``None``
        replays the entire file.
    only_local_tier:
        When ``True`` (default), skip rows whose historical score came from
        a real model — replaying those would compare a deterministic score
        against a model score, which is a meaningless delta. While both
        APIs are unfunded this filter is mostly a no-op.
    only_with_market_context:
        When ``True``, skip rows whose recorded candidate predates the
        market-context schema (``spread_bps`` is None). The fallback
        scorer now includes a market-context component, so comparing
        against pre-context historical scores is apples-to-oranges. Use
        this filter when validating a scoring change rather than a
        full-history audit.
    threshold:
        Score threshold used for decision-flip detection. Defaults to
        ``settings.ai_min_score``.
    runs_path:
        Override path for tests. Defaults to ``runtime_dir() / "pipeline-runs.jsonl"``.
    """

    threshold_value = (
        threshold if threshold is not None else float(getattr(settings, "ai_min_score", 0.55))
    )
    path = runs_path if runs_path is not None else runtime_dir() / "pipeline-runs.jsonl"

    rows = list(_iter_pipeline_rows(path))
    if limit is not None and limit > 0:
        rows = rows[-limit:]

    report = ReplayReport(threshold_used=threshold_value)
    scorer = TradeScorer()

    for row in rows:
        report.rows_scanned += 1
        if row.get("__malformed__"):
            report.add_skip("malformed_jsonl_line")
            continue
        if row.get("event_type") != "pipeline_run":
            report.add_skip(f"unexpected_event_type:{row.get('event_type', 'unknown')}")
            continue

        payload = row.get("payload") or {}
        scored = payload.get("scored_candidate")
        if not scored:
            report.add_skip("no_scored_candidate")
            continue

        candidate_payload = scored.get("candidate") or payload.get("candidate")
        ai_score_payload = scored.get("ai_score") or {}
        if not candidate_payload or not ai_score_payload:
            report.add_skip("missing_candidate_or_score")
            continue

        historical_provenance = ai_score_payload.get("score_provenance", "local")
        if only_local_tier and historical_provenance != "local":
            report.add_skip(f"non_local_provenance:{historical_provenance}")
            continue

        if only_with_market_context and candidate_payload.get("spread_bps") is None:
            report.add_skip("pre_market_context_schema")
            continue

        try:
            candidate = TradeCandidate.model_validate(candidate_payload)
        except Exception as exc:  # noqa: BLE001
            report.add_skip(f"candidate_validation_error:{exc.__class__.__name__}")
            continue

        try:
            current = scorer._score_with_fallback(  # noqa: SLF001 — internal by design here
                candidate,
                summary="Replay re-score using current local fallback.",
                concerns=[],
                model_name="replay-local-fallback",
            )
        except Exception as exc:  # noqa: BLE001
            report.add_skip(f"scoring_error:{exc.__class__.__name__}")
            continue

        historical_score = float(ai_score_payload.get("score", 0.0))
        current_score = float(current.ai_score.score)
        risk_decision = payload.get("risk_decision") or {}
        historical_decision = str(risk_decision.get("state", "unknown"))

        # A "would flip" is when the current score crosses the threshold
        # in the opposite direction of the historical score. We only report
        # flips against an actual recorded historical decision so we don't
        # invent flips for skipped/cancelled rows.
        historical_pass = historical_score >= threshold_value
        current_pass = current_score >= threshold_value
        would_flip = historical_pass != current_pass

        report.add_diff(
            ReplayDiff(
                candidate_id=candidate.candidate_id,
                strategy_id=candidate.strategy_id,
                symbol=candidate.symbol,
                historical_score=historical_score,
                historical_provenance=historical_provenance,
                current_score=current_score,
                current_provenance=current.ai_score.score_provenance,
                historical_decision=historical_decision,
                would_flip_decision=would_flip,
            )
        )

    return report
