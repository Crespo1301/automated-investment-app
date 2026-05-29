"""Tests for ``app.services.coid.make_coid``.

Idempotent client_order_id behavior is load-bearing for replay safety,
so these tests pin determinism, sensitivity, sanitization, and length.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.coid import make_coid

# Alpaca accepts [A-Za-z0-9.\-_] up to 128 chars in client_order_id.
_ALPACA_VALID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


def test_make_coid_is_deterministic() -> None:
    """Same inputs MUST always produce the same coid (replay safety)."""

    fixed = datetime(2026, 5, 28, 14, 30, tzinfo=timezone.utc)
    a = make_coid(
        lane="micro_breakout_v1",
        symbol="SPY",
        discriminator="cand_abc123",
        intent_date=fixed,
    )
    b = make_coid(
        lane="micro_breakout_v1",
        symbol="SPY",
        discriminator="cand_abc123",
        intent_date=fixed,
    )
    assert a == b
    # Sanity: format should embed inputs literally.
    assert a == "20260528-micro_breakout_v1-SPY-2de0547f"


def test_make_coid_varies_by_date() -> None:
    """Different date inputs MUST yield distinct coids."""

    day_a = datetime(2026, 5, 28, tzinfo=timezone.utc)
    day_b = datetime(2026, 5, 29, tzinfo=timezone.utc)

    a = make_coid(
        lane="momentum_v1",
        symbol="AAPL",
        discriminator="cand_xyz",
        intent_date=day_a,
    )
    b = make_coid(
        lane="momentum_v1",
        symbol="AAPL",
        discriminator="cand_xyz",
        intent_date=day_b,
    )
    assert a != b
    assert a.startswith("20260528-")
    assert b.startswith("20260529-")


def test_make_coid_varies_by_discriminator() -> None:
    """Different discriminator inputs MUST yield distinct coids."""

    fixed = datetime(2026, 5, 28, tzinfo=timezone.utc)
    a = make_coid(
        lane="orb_v1",
        symbol="QQQ",
        discriminator="cand_1",
        intent_date=fixed,
    )
    b = make_coid(
        lane="orb_v1",
        symbol="QQQ",
        discriminator="cand_2",
        intent_date=fixed,
    )
    assert a != b


def test_make_coid_sanitizes_illegal_lane_chars() -> None:
    """Lane characters Alpaca rejects MUST be replaced, not passed through."""

    fixed = datetime(2026, 5, 28, tzinfo=timezone.utc)
    coid = make_coid(
        lane="weird lane/with:bad*chars!",
        symbol="MSFT",
        discriminator="cand_x",
        intent_date=fixed,
    )
    # Must still be Alpaca-legal end to end.
    assert _ALPACA_VALID.match(coid), f"coid contains illegal chars: {coid}"
    # Spaces and punctuation should have collapsed into underscores.
    assert " " not in coid
    assert "/" not in coid
    assert ":" not in coid
    assert "*" not in coid
    assert "!" not in coid


def test_make_coid_uppercases_symbol() -> None:
    """Symbol should be normalized to uppercase regardless of input casing."""

    fixed = datetime(2026, 5, 28, tzinfo=timezone.utc)
    coid = make_coid(
        lane="micro_breakout_v1",
        symbol="spy",
        discriminator="cand_x",
        intent_date=fixed,
    )
    assert "-SPY-" in coid


def test_make_coid_length_under_alpaca_cap() -> None:
    """coid MUST stay under Alpaca's 128-character ceiling even with long inputs."""

    fixed = datetime(2026, 5, 28, tzinfo=timezone.utc)
    coid = make_coid(
        lane="x" * 200,
        symbol="VTIVTIVTIVTI",
        discriminator="cand_" + ("y" * 200),
        intent_date=fixed,
    )
    assert len(coid) <= 128, f"coid too long ({len(coid)} chars): {coid}"
    assert _ALPACA_VALID.match(coid), f"coid contains illegal chars: {coid}"


def test_make_coid_default_date_uses_utc_now() -> None:
    """Omitting intent_date should still produce a valid, dated coid."""

    coid = make_coid(
        lane="micro_breakout_v1",
        symbol="SPY",
        discriminator="cand_now",
    )
    # First 8 chars are the date stamp; just sanity-check shape.
    assert re.match(r"^\d{8}-", coid)
    assert _ALPACA_VALID.match(coid)
