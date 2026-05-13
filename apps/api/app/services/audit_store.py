"""Local append-only audit storage for early live trading operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domain.trading import (
    AuditEvent,
    AuditSummary,
    AutopilotState,
    BrokerOrderReceipt,
    BrokerReconciliationSnapshot,
    DailyTradeRecap,
    MarketClockStatus,
    PerformanceHistory,
    PerformancePoint,
    PipelineRunResult,
    ProviderUsageSummary,
    SafetyState,
    StrategyUsageSummary,
)


def runtime_dir() -> Path:
    """Return the runtime data folder and create it when needed."""

    path = Path(settings.runtime_data_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _jsonl_path(name: str) -> Path:
    return runtime_dir() / name


def _append_jsonl(name: str, event: AuditEvent) -> None:
    with _jsonl_path(name).open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json() + "\n")


def _read_jsonl(name: str) -> list[dict[str, Any]]:
    path = _jsonl_path(name)
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows


def record_pipeline_run(result: PipelineRunResult) -> None:
    """Persist a complete pipeline run for later inspection."""

    _append_jsonl(
        "pipeline-runs.jsonl",
        AuditEvent(event_type="pipeline_run", payload=result.model_dump(mode="json")),
    )
    if result.broker_receipt is not None:
        record_order_receipt(result.broker_receipt)


def record_order_receipt(receipt: BrokerOrderReceipt) -> None:
    """Persist a broker order receipt."""

    _append_jsonl(
        "order-events.jsonl",
        AuditEvent(event_type="broker_order_receipt", payload=receipt.model_dump(mode="json")),
    )


def record_cancel_result(result: dict[str, Any]) -> None:
    """Persist an order-cancel command result."""

    _append_jsonl("order-events.jsonl", AuditEvent(event_type="cancel_open_orders", payload=result))


def record_reconciliation_snapshot(snapshot: BrokerReconciliationSnapshot) -> None:
    """Persist account, order, and position state from the broker."""

    _append_jsonl(
        "portfolio-snapshots.jsonl",
        AuditEvent(event_type="broker_reconciliation", payload=snapshot.model_dump(mode="json")),
    )
    for order in snapshot.orders:
        _append_jsonl(
            "order-events.jsonl",
            AuditEvent(event_type="broker_order_snapshot", payload=order.model_dump(mode="json")),
        )


def safety_state_path() -> Path:
    return runtime_dir() / "safety-state.json"


def get_safety_state() -> SafetyState:
    """Read the persisted kill-switch state."""

    path = safety_state_path()
    if not path.exists():
        return SafetyState()

    return SafetyState.model_validate_json(path.read_text(encoding="utf-8"))


def set_kill_switch(enabled: bool, reason: str | None = None) -> SafetyState:
    """Persist the operator kill-switch state."""

    state = SafetyState(
        kill_switch_enabled=enabled,
        reason=reason,
        updated_at=datetime.now(UTC),
    )
    safety_state_path().write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state


def autopilot_state_path() -> Path:
    return runtime_dir() / "autopilot-state.json"


def get_autopilot_state() -> AutopilotState:
    """Read local autopilot state."""

    path = autopilot_state_path()
    if not path.exists():
        return AutopilotState(
            interval_seconds=settings.autopilot_interval_seconds,
            market_open_only=settings.autopilot_market_open_only,
            entry_execution_enabled=settings.autopilot_allow_entries,
            exit_execution_enabled=settings.autopilot_allow_exits,
        )

    state = AutopilotState.model_validate_json(path.read_text(encoding="utf-8"))
    state.interval_seconds = settings.autopilot_interval_seconds
    state.market_open_only = settings.autopilot_market_open_only
    state.entry_execution_enabled = settings.autopilot_allow_entries
    state.exit_execution_enabled = settings.autopilot_allow_exits
    return state


def set_autopilot(
    enabled: bool,
    reason: str | None = None,
    *,
    last_action: str | None = None,
    last_error: str | None = None,
) -> AutopilotState:
    """Persist local autopilot state and record the transition."""

    previous = get_autopilot_state()
    state = AutopilotState(
        enabled=enabled,
        reason=reason,
        updated_at=datetime.now(UTC),
        last_heartbeat_at=previous.last_heartbeat_at,
        last_action=last_action or previous.last_action,
        last_error=last_error,
        interval_seconds=settings.autopilot_interval_seconds,
        market_open_only=settings.autopilot_market_open_only,
        entry_execution_enabled=settings.autopilot_allow_entries,
        exit_execution_enabled=settings.autopilot_allow_exits,
    )
    autopilot_state_path().write_text(state.model_dump_json(indent=2), encoding="utf-8")
    _append_jsonl(
        "autopilot-events.jsonl",
        AuditEvent(event_type="autopilot_state", payload=state.model_dump(mode="json")),
    )
    return state


def record_autopilot_heartbeat(
    action: str,
    *,
    error: str | None = None,
) -> AutopilotState:
    """Persist a heartbeat from the supervised automation loop."""

    previous = get_autopilot_state()
    state = previous.model_copy(
        update={
            "last_heartbeat_at": datetime.now(UTC),
            "last_action": action,
            "last_error": error,
        }
    )
    autopilot_state_path().write_text(state.model_dump_json(indent=2), encoding="utf-8")
    _append_jsonl(
        "autopilot-events.jsonl",
        AuditEvent(event_type="autopilot_heartbeat", payload=state.model_dump(mode="json")),
    )
    return state


def summarize_audit(market_clock: MarketClockStatus | None = None) -> AuditSummary:
    """Return a compact audit summary for CLI and dashboard use."""

    pipeline_runs = _read_jsonl("pipeline-runs.jsonl")
    portfolio_snapshots = _read_jsonl("portfolio-snapshots.jsonl")
    order_events = _read_jsonl("order-events.jsonl")
    autopilot_events = _read_jsonl("autopilot-events.jsonl")
    last_event_at = None
    latest_order_status = None
    latest_order_symbol = None
    latest_order_notional = None

    all_events = pipeline_runs + portfolio_snapshots + order_events + autopilot_events
    if all_events:
        last_event_at = max(
            datetime.fromisoformat(str(event["created_at"]))
            for event in all_events
            if event.get("created_at")
        )

    for event in reversed(order_events):
        payload = event.get("payload") or {}
        latest_order_status = payload.get("status")
        latest_order_symbol = payload.get("symbol")
        latest_order_notional = payload.get("submitted_notional")
        if latest_order_status or latest_order_symbol:
            break

    notes = [
        "Local JSONL storage is for early operator audit only.",
        "Use broker reconciliation as the source of truth before each live cycle.",
    ]
    return AuditSummary(
        pipeline_runs=len(pipeline_runs),
        reconciliation_snapshots=len(portfolio_snapshots),
        order_events=len(order_events),
        last_event_at=last_event_at,
        latest_order_status=latest_order_status,
        latest_order_symbol=latest_order_symbol,
        latest_order_notional=latest_order_notional,
        safety_state=get_safety_state(),
        autopilot_state=get_autopilot_state(),
        market_clock=market_clock,
        notes=notes,
    )


def get_performance_history(limit: int = 80) -> PerformanceHistory:
    """Build recent performance chart points from local reconciliation snapshots."""

    snapshots = _read_jsonl("portfolio-snapshots.jsonl")[-limit:]
    points: list[PerformancePoint] = []
    open_statuses = {
        "accepted",
        "new",
        "pending_new",
        "partially_filled",
        "pending_cancel",
    }

    for event in snapshots:
        payload = event.get("payload") or {}
        account = payload.get("account") or {}
        orders = payload.get("orders") or []
        positions = payload.get("positions") or []
        created_at = event.get("created_at")
        if not created_at:
            continue

        open_orders = 0
        for order in orders:
            status = str(order.get("status") or "").split(".")[-1].lower()
            if status in open_statuses:
                open_orders += 1

        points.append(
            PerformancePoint(
                timestamp=datetime.fromisoformat(str(created_at)),
                portfolio_value=float(account.get("portfolio_value") or 0),
                buying_power=float(account.get("buying_power") or 0),
                cash=float(account.get("cash") or 0),
                open_orders=open_orders,
                open_positions=len(positions),
            )
        )

    return PerformanceHistory(
        points=points,
        notes=[
            "History is built from local broker reconciliation snapshots.",
            "Run dashboard refreshes or the autopilot loop to keep this chart current.",
        ],
    )


def get_daily_trade_recap(date: str | None = None) -> DailyTradeRecap:
    """Summarize today's compounding inputs from local audit events."""

    target_date = date or datetime.now(UTC).date().isoformat()
    pipeline_runs = [
        event
        for event in _read_jsonl("pipeline-runs.jsonl")
        if str(event.get("created_at", "")).startswith(target_date)
    ]
    portfolio_snapshots = [
        event
        for event in _read_jsonl("portfolio-snapshots.jsonl")
        if str(event.get("created_at", "")).startswith(target_date)
    ]
    order_events = [
        event
        for event in _read_jsonl("order-events.jsonl")
        if str(event.get("created_at", "")).startswith(target_date)
    ]
    provider_counts: dict[str, int] = {}
    strategy_counts: dict[str, dict[str, int]] = {}
    candidate_count = 0
    approved_count = 0
    rejected_count = 0
    pdt_rejected_count = 0
    spread_rejected_count = 0
    submitted_orders = 0

    for event in pipeline_runs:
        payload = event.get("payload") or {}
        candidate = payload.get("candidate")
        risk_decision = payload.get("risk_decision")
        scored_candidate = payload.get("scored_candidate") or {}
        broker_receipt = payload.get("broker_receipt")
        if candidate:
            candidate_count += 1
            strategy_id = str(candidate.get("strategy_id") or "unknown")
            strategy_counts.setdefault(
                strategy_id,
                {"candidates": 0, "approved": 0, "submitted": 0},
            )
            strategy_counts[strategy_id]["candidates"] += 1

        ai_score = (scored_candidate.get("ai_score") or {}) if scored_candidate else {}
        provider = _provider_tier(ai_score)
        if provider != "none":
            provider_counts[provider] = provider_counts.get(provider, 0) + 1

        if risk_decision:
            state = str(risk_decision.get("state") or "")
            if state == "approved":
                approved_count += 1
                if candidate:
                    strategy_counts[str(candidate.get("strategy_id"))]["approved"] += 1
            elif state == "rejected":
                rejected_count += 1
                reasons = [
                    str(reason)
                    for reason in risk_decision.get("reasons", [])
                ]
                if any("PDT count" in reason for reason in reasons):
                    pdt_rejected_count += 1
                if any("spread" in reason.lower() for reason in reasons):
                    spread_rejected_count += 1

        if broker_receipt:
            submitted_orders += 1
            if candidate:
                strategy_counts[str(candidate.get("strategy_id"))]["submitted"] += 1

    portfolio_values = [
        float((event.get("payload") or {}).get("account", {}).get("portfolio_value"))
        for event in portfolio_snapshots
        if (event.get("payload") or {}).get("account", {}).get("portfolio_value") is not None
    ]
    starting_value = portfolio_values[0] if portfolio_values else None
    ending_value = portfolio_values[-1] if portfolio_values else None
    portfolio_delta = (
        round(ending_value - starting_value, 4)
        if starting_value is not None and ending_value is not None
        else None
    )

    provider_usage = [
        ProviderUsageSummary(provider=provider, count=count)
        for provider, count in sorted(provider_counts.items())
    ]
    strategy_usage = [
        StrategyUsageSummary(strategy_id=strategy_id, **counts)
        for strategy_id, counts in sorted(strategy_counts.items())
    ]
    notes = [
        "Recap is built from local JSONL audit data.",
        "Portfolio delta uses reconciliation snapshots and should be checked against Alpaca before making decisions.",
    ]
    if order_events and not submitted_orders:
        notes.append("Order snapshots exist today, but no new pipeline submission was recorded.")

    return DailyTradeRecap(
        date=target_date,
        starting_portfolio_value=starting_value,
        ending_portfolio_value=ending_value,
        portfolio_delta=portfolio_delta,
        pipeline_runs=len(pipeline_runs),
        candidate_count=candidate_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        pdt_rejected_count=pdt_rejected_count,
        spread_rejected_count=spread_rejected_count,
        submitted_orders=submitted_orders,
        provider_usage=provider_usage,
        strategy_usage=strategy_usage,
        notes=notes,
    )


def _provider_tier(ai_score: dict[str, Any]) -> str:
    """Return a stable scorer tier for recap aggregation."""

    provenance = str(ai_score.get("score_provenance") or "").lower()
    if provenance in {"anthropic", "openai", "local"}:
        return provenance

    model_name = str(ai_score.get("model_name") or "none").lower()
    if model_name.startswith("local-manual"):
        return "local"
    if "claude" in model_name or "anthropic" in model_name:
        return "anthropic"
    if "gpt" in model_name or "openai" in model_name:
        return "openai"
    return model_name
