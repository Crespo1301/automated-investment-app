"""Tests for the pipeline-replay harness.

Pipeline replay is the read-only iteration loop for the local fallback
scorer while Claude/OpenAI are unfunded. It must:

1. parse historical pipeline rows into ``TradeCandidate`` objects without
   loss,
2. surface per-row deltas and per-strategy aggregates,
3. flag decision flips against the configured AI threshold,
4. ignore malformed rows, non-pipeline rows, and provider-tier rows by
   default (the local scorer can't replicate model output).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.audit_replay import replay_pipeline_runs


def _local_scored_payload(
    *,
    candidate_id: str = "cand_test",
    strategy_id: str = "opening_range_breakout_v1",
    symbol: str = "AAPL",
    historical_score: float = 0.40,
    historical_decision: str = "rejected",
    extra_evidence: list[str] | None = None,
) -> dict:
    """Build a minimal pipeline_run row that the replay harness can parse."""

    candidate = {
        "candidate_id": candidate_id,
        "correlation_id": "evt_test",
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": "buy",
        "proposed_notional": 2.0,
        "proposed_entry": 100.0,
        "proposed_stop": 98.0,
        "proposed_take_profit": 105.0,
        "spread_bps": 5.0,
        "orderbook_imbalance": 0.25,
        "intraday_volatility_percent": 0.4,
        "volatility_regime": "normal",
        "market_move_percent": 0.005,
        "market_regime": "risk_on",
        "news_count_24h": 1,
        "news_sentiment_hint": "positive",
        "trigger_evidence": [
            "Price broke opening range high by 0.42%.",
            "Recent volume is 2.40x the recent average.",
            "Price is 1.20% above previous close.",
            *(extra_evidence or []),
        ],
        "confidence_hint": 0.82,
    }
    return {
        "event_type": "pipeline_run",
        "payload": {
            "event": {},
            "candidate": candidate,
            "scored_candidate": {
                "candidate": candidate,
                "ai_score": {
                    "model_name": "local-manual-anthropic-openai-fallback",
                    "score": historical_score,
                    "summary": "synthetic historical row",
                    "concerns": [],
                    "score_provenance": "local",
                },
            },
            "risk_decision": {"state": historical_decision},
            "execution_intent": None,
            "broker_receipt": None,
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_replay_handles_missing_file(tmp_path: Path) -> None:
    """A missing runs file is not an error — it yields an empty report.
    Operators should be able to run --replay-pipeline before any cycles
    have been recorded without crashing."""

    report = replay_pipeline_runs(runs_path=tmp_path / "missing.jsonl")
    assert report.rows_scanned == 0
    assert report.rows_replayed == 0
    assert report.diffs == []


def test_replay_recovers_candidate_and_emits_delta(tmp_path: Path) -> None:
    """Round-trip: a recorded local-tier row should be re-parseable into
    a TradeCandidate, re-scored deterministically, and surface a delta."""

    runs = tmp_path / "pipeline-runs.jsonl"
    _write_jsonl(runs, [_local_scored_payload(historical_score=0.10)])

    report = replay_pipeline_runs(runs_path=runs, threshold=0.55)

    assert report.rows_scanned == 1
    assert report.rows_replayed == 1
    assert len(report.diffs) == 1
    diff = report.diffs[0]
    assert diff.strategy_id == "opening_range_breakout_v1"
    # The current scorer should rate a clean breakout candidate well above
    # the synthetic 0.10 historical score, so the delta is positive.
    assert diff.current_score > 0.5
    assert diff.delta > 0
    # That positive delta crosses the 0.55 threshold from below, which
    # counts as a decision flip (rejected → would-approve).
    assert diff.would_flip_decision is True


def test_replay_aggregates_per_strategy(tmp_path: Path) -> None:
    """Per-strategy aggregates must roll up sample count, mean delta, and
    flip count so the operator sees which lane shifted, not just totals."""

    runs = tmp_path / "pipeline-runs.jsonl"
    _write_jsonl(
        runs,
        [
            _local_scored_payload(
                strategy_id="opening_range_breakout_v1", historical_score=0.20
            ),
            _local_scored_payload(
                strategy_id="opening_range_breakout_v1", historical_score=0.30
            ),
            _local_scored_payload(
                strategy_id="vwap_reclaim_v1", historical_score=0.40
            ),
        ],
    )

    report = replay_pipeline_runs(runs_path=runs, threshold=0.55)

    assert set(report.aggregates) == {"opening_range_breakout_v1", "vwap_reclaim_v1"}
    assert report.aggregates["opening_range_breakout_v1"].sample_count == 2
    assert report.aggregates["vwap_reclaim_v1"].sample_count == 1


def test_replay_skips_non_local_tier_by_default(tmp_path: Path) -> None:
    """Replaying a model-tier row would compare deterministic against
    model output — meaningless. Default should skip with a counted reason."""

    runs = tmp_path / "pipeline-runs.jsonl"
    row = _local_scored_payload()
    row["payload"]["scored_candidate"]["ai_score"]["score_provenance"] = "anthropic"
    _write_jsonl(runs, [row])

    report = replay_pipeline_runs(runs_path=runs)

    assert report.rows_replayed == 0
    assert report.rows_skipped == 1
    assert any(reason.startswith("non_local_provenance") for reason in report.skip_reasons)


def test_replay_handles_malformed_lines(tmp_path: Path) -> None:
    """A truncated/malformed JSONL line must not crash the whole replay."""

    runs = tmp_path / "pipeline-runs.jsonl"
    valid = json.dumps(_local_scored_payload())
    runs.write_text(valid + "\n{not json at all\n" + valid + "\n", encoding="utf-8")

    report = replay_pipeline_runs(runs_path=runs)

    assert report.rows_scanned == 3
    assert report.rows_replayed == 2
    assert report.skip_reasons.get("malformed_jsonl_line") == 1


def test_replay_can_filter_pre_market_context_rows(tmp_path: Path) -> None:
    """Pre-market-context candidates were scored by a structurally different
    fallback (no market_context_score component). Replay must offer a
    filter so a scoring-logic-change validation doesn't get polluted by
    schema-evolution deltas."""

    runs = tmp_path / "pipeline-runs.jsonl"
    new_row = _local_scored_payload()
    old_row = _local_scored_payload(candidate_id="cand_old")
    old_row["payload"]["scored_candidate"]["candidate"]["spread_bps"] = None
    old_row["payload"]["candidate"]["spread_bps"] = None
    _write_jsonl(runs, [old_row, new_row])

    report = replay_pipeline_runs(runs_path=runs, only_with_market_context=True)

    assert report.rows_replayed == 1
    assert report.skip_reasons.get("pre_market_context_schema") == 1


def test_replay_summary_lists_top_movers_and_flips(tmp_path: Path) -> None:
    """to_summary() must surface the worst movers and flip details so
    the CLI output is actionable, not just a count."""

    runs = tmp_path / "pipeline-runs.jsonl"
    _write_jsonl(
        runs,
        [
            _local_scored_payload(candidate_id="cand_a", historical_score=0.10),
            _local_scored_payload(candidate_id="cand_b", historical_score=0.85),
        ],
    )

    summary = replay_pipeline_runs(runs_path=runs, threshold=0.55).to_summary()

    assert summary["rows_replayed"] == 2
    assert any(item["candidate_id"] == "cand_a" for item in summary["top_score_movers"])
    assert summary["decision_flip_count"] >= 1
    assert summary["by_strategy"][0]["sample_count"] == 2
