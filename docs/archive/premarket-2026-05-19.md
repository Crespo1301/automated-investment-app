# Pre-market → early-session review — 2026-05-19 (Tuesday)

Claude pre-market pass. It began as a pre-open analysis; the market
opened mid-review, so this also documents an early-session autopilot
restoration and two code changes. Codex closes out (review, build,
commit/push) per the workflow.

## Headline — the autopilot loop died overnight; restored exit-only at 09:42 ET

The autopilot loop was **not running** this morning. Last night at
**17:40 ET** it hit a transient `ConnectionError` — DNS failed to
resolve `api.alpaca.markets`, almost certainly the WSL host going to
sleep. `run_autopilot_loop` treated that infrastructure blip as a fatal
fault: it tripped the kill switch, disarmed autopilot, and exited the
process.

State found this morning:

- loop process: gone
- `autopilot.enabled`: false (`disabled_by_error`)
- kill switch: ON
- → the 5 open positions had **no automated stop-loss / take-profit
  coverage**; fractional lots get no broker OCO either.

Already fine: the API server was restarted at 08:37 ET, so yesterday's
stale-config finding is resolved — `/api/autopilot/status` reads
`entry_execution_enabled: false` honestly. DNS verified working again.

## Account snapshot

- Pre-open (08:50 ET): NAV **$49.92** · cash $25.69 · 5 positions $24.22 · PDT 1/3.
- Early session (09:45 ET): NAV **$49.77** (−0.30%) — tracking a soft,
  tech-led-down tape (S&P futures −0.3/−0.4%, Nasdaq-100 −0.6%, chip
  sell-off, inflation/yield worries).

| Symbol | Value | Entry → Last (09:45) | P&L | Note |
|--------|-------|----------------------|-----|------|
| MSFT | $6.27 | 417.96 → 425.36 | +1.77% | was at the +2.5% small-win trigger (428.41) pre-open; slipped back below it after the open |
| XLF  | $6.16 | 51.45 → 51.34 | −0.21% | quiet |
| WFC  | $5.57 | 73.92 → 74.19 | +0.36% | quiet |
| NKE  | $3.05 | 42.23 → 42.06 | −0.41% | quiet |
| SPY  | $3.04 | 746.03 → 733.80 | −1.64% | weakest lot; app-stop $727.38 (~0.9% below); flagged stale-laggard |

All five are 4–5 day holds — none costs a PDT slot to exit. Worst case
(all 5 stop out at 2.5%) ≈ −$0.60.

## Decision — restore exit-only autopilot, keep entries OFF

The operator delegated the call ("treat it as your own money, grow it as
fast as possible"). Decision and reasoning:

1. **Restore exit-only autopilot.** Five fractional lots with no broker
   OCO need the loop as their only stop/take-profit coverage. The kill
   switch had tripped on infrastructure noise, not a risk event —
   clearing it is recovery, not escalation. The 2026-05-18 EOD plan
   already *intended* exit-only autopilot to run today.
2. **Entries stay OFF.** "Grow fast" does not mean arming unattended
   entries on a $50 account into a soft tech tape with an entry path
   that has not run once under post-cleanup config. The disciplined
   ramp *is* the growth strategy — see below.

## What I did (09:42–09:43 ET)

1. Cleared the kill switch (`worker --disable-kill-switch`).
2. Armed autopilot exit-only (`worker --enable-autopilot`).
3. Relaunched the loop as a detached daemon
   (`setsid … python -m app.worker --autopilot-loop`, pid 531004,
   stdout/stderr → `.runtime/autopilot-loop.log`).
4. Verified: heartbeats every ~30s, `last_error: null`, `last_action:
   entry_execution_locked` (the healthy exit-only heartbeat — full tick,
   exits checked, entries correctly locked). Live `/api/risk/exit-check`
   returns no signals.

## Code changes (uncommitted — Codex to review/build/push)

### 1. Loop survives transient network blips — `apps/api/app/services/autopilot.py`

`run_autopilot_loop` treated *every* exception as fatal. A single
transient network error (DNS hiccup, dropped connection, timeout — the
exact overnight failure) tripped the kill switch and killed exit
protection for the rest of the session, with no auto-recovery.

The loop now classifies the error. A transient network error is retried
for up to `_TRANSIENT_ERROR_RETRY_BUDGET` (6) consecutive ticks
(~3 min of grace) while staying armed; the retry is surfaced as a
`transient_network_retry:n/6` heartbeat so the dashboard is neither
silently healthy nor silently dead. Only an outage that *persists* past
the budget — or any non-network exception — falls through to the
unchanged fail-safe (kill switch + disarm + raise). The kill switch
still fires on genuine faults; it just stops false-firing on noise.

Transient = `requests`/`urllib3` connection/timeout errors, builtin
`ConnectionError`/`TimeoutError`, `socket.gaierror`. Broker `APIError`
and HTTP non-2xx responses are deliberately **not** transient.

### 2. Honest exit-check note — `apps/api/app/services/exit_monitor.py`

`run_exit_check` appended "execution is locked by
`INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=false`" whenever a signal existed
but `execution_allowed` was false. The read-only `/api/risk/exit-check`
route always passes `execute=False`, so the dashboard exit panel showed
that note even though `ALLOW_EXITS` is actually `true` — telling the
operator their config is wrong when it is not. The note now reports the
real cause: the `ALLOW_EXITS=false` message only when the flag is
genuinely false, otherwise "this is a read-only preview — the autopilot
loop submits exits, not this endpoint." Display copy only; no exit
logic changed.

`pytest -q` → **120 passed** locally after both changes.

## Session posture

Autopilot is exit-only and healthy. Nothing is near a stop. MSFT was the
only live exit candidate (small-win) and it slipped below its trigger
after the open, so it is simply held. SPY (−1.6%) is the lot to watch;
its $727.38 app-stop is ~0.9% below current and the loop will sell it
with **no PDT cost** (multi-day hold) if it gets there. Quiet day
expected.

## Honest note — 12-minute coverage gap

The loop came back up at 09:42, 12 minutes after the 09:30 open — the
market opened while the pre-open analysis was still in progress. During
that window there was no automated coverage. No *protective* exit was at
risk: every stop was ≥0.9% away, and the only live signal was MSFT's
*opportunistic* small-win (~$0.16), which had already lapsed as MSFT
slipped below its trigger. Net cost ≈ zero. Process lesson: when the
protective loop is found down at or near the open, restore it first and
refine second.

## Arming ramp — unchanged

Entries stay off. The path to entries (growth) is still the deliberate
ramp from the 2026-05-18 EOD doc:

1. **Verify (today):** one clean exit-only session on an honest,
   restarted dashboard.
2. **First attended entry (target May 20):** review the entry-sizing
   knobs first — `apps/api/.env` runs
   `CASH_RESERVE_PERCENT_OF_PORTFOLIO=0.02` and
   `MAX_BUYING_POWER_UTILIZATION_PER_TRADE=0.9`, both hotter than the
   documented 10% / 50% defaults (at ~$49.8 NAV that sizes one entry
   near 25% of the account and reserves only ~$1). Then run
   `npm run autopilot:once` and watch one supervised tick place one
   entry.
3. **Unattended entries:** only after the attended entry looks correct.

Honest growth context: under PDT rules a sub-$25k account compounds on
swing trades, not day-trading; with ~$26 cash it can hold ~2 new swing
positions. The largest growth lever is added capital — the autopilot's
job is to compound it safely.

## For Codex

- **The working tree was already dirty before this session — please
  reconcile and close it out.** `git status` shows 17 modified files
  plus untracked `docs/eod-2026-05-18.md` and
  `docs/handoff-2026-05-18.md`. That is the 2026-05-18 session (IWM 404
  fix, sell-by-dollars, hydration fix, sell-path tests) and later work
  (`get_defragmentation_report` stale-laggard logic, `ai_scorer.py`,
  `local_worker.py`, dashboard visuals) that was never committed — the
  latest commit is still `069a9ba`. `pytest -q` → **120 passed** on the
  whole tree, so it is test-green, but the repo has drifted from its
  last commit and needs a closeout.
- **My changes this session, isolated from that pile:**
  - `apps/api/app/services/autopilot.py` — loop resilience. The entire
    file diff is mine.
  - `apps/api/app/services/exit_monitor.py` — **only** the exit-check
    note block (~line 177). The `get_defragmentation_report`
    stale-laggard hunk lower in the same file is pre-existing, not mine.
  - `CHANGELOG.md` — new `2026-05-19` section at the top.
  - `docs/premarket-2026-05-19.md` — new (this doc).
- **Running processes vs. code:** the loop (pid 531004) was relaunched
  *after* the `autopilot.py` edit, so the live loop has the resilience
  fix. The API (pid 517800, started 08:37 ET) predates both edits. A
  normal build/restart picks them up; no urgent mid-session restart is
  needed for trading correctness.
- **Follow-through completed after this handoff:** loop classifier tests
  and audit-log tailing regression tests were added. The hot dashboard
  endpoints now use bounded JSONL tail readers instead of reparsing the
  full runtime logs on every request.
- **Measured API latency after the audit-store follow-up:** direct local
  checks on the rebuilt API returned
  `/api/performance/history` ≈ `0.15s`,
  `/api/performance/symbol-history` ≈ `0.15s`,
  `/api/performance/daily-recap` ≈ `0.62s`, and
  `/api/safety/status` ≈ `2.15s`.
- **Web validation follow-through:** production build is green and
  `lint:web` now runs non-interactively from a committed ESLint flat
  config instead of dropping into the old `next lint` setup wizard.
- Still-open prior items from `docs/handoff-2026-05-18.md` remain:
  stale `low_nav_max_open_positions` CHANGELOG line, dead
  `INVESTMENT_APP_MAX_LIVE_TRADES_PER_DAY` env var, `exit_signal_locked`
  heartbeat suppression.
- Housekeeping (not urgent): `.runtime/order-events.jsonl` (~97 MB) and
  `portfolio-snapshots.jsonl` (~80 MB) are large; consider rotation.
