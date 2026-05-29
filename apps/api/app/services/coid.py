"""Deterministic client_order_id generation.

A coid is a stable identifier for an *intent* (date + lane + symbol + a
short discriminator). Reusing the same intent inputs MUST produce the
same coid — this prevents accidental duplicate submissions when a script
or autopilot tick is replayed and lets the broker enforce idempotency
on its end.

Format: ``{yyyymmdd}-{lane}-{symbol}-{short_id}``

  * yyyymmdd uses UTC date of the intent.
  * lane is the strategy/source name, lowercased and stripped of
    characters Alpaca rejects (it accepts ``[A-Za-z0-9.\\-_]`` up to
    128 chars).
  * symbol is the ticker uppercased.
  * short_id is the first 8 chars of a hash over a caller-provided
    discriminator (candidate_id, etc.).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, UTC

_ALLOWED = re.compile(r"[^A-Za-z0-9._\-]")


def sanitize_coid_part(part: str) -> str:
    """Strip characters Alpaca rejects from one coid segment."""

    return _ALLOWED.sub("_", part)[:40]


# Backwards-compatible private alias retained for v1.0; new callers
# should use the public ``sanitize_coid_part``.
_sanitize = sanitize_coid_part


def coid_prefix_for(lane: str, intent_date: datetime | None = None) -> str:
    """Return the leading ``{yyyymmdd}-{lane}-`` slice of a coid.

    Use this for broker-side duplicate-order detection so callers do
    not have to reimplement the format. Replay on the same UTC day
    produces the same prefix; cross-day replay correctly does not.
    """

    date = (intent_date or datetime.now(UTC)).strftime("%Y%m%d")
    return f"{date}-{sanitize_coid_part(lane).lower()}-"


def make_coid(
    *,
    lane: str,
    symbol: str,
    discriminator: str,
    intent_date: datetime | None = None,
) -> str:
    """Build a deterministic client_order_id.

    Same inputs ALWAYS return the same string. Use this everywhere we
    mint a coid so replay is safe and the audit trail stays parseable.
    """

    short = hashlib.sha1(discriminator.encode("utf-8")).hexdigest()[:8]
    return f"{coid_prefix_for(lane, intent_date)}{symbol.upper()}-{short}"
