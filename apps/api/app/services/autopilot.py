"""Supervised local automation loop for attended-to-unattended progression."""

from __future__ import annotations

import signal
import socket
import time

import requests.exceptions
import urllib3.exceptions

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
from app.services.exit_monitor import run_exit_check
from app.services.local_worker import run_single_cycle
from app.services.options_worker import run_options_cycle


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

    exit_result = run_exit_check(broker, execute=settings.autopilot_allow_exits)
    if exit_result.submitted_receipts:
        symbols = ",".join(receipt.symbol for receipt in exit_result.submitted_receipts)
        return record_autopilot_heartbeat(f"exit_submitted:{symbols}")
    if exit_result.signals:
        blocking_signals = [
            signal for signal in exit_result.signals if signal.reason != "small_win"
        ]
        if blocking_signals:
            symbols = ",".join(f"{signal.symbol}:{signal.reason}" for signal in blocking_signals)
            return record_autopilot_heartbeat(f"exit_signal_locked:{symbols}")

    if settings.options_enabled:
        try:
            options_records = run_options_cycle(
                broker,
                execute=settings.autopilot_allow_entries,
            )
        except Exception as exc:
            record_autopilot_heartbeat(
                f"options_cycle_error:{exc.__class__.__name__}"
            )
            options_records = []

        submitted = [r for r in options_records if r.receipt is not None]
        if submitted:
            symbols = ",".join(r.underlying for r in submitted)
            return record_autopilot_heartbeat(f"options_submitted:{symbols}")
        approved = [r for r in options_records if r.decision and r.decision.state == "approved"]
        if approved:
            symbols = ",".join(r.underlying for r in approved)
            record_autopilot_heartbeat(f"options_approved_no_submit:{symbols}")

    if not settings.autopilot_allow_entries:
        return record_autopilot_heartbeat(
            "entry_execution_locked: set INVESTMENT_APP_AUTOPILOT_ALLOW_ENTRIES=true after exit protection is ready"
        )

    result: PipelineRunResult = run_single_cycle()
    if result.risk_decision is None:
        if result.event.source == "portfolio-guard":
            return record_autopilot_heartbeat(
                f"exit_checked_entry_skipped:buying_power_below_${settings.minimum_order_notional:.2f}_minimum"
            )
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


# Hard wall-clock bound on a single tick. The Alpaca SDK calls carry no
# guaranteed request timeout, so on spotty internet (or when the host wakes
# from sleep) a tick can block indefinitely — the heartbeat then silently
# stops (a "freeze") even though the process is still alive. Every tick runs
# under this budget so a hang surfaces as a transient timeout the loop rides
# through, instead of freezing forever.
_AUTOPILOT_TICK_TIMEOUT_SECONDS = 25

# Defense-in-depth: bound any blocking socket op in this process so a hung
# connection cannot outlive the tick budget even if SIGALRM is unavailable.
_SOCKET_DEFAULT_TIMEOUT_SECONDS = 20

# Capped backoff between retries while a transient network outage persists.
# The loop NEVER gives up on a network blip — it just slows its polling and
# resumes the moment connectivity returns.
_TRANSIENT_BACKOFF_MIN_SECONDS = 30
_TRANSIENT_BACKOFF_MAX_SECONDS = 120


class _TickTimeout(TimeoutError):
    """Raised when a single autopilot tick exceeds its wall-clock budget.

    Subclasses ``TimeoutError`` so it is classified as a transient network
    fault and rides through the self-healing retry path.
    """


def _install_tick_timeout_handler() -> bool:
    """Install a SIGALRM handler that aborts a hung tick. Returns availability.

    SIGALRM only works on the process main thread on Unix. When it is not
    available (non-main thread or non-Unix), the loop falls back to the
    process-wide socket timeout alone.
    """

    def _handler(signum: int, frame: object) -> None:  # noqa: ANN001
        raise _TickTimeout(
            f"autopilot tick exceeded {_AUTOPILOT_TICK_TIMEOUT_SECONDS}s wall-clock budget"
        )

    try:
        signal.signal(signal.SIGALRM, _handler)
        return True
    except (ValueError, AttributeError, OSError):
        return False


# requests wraps urllib3 connection/DNS/timeout failures in these types; the
# builtin and socket entries cover any non-requests network path. Broker
# APIError and requests HTTPError (genuine non-2xx responses) are deliberately
# excluded — those are real faults and must still trip the fail-safe.
_TRANSIENT_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    urllib3.exceptions.ProtocolError,
    urllib3.exceptions.ConnectTimeoutError,
    urllib3.exceptions.ReadTimeoutError,
    urllib3.exceptions.NameResolutionError,
    urllib3.exceptions.NewConnectionError,
    ConnectionError,
    TimeoutError,
    socket.gaierror,
)


def _is_transient_network_error(exc: BaseException) -> bool:
    """Return True if exc, or any error in its cause chain, is a network blip.

    Every non-network exception stays non-transient so the kill-switch
    fail-safe keeps firing on genuine trading, risk, or logic faults.
    """

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _TRANSIENT_NETWORK_ERRORS):
            return True
        current = current.__cause__ or current.__context__
    return False


def run_autopilot_loop(max_ticks: int | None = None) -> None:
    """Run the local autopilot loop until disabled, interrupted, or max_ticks.

    Reliability semantics (v2.0):

    - **Every tick is wall-clock bounded** (SIGALRM + a process-wide socket
      timeout) so a hung SDK call surfaces as a transient timeout instead of
      silently freezing the heartbeat.
    - **Transient network faults self-heal.** A blip, hang, or sustained
      outage (e.g. the host sleeping overnight) is NOT a trading fault: the
      loop never trips the kill switch and never exits on it. It backs off with
      a cap and keeps polling, so it resumes on its own the moment connectivity
      returns — no manual premarket restart, no latched kill switch to clear.
    - **Genuine faults still fail safe.** Any non-network exception trips the
      kill switch, disarms autopilot, and exits.
    - **Operator disable is honored even mid-outage** via a cheap local read,
      so the loop still stops promptly when disarmed.
    """

    socket.setdefaulttimeout(_SOCKET_DEFAULT_TIMEOUT_SECONDS)
    alarm_available = _install_tick_timeout_handler()

    ticks = 0
    transient_failures = 0
    while True:
        # Respect an operator disable even during a network outage. This is a
        # local file read with no network, so it never hangs or fails the loop.
        try:
            if not get_autopilot_state().enabled:
                return
        except Exception:
            pass

        try:
            if alarm_available:
                signal.alarm(_AUTOPILOT_TICK_TIMEOUT_SECONDS)
            try:
                state = run_autopilot_once()
            finally:
                if alarm_available:
                    signal.alarm(0)
            transient_failures = 0
        except Exception as exc:
            if _is_transient_network_error(exc):
                # Self-heal: ride the outage indefinitely. Surface the retry
                # state on the heartbeat so the dashboard never looks silently
                # healthy or silently dead, then back off and try again.
                transient_failures += 1
                try:
                    record_autopilot_heartbeat(
                        f"transient_network_retry:{transient_failures}:{exc.__class__.__name__}"
                    )
                except Exception:
                    pass
                backoff = min(
                    _TRANSIENT_BACKOFF_MAX_SECONDS,
                    _TRANSIENT_BACKOFF_MIN_SECONDS * min(transient_failures, 4),
                )
                time.sleep(backoff)
                continue

            # Genuine trading/risk/logic fault: fail safe.
            reason = f"Autopilot error: {exc.__class__.__name__}."
            set_kill_switch(True, reason=reason)
            set_autopilot(
                False,
                reason=reason,
                last_action="disabled_by_error",
                last_error=str(exc),
            )
            raise

        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            return

        if not state.enabled:
            return

        time.sleep(max(30, state.interval_seconds))
