# Execution Guide — Friday 2026-05-15

**Role:** Claude in the driver's seat for this test session.
**Operator:** crespo1301@gmail.com
**Account:** Alpaca live (...b7a676), $24.71 + $25 injection planned → ~$50 base.
**PDT going into Friday:** 2 / 3 (1 free slot — reserve it).

This guide is a minute-by-minute checklist. **Read it once start-to-finish before market open.** Then execute top-to-bottom. Every step that touches the broker uses real endpoints already in `apps/api`. Every command assumes you're at `/home/cresp3/automated-investment-app` with the API running on `localhost:8000`.

**Important context:** the brief-loader (`apps/api/app/services/premarket_brief.py`) is not yet implemented. So the JSON brief is not auto-consumed by the autopilot. This session is **operator-piloted with the brief as a reference**. Entries flow through the autopilot's existing scorer; exits and defrag are done manually by you using documented endpoints below.

---

## How this repo runs (three processes)

Your normal local dev runs three things, each in its own terminal:

| Process | Script | What it does |
|---|---|---|
| **API** (FastAPI/uvicorn) | `npm run dev:api` | Serves all the HTTP endpoints we curl against (port 8000) |
| **Autopilot worker** | `npm run dev:autopilot` | Standalone Python loop that scores the watchlist + executes entries every 30s |
| **Web dashboard** | `npm run dev:web` | The Next.js dashboard (hot-reloads, no restart needed) |

**Both** the API and the autopilot import the same `app.services.*` modules. The code changes from this session live in those services. So **both** the API process and the autopilot process must be restarted to load them. The web dashboard is fine as-is.

### Restart procedure (do this once, tonight after reading the brief)

In the **API terminal:** `Ctrl-C`, then `npm run dev:api`. Wait for `Application startup complete`.

In the **autopilot terminal:** `Ctrl-C`, then `npm run dev:autopilot`. Wait for it to print its first heartbeat (the loop prints state every ~30s).

The web terminal stays running.

## Pre-flight — Thursday night (now)

Run these from the repo root and confirm the responses look sane:

```bash
# 1. API alive (the repo's built-in healthcheck script)
npm run check:api

# 2. Autopilot worker status (queries the same audit store the loop writes to)
npm run autopilot:status

# 3. Account + daytrade count
curl -s http://localhost:8000/api/broker/account | python3 -m json.tool

# 4. Kill switch should be OFF
curl -s http://localhost:8000/api/safety/status | python3 -c "import json,sys; d=json.load(sys.stdin); print('kill_switch:', d['safety_state']['kill_switch_enabled'])"

# 5. Confirm the brief files are on disk
ls -la data/premarket/2026-05-15.*
```

**Expected:** `check:api` returns the root payload. `autopilot:status` shows `enabled: true, last_action: waiting_for_market_open`. Account shows `daytrade_count: 3, portfolio_value: ~24.7`. Kill switch `False`. Both `.json` and `.md` (and `execution-guide.md`) present.

If any of these fail: stop, fix the env, and start over.

---

## Friday 2026-05-15 — Timeline

All times are **ET**.

### 08:00–08:30 ET — Cash injection

1. Log into Alpaca dashboard (web or app).
2. Initiate the **$25 deposit**. If using instant transfer, buying power should reflect within minutes.
3. Confirm with:
   ```bash
   curl -s http://localhost:8000/api/broker/account | python3 -c "import json,sys; d=json.load(sys.stdin); print('cash:', d['cash'], 'bp:', d['buying_power'], 'pv:', d['portfolio_value'])"
   ```
4. **Target:** `bp ≥ $26.00` (your $1.05 + $25). If less, the deposit hasn't cleared — wait.

**If deposit takes longer than 30 min:** proceed without it. Plan still works at $1.05 cash + $6.21 defrag reclaim + $3.46 T-exit = $10.72 deployable. Cut Phase 2 candidates to the top 2 (SMH + NVDA-adds only).

---

### 08:30–09:00 ET — Market & news scan (15 min)

Open three tabs (any of these — your call):
- SPY / QQQ futures (Bloomberg, Yahoo, TradingView)
- VIX live quote
- Major headlines: Reuters, CNBC, Bloomberg

Look for:
- **Trump-Xi AI-summit outcome** — overnight statement? Any specific semis or AI restrictions?
- **Warsh confirmation news** — any Fed-tone signals?
- **Premarket gaps in your candidates:** SMH, GOOGL, NVDA, SPY, AAPL, XLE.

Write your gap table on paper:

| Symbol | 5/14 close | Pre-mkt now | % move |
|---|---|---|---|
| SPY | 748.33 | __ | __ |
| SMH | 580.25 | __ | __ |
| NVDA | 235.92 | __ | __ |
| GOOGL | ~400 | __ | __ |
| AAPL | 300.35 | __ | __ |
| XLE | ~57.51 | __ | __ |

### 09:00 ET — Decision tree based on the scan

| Scenario | Action |
|---|---|
| Futures **+0.5% or more, VIX flat/down** | Plan stands. Run all phases. |
| Futures **-0.5% to +0.5%, VIX flat** | Plan stands but skip XLE and AAPL. Tighten Phase 2 to top 4. |
| Futures **down 0.5–1.5%** | Phase 1 still runs (defrag is good in any tape). Skip Phase 2 entries until 10:30 ET, re-evaluate then. |
| Futures **down >1.5% OR VIX >22** | Phase 1 only (defrag for cash). Phase 2 = no entries today. Kill switch enable: `curl -s -X POST 'http://localhost:8000/api/safety/kill-switch/enable?reason=Friday%20event%20risk%20too%20high' \| python3 -m json.tool`. Wait for Monday. |
| Anything truly weird (gap >3%, VIX >30) | Kill switch ON. Do nothing. Notify yourself you stood down. |

---

### 09:25 ET — Final pre-open checks

```bash
# Confirm autopilot is still armed
curl -s http://localhost:8000/api/autopilot/status | python3 -m json.tool

# Pre-flight readiness (this is the system's own pre-open scan)
curl -s http://localhost:8000/api/trading/morning-readiness | python3 -m json.tool | head -60

# Re-check defrag list is still the same four names
curl -s http://localhost:8000/api/risk/defragmentation-candidates | python3 -m json.tool
```

**If `morning-readiness` reports anything red or unexpected (kill switch on, autopilot disabled, account locked), stand down for today.**

---

### 09:30 ET — Market open: Phase 1 (defrag + T exit)

**Important: code changes applied this session.** The manual-sell endpoint now has a PDT guard. It will refuse to fire a sell that would burn a PDT slot you don't have unless you pass `?force_pdt=true`. **None of the Phase 1 sells below should trigger that guard** — every one is >24h old (no same-day buy on the same symbol) — but if the API returns 409 with a PDT message, STOP and re-check the position's buy history before forcing.

The defrag endpoint has also been extended: T will now show up automatically in `/api/risk/defragmentation-candidates` because it's held >48h with >1% loss (the new stale-laggard branch).

> **Before doing anything, restart both the API and the autopilot processes** so the new code is loaded. In the API terminal: `Ctrl-C` then `npm run dev:api`. In the autopilot terminal: `Ctrl-C` then `npm run dev:autopilot`. Without these restarts, the running API has the OLD `sell-market` endpoint (no PDT guard) and the running autopilot has the OLD defrag thresholds.

Execute these **immediately at the bell** — endpoints reject when market is closed (HTTP 409). All are >24h old, **so they do NOT consume a PDT slot.**

```bash
# 1. Re-check defrag (should now include T thanks to the new stale-laggard rule)
curl -s http://localhost:8000/api/risk/defragmentation-candidates | python3 -m json.tool

# 2. Sell each flagged candidate
curl -s -X POST http://localhost:8000/api/broker/positions/AMZN/sell-market | python3 -m json.tool
curl -s -X POST http://localhost:8000/api/broker/positions/CMCSA/sell-market | python3 -m json.tool
curl -s -X POST http://localhost:8000/api/broker/positions/SCHD/sell-market | python3 -m json.tool
curl -s -X POST http://localhost:8000/api/broker/positions/V/sell-market | python3 -m json.tool
curl -s -X POST http://localhost:8000/api/broker/positions/T/sell-market | python3 -m json.tool
```

**Verify each receipt shows `status: FILLED` or accepted.** If any returns 409 or 404, screenshot and stop.

After ~30 seconds, verify cash:

```bash
curl -s http://localhost:8000/api/broker/account | python3 -c "import json,sys; d=json.load(sys.stdin); print('cash now:', d['cash'], 'bp:', d['buying_power'])"
```

**Target:** `cash ≥ $30` (≈ $25 inject + $6.21 defrag + $3.46 T). If `cash < $20`, something didn't fill — investigate before continuing.

---

### 09:30–10:00 ET — Phase 2: monitor, do not chase

The autopilot will start scoring on its 30-second cycle. Its watchlist already includes SMH, GOOGL, NVDA, SPY, AAPL, XLE, so it CAN pick them. It can also still pick names from the blocklist in the brief — the brief isn't wired yet.

**Your job during the first 30 minutes:**

1. Watch the dashboard route or poll fills:
   ```bash
   curl -s http://localhost:8000/api/broker/reconciliation | python3 -c "
   import json,sys
   d=json.load(sys.stdin)
   from datetime import datetime,timedelta
   today='2026-05-15'
   for o in d['orders']:
       ts=o.get('filled_at') or o.get('submitted_at') or ''
       if ts.startswith(today.replace('-','-')):  # crude
           print(o['symbol'], o['side'], o.get('filled_quantity'), o.get('filled_average_price'), o.get('status'))
   "
   ```

2. **If the autopilot fires on a brief-blocklisted name** (T, F, GM, OXY, IWM, AMD, AMZN, CMCSA, SCHD, V, NIO, TSLA, GME, MSTR), **immediately cancel**:
   ```bash
   curl -s -X POST http://localhost:8000/api/broker/cancel-open-orders | python3 -m json.tool
   ```
   Note: this cancels ALL open orders, not just the bad one. Acceptable cost of test run.

3. **If the autopilot fires on a brief-listed name** (SMH, GOOGL, NVDA, SPY, AAPL, XLE), let it run. The brief levels and conviction guide your tolerance — if the entry comes >2% above the brief's `entry_zone.high`, manually cancel (it's chasing strength).

4. **PDT discipline:** if the autopilot is about to exit a name it bought THIS SESSION (rare given the morning-readiness path, but possible in panic-stop scenarios), cancel that exit using `cancel-open-orders` and let the position go overnight. **One same-day round trip puts you at 3/3 again.**

---

### 10:00 ET — UMich Consumer Sentiment release

Released at 10:00 ET. SPY frequently gaps within 1–2 minutes.

**If the print causes SPY to move >0.5% in either direction within 5 minutes:**
- Wait the gap out. Do NOT enter SPY/SMH/QQQ in the first 5-minute post-print bar — wait for the second.
- If the move is sharply negative (>1% down): **enable kill switch** for 30 min to prevent autopilot from chasing the panic:
  ```bash
  curl -s -X POST 'http://localhost:8000/api/safety/kill-switch/enable?reason=UMich%20negative%20surprise%20cooling%20off' | python3 -m json.tool
  # ... wait 30 min, observe ...
  curl -s -X POST http://localhost:8000/api/safety/kill-switch/disable | python3 -m json.tool
  ```

---

### 10:30–15:30 ET — Steady state

By now you should have:
- ~5–6 positions total (5 defragged + 1–4 new from Phase 2)
- Cash buffer: $3–$8
- PDT count: still 2 (no day trades today)

**Hourly checklist (set a 60-min reminder):**

```bash
echo "=== $(date +%H:%M) ==="
curl -s http://localhost:8000/api/broker/account | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"PV \${d['portfolio_value']:.2f}  cash \${d['cash']:.2f}  DT {d['daytrade_count']}/3\")"
curl -s http://localhost:8000/api/autopilot/status | python3 -c "import json,sys; d=json.load(sys.stdin); print('autopilot:', d.get('enabled'), '| last:', d.get('last_action'))"
```

**Watch for:**
- `daytrade_count` increments above 2 → autopilot did a same-day round trip. Immediately enable kill switch and investigate fills.
- `last_action` reports an error → screenshot, stand down for the hour.
- Portfolio value dropping >2% in an hour → kill switch on, manual review.

---

### 15:45 ET — Pre-close decision

Look at NVDA position size and gain.

| NVDA P/L now | Action |
|---|---|
| +2% or more from your blended cost | **Trim 50% of total NVDA holding**. Earnings 5/20 AMC is binary; lock half. Use the sell-market endpoint (this counts as a day trade ONLY if you also bought NVDA today — if NVDA was untouched today, it's free). Check `daytrade_count` and whether NVDA was bought today before deciding. |
| Flat to +2% | Hold. |
| Negative | Hold and tighten mental stop. Re-evaluate Monday morning. |

If you have new NVDA buys from today, **do NOT trim** — that creates a same-day round trip and burns a PDT slot. Hold the full position into Monday and trim then.

---

### 16:00 ET — Close + EOD review

```bash
# Full snapshot for the log
mkdir -p data/premarket/eod
curl -s http://localhost:8000/api/broker/reconciliation > data/premarket/eod/2026-05-15-recon.json
curl -s http://localhost:8000/api/broker/account > data/premarket/eod/2026-05-15-account.json
curl -s http://localhost:8000/api/performance/daily-recap > data/premarket/eod/2026-05-15-recap.json 2>/dev/null
curl -s http://localhost:8000/api/safety/status > data/premarket/eod/2026-05-15-safety.json

ls -la data/premarket/eod/
```

Then look at the recap and write 5 lines in your operator notes:

- PV start: $24.71 (+ $25 inject = effective ~$50)
- PV end: __
- Defrag reclaimed: __
- New positions opened: __
- Day-trade count change: 3 → __

---

## Abort & emergency commands (memorize these)

```bash
# STOP EVERYTHING (kill switch on + cancel open orders)
curl -s -X POST 'http://localhost:8000/api/safety/kill-switch/enable?reason=MANUAL%20ABORT' | python3 -m json.tool
curl -s -X POST http://localhost:8000/api/broker/cancel-open-orders | python3 -m json.tool

# Disable autopilot but keep kill switch off (less aggressive stand-down)
curl -s -X POST 'http://localhost:8000/api/autopilot/disable?reason=manual%20pause' | python3 -m json.tool

# Re-enable when ready
curl -s -X POST http://localhost:8000/api/safety/kill-switch/disable | python3 -m json.tool
curl -s -X POST 'http://localhost:8000/api/autopilot/enable?reason=resuming' | python3 -m json.tool
```

---

## Decision quick-reference card (print or pin)

```
PDT:           2/3 going in. Save the slot. NO same-day round trips.
Catalysts:     Trump-Xi summit, Warsh confirm, UMich 10am, NVDA earnings 5/20.
Tape bias:     Risk-on at 5/14 close (SPY +0.74%, VIX 17.87).

PRIORITY:      SMH > GOOGL > SPY > NVDA > AAPL > XLE
SIZE / NAME:   ~$8-10 each (top 4); ~$5-6 each (AAPL/XLE)
TOTAL CAP:     ~$28 new deployment, $5+ cash buffer

DON'T BUY:     T, F, GM, OXY, IWM, AMD, AMZN, CMCSA, SCHD, V, NIO, TSLA, GME, MSTR

DEFRAG:        AMZN, CMCSA, SCHD, V, T  (sell at open, no PDT cost)
TRIM:          NVDA before 5/20 if green and not bought today

ABORT IF:      futures <-1.5%, VIX>22, autopilot errors, weird fills
```

---

## What Codex should do in parallel

While the operator runs this guide live, Codex can ship the following in the background — none of them block tomorrow's run:

1. **`add-premarket-brief-pipeline`** (already proposed) — the loader + scoring boost.
2. **Review the in-session code changes** that landed this round: (a) manual-sell PDT guard in `apps/api/app/api/routes.py`, (b) defrag stale-laggard branch in `apps/api/app/services/exit_monitor.py`, (c) new settings in `apps/api/app/core/config.py`. 5 new tests cover them in `tests/test_trading_pipeline.py`. Codex owns commit / push / version.
3. **`lane-diversity-diagnostic`** (future): every recent autopilot buy used `opening_range_breakout_v1`. The `pdt_capped_swing_entry_strategy_ids` setting hard-limits eligible lanes when PDT is at cap — that's intended, but at low NAV it concentrates all entries in one setup type. Worth a proposal to broaden when account size is low.

### Important finding (root-cause of your PDT problem)

Every same-day round-trip in your order log is a `manual_exit_*` — **the autopilot has never generated a PDT day-trade in the rolling window.** You did, via the manual sell endpoint (curl/dashboard). The manual sell had no PDT guard until this session's code change. Going forward:

- The endpoint defaults to PDT-aware and will refuse to fire if it would burn your last slot.
- Override with `?force_pdt=true` if you accept the cost.
- This is the highest-leverage fix in the system. Keep the guard enabled. Operator discipline > strategy alpha at this account size.

---

## Reminders (real-money safety)

- This is a **test run** at small notional ($50 account). Treat it as a procedure rehearsal, not an alpha hunt.
- The brief is **advisory**. The kill switch + cancel-orders endpoints are your only true safety net.
- If anything feels wrong, **kill switch first, diagnose second.** A missed trade costs $0; a runaway autopilot can cost the account.
- After today, write a short post-mortem (what worked, what didn't, what to change before Monday).
