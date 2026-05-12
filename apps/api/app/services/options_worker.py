"""Options cycle worker — Level 1 (covered call + cash-secured put).

Runs per autopilot tick when ``settings.options_enabled`` is true. Iterates
the approved options universe, asks each lane for a candidate, gates each
candidate through ``OptionsRiskGate``, optionally submits via the broker,
and persists everything for the dashboard.

This is intentionally conservative:
- Submission only happens when ``settings.autopilot_allow_entries`` is true
  AND ``settings.options_enabled`` is true AND the broker is live.
- Per-tick chain fetches are capped to ``MAX_CHAINS_PER_TICK`` to keep
  Alpaca data quota in check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import configured_options_underlyings, settings
from app.domain.trading import (
    AuditEvent,
    BrokerOrderReceipt,
    OptionsRiskDecision,
    OptionsTradeCandidate,
    new_id,
)
from app.services.audit_store import _append_jsonl, get_safety_state
from app.services.broker_adapter import AlpacaBroker
from app.services.options_risk import OptionsRiskGate, options_limits_from_settings
from app.services.options_strategy import (
    CashSecuredPutStrategy,
    CoveredCallStrategy,
)


MAX_CHAINS_PER_TICK = 4


@dataclass
class OptionsCycleRecord:
    underlying: str
    candidate: OptionsTradeCandidate | None
    decision: OptionsRiskDecision | None
    receipt: BrokerOrderReceipt | None
    note: str | None = None


def run_options_cycle(
    broker: AlpacaBroker,
    *,
    execute: bool,
) -> list[OptionsCycleRecord]:
    """Run one options pass across the approved underlyings."""

    if not settings.options_enabled:
        return []

    limits = options_limits_from_settings()
    if not limits.enabled or not limits.allowed_underlyings:
        return []

    safety = get_safety_state()
    gate = OptionsRiskGate(limits, kill_switch_enabled=safety.kill_switch_enabled)
    account = broker.get_account_status()
    positions = broker.list_positions()
    trading_mode = "live" if settings.trading_mode == "live" else "paper"

    csp_lane = CashSecuredPutStrategy()
    cc_lane = CoveredCallStrategy()
    held_symbols = {p.symbol.upper() for p in positions if p.quantity >= 100}

    # Prioritize chains for symbols we already own (covered call eligible)
    # then fall back to the CSP universe. Cap per tick.
    universe = list(dict.fromkeys(
        [sym for sym in limits.allowed_underlyings if sym.upper() in held_symbols]
        + list(limits.allowed_underlyings)
    ))[:MAX_CHAINS_PER_TICK]

    records: list[OptionsCycleRecord] = []
    for underlying in universe:
        try:
            chain = broker.get_option_chain(
                underlying,
                dte_min=limits.target_dte_min,
                dte_max=limits.target_dte_max,
            )
        except Exception as exc:
            records.append(
                OptionsCycleRecord(
                    underlying=underlying,
                    candidate=None,
                    decision=None,
                    receipt=None,
                    note=f"chain_fetch_failed:{exc.__class__.__name__}",
                )
            )
            continue

        correlation_id = new_id("optcycle")
        candidate: OptionsTradeCandidate | None = None

        if underlying.upper() in held_symbols:
            held = next(p for p in positions if p.symbol.upper() == underlying.upper())
            candidate = cc_lane.evaluate_for_position(
                held, chain, limits, correlation_id
            )

        if candidate is None:
            candidate = csp_lane.evaluate_for_underlying(
                chain, account, limits, correlation_id
            )

        if candidate is None:
            records.append(
                OptionsCycleRecord(
                    underlying=underlying,
                    candidate=None,
                    decision=None,
                    receipt=None,
                    note="no_candidate",
                )
            )
            continue

        decision, intent = gate.evaluate(
            candidate, account, positions, trading_mode=trading_mode
        )

        receipt: BrokerOrderReceipt | None = None
        note: str | None = None
        if decision.state == "approved" and intent is not None:
            if execute and settings.allow_live_trading:
                try:
                    receipt = broker.submit_options_order(intent)
                except Exception as exc:
                    note = f"submit_failed:{exc.__class__.__name__}:{exc}"
            else:
                note = "approved_dry_run"

        record = OptionsCycleRecord(
            underlying=underlying,
            candidate=candidate,
            decision=decision,
            receipt=receipt,
            note=note,
        )
        records.append(record)
        _persist_record(record)

    return records


def _persist_record(record: OptionsCycleRecord) -> None:
    """Append a single options-cycle record to the audit log."""

    payload: dict[str, Any] = {
        "underlying": record.underlying,
        "note": record.note,
        "candidate": record.candidate.model_dump(mode="json") if record.candidate else None,
        "decision": record.decision.model_dump(mode="json") if record.decision else None,
        "receipt": record.receipt.model_dump(mode="json") if record.receipt else None,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    _append_jsonl(
        "options-events.jsonl",
        AuditEvent(event_type="options_cycle", payload=payload),
    )


def recent_options_records(limit: int = 25) -> list[dict[str, Any]]:
    """Read recent options-cycle records for the dashboard."""

    from app.services.audit_store import _read_jsonl

    rows = _read_jsonl("options-events.jsonl")
    return rows[-limit:][::-1]
