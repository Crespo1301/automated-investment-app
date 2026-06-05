from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
import requests.exceptions
import urllib3.exceptions

from app.core.config import settings
from app.services.audit_store import _tail_jsonl, _tail_jsonl_for_date
from app.services.autopilot import _is_transient_network_error


@pytest.fixture(autouse=True)
def isolate_runtime_data_dir(tmp_path):
    original_runtime_data_dir = settings.runtime_data_dir
    settings.runtime_data_dir = str(tmp_path)
    yield
    settings.runtime_data_dir = original_runtime_data_dir


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_tail_jsonl_returns_only_recent_rows() -> None:
    rows = [
        {"created_at": "2026-05-18T13:00:00+00:00", "payload": {"index": 1}},
        {"created_at": "2026-05-18T14:00:00+00:00", "payload": {"index": 2}},
        {"created_at": "2026-05-18T15:00:00+00:00", "payload": {"index": 3}},
        {"created_at": "2026-05-18T16:00:00+00:00", "payload": {"index": 4}},
    ]
    _write_jsonl(Path(settings.runtime_data_dir) / "order-events.jsonl", rows)

    tail = _tail_jsonl("order-events.jsonl", 2)

    assert [row["payload"]["index"] for row in tail] == [3, 4]


def test_tail_jsonl_for_date_returns_only_requested_utc_day() -> None:
    rows = [
        {"created_at": "2026-05-18T23:55:00+00:00", "payload": {"index": 1}},
        {"created_at": "2026-05-19T09:30:00+00:00", "payload": {"index": 2}},
        {"created_at": "2026-05-19T15:45:00+00:00", "payload": {"index": 3}},
        {"created_at": "2026-05-20T09:30:00+00:00", "payload": {"index": 4}},
    ]
    _write_jsonl(Path(settings.runtime_data_dir) / "pipeline-runs.jsonl", rows)

    matching_rows = _tail_jsonl_for_date("pipeline-runs.jsonl", "2026-05-19")

    assert [row["payload"]["index"] for row in matching_rows] == [2, 3]


def test_transient_network_error_classifier_is_narrowed_to_retryable_cases() -> None:
    assert _is_transient_network_error(requests.exceptions.ConnectionError("offline")) is True
    assert _is_transient_network_error(requests.exceptions.Timeout("slow")) is True
    assert _is_transient_network_error(urllib3.exceptions.ProtocolError("conn", OSError("reset"))) is True
    assert _is_transient_network_error(urllib3.exceptions.ReadTimeoutError(None, None, "timed out")) is True
    assert _is_transient_network_error(socket.gaierror("dns")) is True

    assert _is_transient_network_error(urllib3.exceptions.HTTPError("generic http failure")) is False



def test_loop_self_heals_through_transient_outage(monkeypatch) -> None:
    """A transient network outage must NOT trip the kill switch or exit.

    The loop should ride the blips (backing off) and resume, so exit
    protection survives an overnight host-sleep without a manual restart.
    """

    import app.services.autopilot as autopilot
    from app.services.audit_store import get_safety_state, set_autopilot

    set_autopilot(True, reason="test arm", last_action="armed")
    disabled_state = autopilot.get_autopilot_state().model_copy(update={"enabled": False})

    calls = {"n": 0}

    def fake_once():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise requests.exceptions.ConnectionError("offline")
        return disabled_state

    monkeypatch.setattr(autopilot, "run_autopilot_once", fake_once)
    monkeypatch.setattr(autopilot.time, "sleep", lambda *_: None)
    monkeypatch.setattr(autopilot.signal, "alarm", lambda *_: 0)

    autopilot.run_autopilot_loop()

    assert calls["n"] == 3  # rode 2 blips, then a clean (disabled) tick ended it
    assert get_safety_state().kill_switch_enabled is False  # outage never latched the kill switch


def test_loop_fails_safe_on_genuine_fault(monkeypatch) -> None:
    """A non-network fault must still trip the kill switch and disarm."""

    import app.services.autopilot as autopilot
    from app.services.audit_store import get_safety_state, set_autopilot

    set_autopilot(True, reason="test arm", last_action="armed")

    def fake_once():
        raise ValueError("genuine logic fault")

    monkeypatch.setattr(autopilot, "run_autopilot_once", fake_once)
    monkeypatch.setattr(autopilot.time, "sleep", lambda *_: None)
    monkeypatch.setattr(autopilot.signal, "alarm", lambda *_: 0)

    with pytest.raises(ValueError):
        autopilot.run_autopilot_loop()

    assert get_safety_state().kill_switch_enabled is True
    assert autopilot.get_autopilot_state().enabled is False
