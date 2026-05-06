"""Supervised local automation loop for attended-to-unattended progression."""

from __future__ import annotations

import time

from app.core.config import settings
from app.domain.trading import AutopilotState, PipelineRunResult
from app.services.audit_store import (
    get_autopilot_state,
    get_safety_state,
    record_autopilot_heartbeat,
    set_autopilot,
    set_kill_switch,
)
from app.services.broker_adapter import get_active_alpaca_broker
from app.services.local_worker import run_single_cycle


def enable_autopilot(reason: str = "Operator enabled autopilot.") -> AutopilotState:
    """Arm the local autopilot state.

    This does not start a process by itself. The operator must also run the
    autopilot loop command locally.
    """

    return set_autopilot(True, reason=reason, last_action="armed")


def disable_autopilot(reason: str = "Operator disabled autopilot.") -> AutopilotState:
    """Disarm the local autopilot state."""

    return set_autopilot(False, reason=reason, last_action="disarmed")


def run_autopilot_once() -> AutopilotState:
    """Run one supervised automation tick without hiding safety failures."""

    state = get_autopilot_state()
    if not state.enabled:
        return record_autopilot_heartbeat("disabled")

    safety = get_safety_state()
    if safety.kill_switch_enabled:
        return record_autopilot_heartbeat("blocked_by_kill_switch")

    if settings.trading_mode != "live" or not settings.allow_live_trading:
        reason = "Autopilot requires live trading mode and explicit live permission."
        set_kill_switch(True, reason=reason)
        return set_autopilot(False, reason=reason, last_action="disabled_by_config_error", last_error=reason)

    broker = get_active_alpaca_broker()
    clock = broker.get_market_clock()
    if state.market_open_only and not clock.is_open:
        next_open = clock.next_open.isoformat() if clock.next_open else "unknown"
        return record_autopilot_heartbeat(f"waiting_for_market_open:{next_open}")

    if not settings.autopilot_allow_entries:
        return record_autopilot_heartbeat(
            "entry_execution_locked: set INVESTMENT_APP_AUTOPILOT_ALLOW_ENTRIES=true after exit protection is ready"
        )

    result: PipelineRunResult = run_single_cycle()
    if result.risk_decision is None:
        return record_autopilot_heartbeat("no_candidate")

    if result.risk_decision.state == "rejected":
        return record_autopilot_heartbeat(
            "risk_rejected:" + "; ".join(result.risk_decision.reasons)
        )

    if result.broker_receipt is None:
        return record_autopilot_heartbeat("approved_without_broker_receipt")

    return record_autopilot_heartbeat(
        f"submitted:{result.broker_receipt.symbol}:{result.broker_receipt.status}"
    )


def run_autopilot_loop(max_ticks: int | None = None) -> None:
    """Run the local autopilot loop until disabled, interrupted, or max_ticks."""

    ticks = 0
    while True:
        try:
            state = run_autopilot_once()
        except Exception as exc:
            reason = f"Autopilot error: {exc.__class__.__name__}."
            set_kill_switch(True, reason=reason)
            set_autopilot(False, reason=reason, last_action="disabled_by_error", last_error=str(exc))
            raise

        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            return

        if not state.enabled:
            return

        time.sleep(max(30, state.interval_seconds))
