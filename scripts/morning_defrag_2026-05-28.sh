#!/usr/bin/env bash
# One-shot morning defrag for 2026-05-28.
# Liquidates stale lots flagged by /api/risk/defragmentation-candidates so the
# autopilot has fresh buying power. Fires after market open (no PDT impact
# because all source buys are >24h old).
#
# Sell rationale (recorded for audit trail):
#   EL   — winner +3.5%, tiny $1.81 lot, lock the gain and recycle BP.
#   MDT  — -2.7%, 5.6d stale, no fresh thesis.
#   NFLX — -1.8%, 6.8d stale, long-term bullish but autopilot can re-enter on fresh signal.
#   XLE  — HOLD (removed pre-open). Fresh Middle East attacks 5/28 re-price oil higher
#          near-term; XLE is the one defensive bid against a potentially hot 8:30 PCE.
#          Structural exit thesis (Q4 oil rolldown) deferred to next week.

set -u
LOG="/home/cresp3/automated-investment-app/scripts/morning_defrag_2026-05-28.log"
API="http://localhost:8000"

log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

log "morning_defrag start"

# Wait until market is open before submitting.
for i in $(seq 1 60); do
    open=$(curl -fs "$API/api/safety/status" | python3 -c "import sys,json;print(json.load(sys.stdin)['market_clock']['is_open'])" 2>/dev/null || echo "False")
    if [ "$open" = "True" ]; then
        log "market open detected"
        break
    fi
    log "market not open yet (attempt $i), sleeping 30s"
    sleep 30
done

if [ "$open" != "True" ]; then
    log "ABORT: market never opened in poll window"
    exit 1
fi

for sym in EL MDT NFLX; do
    log "selling 100% of $sym"
    resp=$(curl -sX POST "$API/api/broker/positions/${sym}/sell-market?percent=100" 2>&1)
    log "  resp: $resp"
    sleep 2
done

log "morning_defrag done"
