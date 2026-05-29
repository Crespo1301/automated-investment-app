#!/usr/bin/env python3
"""Per-lane edge analysis for the automated-investment-app.

Reads filled BUY/SELL broker_order_snapshot events from
apps/api/.runtime/order-events.jsonl plus any rotated archives in
apps/api/.runtime/archive/order-events.*.jsonl.gz.

Round-trips are built with FIFO lot matching per symbol: each SELL is
consumed against the oldest open BUY lots for that symbol. One BUY lot
may contribute to multiple SELL round-trips. Each round-trip is
attributed to the originating lane via the BUY's client_order_id prefix.

Open lots at end-of-data are reported with unrealized P&L sourced from
the latest portfolio-snapshots.jsonl entry (current_price * quantity vs
cost basis).

Writes a markdown report to docs/v1-lane-analysis.md.
"""
from __future__ import annotations

import gzip
import json
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "apps" / "api" / ".runtime"
ARCHIVE = RUNTIME / "archive"
OUT = ROOT / "docs" / "v1-lane-analysis.md"


def iter_order_event_files() -> list[Path]:
    files = sorted(ARCHIVE.glob("order-events.*.jsonl.gz"))
    live = RUNTIME / "order-events.jsonl"
    if live.exists():
        files.append(live)
    return files


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def lane_of(client_order_id: str | None) -> str:
    if not client_order_id:
        return "unknown"
    cid = client_order_id
    KNOWN_LANES = (
        "opening_range_breakout_v1",
        "micro_breakout_v1",
        "vwap_reclaim_v1",
        "pullback_continuation_v1",
        "relative_volume_spike_v1",
    )
    for lane in KNOWN_LANES:
        if cid.startswith(lane):
            return lane
    if cid.startswith("manual_"):
        # Collapse all manual_exit_xxx and manual_buy_xxx and manual_trim_xxx into
        # a single "manual_*" lane for high-level analysis.
        if cid.startswith("manual_exit_"):
            return "manual_exit"
        if cid.startswith("manual_buy_"):
            return "manual_buy"
        if cid.startswith("manual_trim_"):
            return "manual_trim"
        return "manual_other"
    return "unknown"


@dataclass
class Fill:
    broker_order_id: str
    client_order_id: str | None
    lane: str
    symbol: str
    side: str  # "buy" / "sell"
    qty: float
    price: float
    filled_at: datetime | None
    submitted_at: datetime | None


@dataclass
class Lot:
    """An open BUY lot waiting to be matched against SELLs (FIFO)."""
    fill: Fill
    qty_remaining: float


@dataclass
class RoundTrip:
    lane: str  # lane of the BUY
    symbol: str
    qty: float
    buy_price: float
    sell_price: float
    buy_at: datetime | None
    sell_at: datetime | None
    sell_lane: str

    @property
    def cost(self) -> float:
        return self.qty * self.buy_price

    @property
    def proceeds(self) -> float:
        return self.qty * self.sell_price

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost

    @property
    def pnl_pct(self) -> float:
        if self.cost <= 0:
            return 0.0
        return (self.pnl / self.cost) * 100.0

    @property
    def hold_minutes(self) -> float | None:
        if self.buy_at and self.sell_at:
            return (self.sell_at - self.buy_at).total_seconds() / 60.0
        return None


def collect_fills() -> list[Fill]:
    """Deduplicate filled BUY/SELL snapshots by broker_order_id (one fill per order)."""
    seen: dict[str, Fill] = {}
    for path in iter_order_event_files():
        with open_text(path) as fh:
            for raw in fh:
                try:
                    e = json.loads(raw)
                except Exception:
                    continue
                if e.get("event_type") != "broker_order_snapshot":
                    continue
                p = e.get("payload") or {}
                status = p.get("status") or ""
                if "FILLED" not in status:
                    continue
                qty = p.get("filled_quantity") or 0
                price = p.get("filled_average_price")
                if not qty or price is None:
                    continue
                oid = p.get("broker_order_id")
                if not oid:
                    continue
                side_raw = (p.get("side") or "").upper()
                if "BUY" in side_raw:
                    side = "buy"
                elif "SELL" in side_raw:
                    side = "sell"
                else:
                    continue
                cid = p.get("client_order_id")
                fill = Fill(
                    broker_order_id=oid,
                    client_order_id=cid,
                    lane=lane_of(cid),
                    symbol=(p.get("symbol") or "").upper(),
                    side=side,
                    qty=float(qty),
                    price=float(price),
                    filled_at=parse_ts(p.get("filled_at") or ""),
                    submitted_at=parse_ts(p.get("submitted_at") or ""),
                )
                # On duplicate snapshots, keep the one with a real filled_at if available.
                prev = seen.get(oid)
                if prev is None:
                    seen[oid] = fill
                else:
                    if prev.filled_at is None and fill.filled_at is not None:
                        seen[oid] = fill
    fills = list(seen.values())
    # Sort by best available timestamp for FIFO matching.
    fills.sort(key=lambda f: (f.filled_at or f.submitted_at or datetime.min.replace(tzinfo=timezone.utc), f.broker_order_id))
    return fills


def match_fifo(fills: Iterable[Fill]) -> tuple[list[RoundTrip], dict[str, list[Lot]]]:
    open_lots: dict[str, deque[Lot]] = defaultdict(deque)
    trips: list[RoundTrip] = []
    for f in fills:
        if f.side == "buy":
            open_lots[f.symbol].append(Lot(fill=f, qty_remaining=f.qty))
            continue
        # SELL: consume oldest lots
        remaining = f.qty
        q = open_lots[f.symbol]
        while remaining > 1e-12 and q:
            lot = q[0]
            take = min(lot.qty_remaining, remaining)
            trips.append(
                RoundTrip(
                    lane=lot.fill.lane,
                    symbol=f.symbol,
                    qty=take,
                    buy_price=lot.fill.price,
                    sell_price=f.price,
                    buy_at=lot.fill.filled_at or lot.fill.submitted_at,
                    sell_at=f.filled_at or f.submitted_at,
                    sell_lane=f.lane,
                )
            )
            lot.qty_remaining -= take
            remaining -= take
            if lot.qty_remaining <= 1e-9:
                q.popleft()
        # Any unmatched SELL (no open lot) is dropped silently; tracked separately below.
    return trips, {k: list(v) for k, v in open_lots.items() if v}


def latest_snapshot_positions() -> dict[str, dict]:
    path = RUNTIME / "portfolio-snapshots.jsonl"
    if not path.exists():
        return {}
    last_obj = None
    with path.open() as fh:
        for raw in fh:
            try:
                last_obj = json.loads(raw)
            except Exception:
                pass
    if not last_obj:
        return {}
    positions = (last_obj.get("payload") or {}).get("positions") or []
    return {(p.get("symbol") or "").upper(): p for p in positions}


@dataclass
class LaneStats:
    lane: str
    trips: list[RoundTrip] = field(default_factory=list)

    def summary(self) -> dict:
        n = len(self.trips)
        if n == 0:
            return {
                "lane": self.lane,
                "trips": 0,
                "notional": 0.0,
                "pnl": 0.0,
                "pnl_pct_on_notional": 0.0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "biggest_win": 0.0,
                "biggest_loss": 0.0,
                "avg_hold_min": None,
            }
        pnls = [t.pnl for t in self.trips]
        notional = sum(t.cost for t in self.trips)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        holds = [t.hold_minutes for t in self.trips if t.hold_minutes is not None]
        return {
            "lane": self.lane,
            "trips": n,
            "notional": notional,
            "pnl": sum(pnls),
            "pnl_pct_on_notional": (sum(pnls) / notional * 100.0) if notional > 0 else 0.0,
            "win_rate": (len(wins) / n * 100.0) if n else 0.0,
            "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
            "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
            "biggest_win": max(pnls) if pnls else 0.0,
            "biggest_loss": min(pnls) if pnls else 0.0,
            "avg_hold_min": statistics.mean(holds) if holds else None,
        }


def fmt_money(x: float) -> str:
    return f"${x:,.4f}"


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def fmt_hold(x: float | None) -> str:
    if x is None:
        return "—"
    if x < 60:
        return f"{x:.1f}m"
    h = x / 60.0
    if h < 24:
        return f"{h:.1f}h"
    return f"{h/24:.1f}d"


def render_markdown(
    realized_by_lane: dict[str, LaneStats],
    open_lot_rows: list[dict],
    snapshot_meta: dict,
    file_meta: dict,
) -> str:
    lines: list[str] = []
    lines.append("# v1 Lane Edge Analysis")
    lines.append("")
    lines.append(
        f"Generated from {file_meta['source_files']} order-event files "
        f"({file_meta['fills']} distinct filled orders: "
        f"{file_meta['buys']} buys, {file_meta['sells']} sells)."
    )
    lines.append("")
    lines.append(
        f"FIFO round-trip matching by `symbol`. Lane attribution comes from the "
        f"BUY's `client_order_id` prefix."
    )
    lines.append("")
    if snapshot_meta:
        lines.append(
            f"Open-lot unrealized P&L sourced from portfolio snapshot at "
            f"`{snapshot_meta.get('created_at','?')}`."
        )
        lines.append("")

    # Realized table
    lines.append("## Realized round-trips by lane")
    lines.append("")
    lines.append(
        "| Lane | Trips | Notional | Realized P&L | P&L % | Win rate | Avg win | Avg loss | Biggest win | Biggest loss | Avg hold |"
    )
    lines.append(
        "|------|------:|---------:|-------------:|------:|---------:|--------:|---------:|------------:|-------------:|---------:|"
    )
    # Sort lanes by total pnl descending
    summaries = sorted(
        (s.summary() for s in realized_by_lane.values()),
        key=lambda r: r["pnl"],
        reverse=True,
    )
    totals = {
        "trips": 0, "notional": 0.0, "pnl": 0.0, "wins": 0,
    }
    for s in summaries:
        totals["trips"] += s["trips"]
        totals["notional"] += s["notional"]
        totals["pnl"] += s["pnl"]
        lines.append(
            f"| `{s['lane']}` | {s['trips']} | {fmt_money(s['notional'])} | "
            f"{fmt_money(s['pnl'])} | {fmt_pct(s['pnl_pct_on_notional'])} | "
            f"{s['win_rate']:.1f}% | {fmt_money(s['avg_win'])} | "
            f"{fmt_money(s['avg_loss'])} | {fmt_money(s['biggest_win'])} | "
            f"{fmt_money(s['biggest_loss'])} | {fmt_hold(s['avg_hold_min'])} |"
        )
    overall_pct = (totals["pnl"] / totals["notional"] * 100.0) if totals["notional"] > 0 else 0.0
    lines.append(
        f"| **TOTAL** | **{totals['trips']}** | **{fmt_money(totals['notional'])}** | "
        f"**{fmt_money(totals['pnl'])}** | **{fmt_pct(overall_pct)}** | — | — | — | — | — | — |"
    )
    lines.append("")

    # Open lots
    lines.append("## Still-open lots (unrealized)")
    lines.append("")
    if not open_lot_rows:
        lines.append("_No still-open lots with both an open BUY in the audit log and a matching current position._")
    else:
        lines.append(
            "| Lane | Symbol | Open qty | Avg cost | Current px | Cost basis | Mkt value | Unrealized P&L | P&L % |"
        )
        lines.append(
            "|------|--------|---------:|---------:|-----------:|-----------:|----------:|---------------:|------:|"
        )
        u_total_cost = 0.0
        u_total_mv = 0.0
        for r in open_lot_rows:
            u_total_cost += r["cost_basis"]
            u_total_mv += r["market_value"]
            lines.append(
                f"| `{r['lane']}` | {r['symbol']} | {r['qty']:.6f} | "
                f"${r['avg_cost']:.4f} | ${r['current_price']:.4f} | "
                f"{fmt_money(r['cost_basis'])} | {fmt_money(r['market_value'])} | "
                f"{fmt_money(r['unrealized_pl'])} | {fmt_pct(r['unrealized_pl_pct'])} |"
            )
        u_pl = u_total_mv - u_total_cost
        u_pct = (u_pl / u_total_cost * 100.0) if u_total_cost > 0 else 0.0
        lines.append(
            f"| **TOTAL** | — | — | — | — | **{fmt_money(u_total_cost)}** | "
            f"**{fmt_money(u_total_mv)}** | **{fmt_money(u_pl)}** | **{fmt_pct(u_pct)}** |"
        )
    lines.append("")

    # Interpretation
    lines.append("## Interpretation")
    lines.append("")
    earners = [s for s in summaries if s["pnl"] > 0.01]
    losers = [s for s in summaries if s["pnl"] < -0.01]
    flat = [s for s in summaries if -0.01 <= s["pnl"] <= 0.01]

    def fmt_lane_line(s: dict) -> str:
        return (
            f"- `{s['lane']}`: {fmt_money(s['pnl'])} across {s['trips']} round-trips "
            f"({s['win_rate']:.0f}% win-rate, avg hold {fmt_hold(s['avg_hold_min'])})"
        )

    lines.append("**Earned edge (positive realized P&L):**")
    if earners:
        for s in earners:
            lines.append(fmt_lane_line(s))
    else:
        lines.append("- _None._")
    lines.append("")
    lines.append("**Break-even noise (|P&L| ≤ $0.01):**")
    if flat:
        for s in flat:
            lines.append(fmt_lane_line(s))
    else:
        lines.append("- _None._")
    lines.append("")
    lines.append("**Lost money (negative realized P&L):**")
    if losers:
        for s in losers:
            lines.append(fmt_lane_line(s))
    else:
        lines.append("- _None._")
    lines.append("")
    lines.append(
        "_Notional values are tiny by design (this account is a $5-biweekly DCA "
        "live-paper scaffold), so dollar P&L should be read as edge signal, not "
        "income. Percent-on-notional is the more meaningful column for comparing "
        "lanes._"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    files = iter_order_event_files()
    fills = collect_fills()
    buys = sum(1 for f in fills if f.side == "buy")
    sells = sum(1 for f in fills if f.side == "sell")

    trips, open_lots = match_fifo(fills)

    # Group realized by lane
    by_lane: dict[str, LaneStats] = defaultdict(lambda: LaneStats(lane=""))
    for t in trips:
        if not by_lane[t.lane].lane:
            by_lane[t.lane].lane = t.lane
        by_lane[t.lane].trips.append(t)

    # Open lots: cross-reference with latest portfolio snapshot
    snap_positions = latest_snapshot_positions()
    # Pull snapshot metadata
    snap_meta = {}
    snap_path = RUNTIME / "portfolio-snapshots.jsonl"
    if snap_path.exists():
        last = None
        with snap_path.open() as fh:
            for ln in fh:
                last = ln
        if last:
            try:
                last_obj = json.loads(last)
                snap_meta = {"created_at": last_obj.get("created_at")}
            except Exception:
                pass

    # For each symbol with both open lots in audit AND a position in snapshot,
    # use snapshot's current_price and the audit's avg cost basis from remaining lots.
    open_rows = []
    for symbol, lots in open_lots.items():
        pos = snap_positions.get(symbol)
        if not pos:
            continue
        # Total open qty & cost basis per lane
        per_lane_open: dict[str, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))
        for lot in lots:
            q, cb = per_lane_open[lot.fill.lane]
            per_lane_open[lot.fill.lane] = (q + lot.qty_remaining, cb + lot.qty_remaining * lot.fill.price)
        current_price = float(pos.get("current_price") or 0.0)
        for lane, (qty, cost) in per_lane_open.items():
            if qty <= 1e-9:
                continue
            mv = qty * current_price
            avg_cost = cost / qty
            open_rows.append({
                "lane": lane,
                "symbol": symbol,
                "qty": qty,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "cost_basis": cost,
                "market_value": mv,
                "unrealized_pl": mv - cost,
                "unrealized_pl_pct": ((mv - cost) / cost * 100.0) if cost > 0 else 0.0,
            })

    # Sort open rows by unrealized P&L desc
    open_rows.sort(key=lambda r: r["unrealized_pl"], reverse=True)

    file_meta = {
        "source_files": len(files),
        "fills": len(fills),
        "buys": buys,
        "sells": sells,
    }

    md = render_markdown(by_lane, open_rows, snap_meta, file_meta)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md)
    print(f"Wrote {OUT}")
    print(f"  Files read: {len(files)}  Fills: {len(fills)}  Buys: {buys}  Sells: {sells}")
    print(f"  Round-trips: {len(trips)}  Lanes (realized): {len(by_lane)}  Open-lot rows: {len(open_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
