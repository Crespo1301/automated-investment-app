#!/usr/bin/env bash
# 2026-05-29 morning rotation — fires once at the open.
#
# Phase 1 (sell, via API):  NVDA $5.91 + XLF $6.14  -> frees ~$12.05
# Phase 2 (buy,  via Alpaca SDK):  SMH $8, GLD $5, USO $5  -> ~$18 deployed
# Net leaves ~$3.6 buffer on top of the morning $9.56 BP for autopilot to use.
#
# Sell rationale (no PDT impact — both lots are >1 session old):
#   NVDA — beat-and-fade hangover from 5/20, no fresh catalyst tomorrow.
#   XLF  — Fed-on-hold (PCE 3.8% y/y) is structurally against banks.
#
# Buy rationale (hidden-gem watchlist from premarket-2026-05-29):
#   SMH — semis breadth, AI capex tailwind, no single-name event risk.
#   GLD — sticky inflation + Fed on hold = real-rate tailwind for gold.
#   USO — WTI $90, ME risk premium holding into June.
#
# Process bug fix from 2026-05-28: single-process lockfile, no parsed-list races.

set -u
LOCK="/tmp/morning_rotation_2026-05-29.lock"
LOG="/home/cresp3/automated-investment-app/scripts/morning_rotation_2026-05-29.log"
API="http://localhost:8000"
VENV_PY="/home/cresp3/automated-investment-app/apps/api/.venv/bin/python3"
ENV_FILE="/home/cresp3/automated-investment-app/apps/api/.env"

# --- single-instance guard ---
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "[$(date -Is)] already running, exiting" >> "$LOG"
    exit 0
fi

log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

log "rotation start (pid $$)"

# --- sleep until 09:25 ET, then poll for actual open ---
TARGET=$(date -d "2026-05-29 09:25:00 EDT" +%s 2>/dev/null || echo 0)
NOW=$(date +%s)
DELTA=$(( TARGET - NOW ))
if [ "$DELTA" -gt 60 ]; then
    log "sleeping $DELTA s until 09:25 ET poll window"
    sleep "$DELTA"
fi

open="False"
for i in $(seq 1 240); do
    open=$(curl -fs "$API/api/safety/status" | $VENV_PY -c "import sys,json;print(json.load(sys.stdin)['market_clock']['is_open'])" 2>/dev/null || echo "False")
    if [ "$open" = "True" ]; then
        log "market open detected"
        break
    fi
    log "wait open (attempt $i)"
    sleep 30
done
if [ "$open" != "True" ]; then
    log "ABORT: market never opened in poll window"
    exit 1
fi

# --- let the open auction settle a few minutes before submitting ---
log "settling 180s after open"
sleep 180

# --- Phase 1: sells via API ---
for sym in NVDA XLF; do
    log "selling 100% of $sym"
    resp=$(curl -sX POST "$API/api/broker/positions/${sym}/sell-market?percent=100" 2>&1)
    log "  resp: $resp"
    sleep 3
done

# --- wait for fills to update BP ---
log "waiting 45s for fills to reflect in BP"
sleep 45

# --- Phase 2: buys via Alpaca SDK (no manual-buy API endpoint exists) ---
$VENV_PY <<PY 2>&1 | tee -a "$LOG"
import os, sys, time, pathlib
env_path = pathlib.Path("$ENV_FILE")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

api_key = os.environ["INVESTMENT_APP_ALPACA_API_KEY"]
secret  = os.environ["INVESTMENT_APP_ALPACA_SECRET_KEY"]
paper   = os.environ.get("INVESTMENT_APP_ALPACA_PAPER","false").lower() == "true"

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

client = TradingClient(api_key, secret, paper=paper)
acct = client.get_account()
bp = float(acct.buying_power)
print(f"[buys] account BP before buys: \${bp:.2f}")

# Cap per ticker so a low-BP day doesn't over-deploy.
plan = [("SMH", 8.0), ("GLD", 5.0), ("USO", 5.0)]
total_target = sum(n for _, n in plan)
if bp < total_target:
    scale = max(0.0, bp - 0.50) / total_target
    print(f"[buys] BP \${bp:.2f} below target \${total_target:.2f}, scaling to {scale:.2f}")
    plan = [(s, round(n * scale, 2)) for s, n in plan]

for sym, notional in plan:
    if notional < 1.00:
        print(f"[buys] {sym} skip: notional \${notional:.2f} below \$1.00 minimum")
        continue
    coid = f"morning_rotation_2026-05-29_{sym.lower()}_{int(time.time())}"
    req = MarketOrderRequest(
        symbol=sym,
        notional=notional,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        client_order_id=coid,
    )
    try:
        order = client.submit_order(req)
        print(f"[buys] {sym} BUY \${notional:.2f}  status={order.status}  id={order.id}  coid={coid}")
    except Exception as e:
        print(f"[buys] {sym} BUY \${notional:.2f}  FAILED: {e!r}")
    time.sleep(2)

acct = client.get_account()
print(f"[buys] account BP after buys: \${float(acct.buying_power):.2f}")
PY

log "rotation done"
