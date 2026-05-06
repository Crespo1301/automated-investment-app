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
    MarketClockStatus,
    PipelineRunResult,
    SafetyState,
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
        )

    state = AutopilotState.model_validate_json(path.read_text(encoding="utf-8"))
    if state.interval_seconds <= 0:
        state.interval_seconds = settings.autopilot_interval_seconds
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
        interval_seconds=previous.interval_seconds,
        market_open_only=previous.market_open_only,
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
