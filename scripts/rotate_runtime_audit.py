#!/usr/bin/env python3
"""Rotate runtime JSONL audit logs in apps/api/.runtime/.

Splits each file by UTC calendar date:
- Events older than KEEP_DAYS days are gzipped into
  apps/api/.runtime/archive/{basename}.YYYY-MM-DD.jsonl.gz (one per day).
- Events in the last KEEP_DAYS calendar days (inclusive of TODAY) stay
  in the live file.

The audit_store.py code uses bounded tail readers (CHANGELOG 2026-05-19),
so head-trimming is safe. Every event is preserved -- nothing is deleted.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "apps" / "api" / ".runtime"
ARCHIVE = RUNTIME / "archive"

# Live window: 2026-05-22 .. 2026-05-28 inclusive (7 calendar days ending today)
TODAY = date(2026, 5, 28)
KEEP_DAYS = 7
CUTOFF = TODAY - timedelta(days=KEEP_DAYS - 1)  # = 2026-05-22

FILES = [
    "order-events.jsonl",
    "portfolio-snapshots.jsonl",
    "pipeline-runs.jsonl",
    "autopilot-events.jsonl",
]


def event_date(line: str) -> date | None:
    """Extract created_at UTC date from a JSON line. Returns None on parse failure."""
    try:
        obj = json.loads(line)
    except Exception:
        return None
    ts = obj.get("created_at")
    if not ts:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def rotate(name: str) -> dict:
    src = RUNTIME / name
    if not src.exists():
        return {"file": name, "skipped": True}

    ARCHIVE.mkdir(parents=True, exist_ok=True)

    # buckets: date -> list[bytes], plus "live" list and an "undated" list (kept live).
    buckets: dict[date, list[bytes]] = {}
    live: list[bytes] = []
    undated: list[bytes] = []
    total = 0
    parsed = 0
    archived = 0
    kept = 0

    with src.open("rb") as fh:
        for raw in fh:
            total += 1
            if not raw.strip():
                continue
            try:
                d = event_date(raw.decode("utf-8", errors="replace"))
            except Exception:
                d = None
            if d is None:
                # Keep undated/unparseable lines in the live file to avoid silent loss.
                undated.append(raw)
                kept += 1
                continue
            parsed += 1
            if d < CUTOFF:
                buckets.setdefault(d, []).append(raw)
                archived += 1
            else:
                live.append(raw)
                kept += 1

    # Write per-day gzipped archives (append-safe: if archive already exists, append).
    written_archives = []
    for d in sorted(buckets):
        archive_path = ARCHIVE / f"{src.stem}.{d.isoformat()}.jsonl.gz"
        mode = "ab" if archive_path.exists() else "wb"
        with gzip.open(archive_path, mode) as gz:
            for raw in buckets[d]:
                gz.write(raw)
        written_archives.append((archive_path.name, len(buckets[d])))

    # Atomic rewrite of live file: write to tmp, fsync, rename.
    tmp = src.with_suffix(src.suffix + ".rotating.tmp")
    with tmp.open("wb") as fh:
        # Preserve original ordering: undated lines first (rare; only parse failures)
        # then live lines in their original sequence.
        for raw in undated:
            fh.write(raw)
        for raw in live:
            fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(src)
    # Audit data should not be world-readable; tighten in case the
    # default umask left them at 644.
    os.chmod(src, 0o600)

    return {
        "file": name,
        "total_lines": total,
        "parsed": parsed,
        "archived": archived,
        "kept": kept,
        "archives": written_archives,
    }


def main() -> int:
    if not RUNTIME.exists():
        print(f"Runtime dir missing: {RUNTIME}", file=sys.stderr)
        return 1
    print(f"Cutoff (inclusive live start): {CUTOFF.isoformat()}  TODAY: {TODAY.isoformat()}")
    print(f"Archive dir: {ARCHIVE}")
    results = []
    for name in FILES:
        res = rotate(name)
        results.append(res)
        if res.get("skipped"):
            print(f"  SKIP {name} (missing)")
            continue
        print(
            f"  {name}: total={res['total_lines']} parsed={res['parsed']} "
            f"archived={res['archived']} kept={res['kept']} "
            f"archives={len(res['archives'])}"
        )
        for arc_name, count in res["archives"]:
            print(f"     -> {arc_name}: {count} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
