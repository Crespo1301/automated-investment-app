# Changelog

## Unreleased - 2026-05-28 Claude pre-market defrag

Claude pre-market session. No application code changes — operations
script + handoff only. Account is essentially fully deployed ($0.29
buying power) and four lots flagged by `/api/risk/defragmentation-candidates`
are >24h old, so they can be recycled without a PDT slot.

### Added

- `scripts/morning_defrag_2026-05-28.sh` — one-shot pre-open script
  (launched via nohup) that polls `/api/safety/status` for market open,
  then submits `sell-market?percent=100` for EL, MDT, and NFLX. Expected
  to free ~$8.40 of buying power for the autopilot's regime-aware
  fallback to redeploy intraday. XLE was deliberately excluded after
  S&P futures opened −0.3% on fresh Middle East attacks (XLE is the one
  defensive bid into the 8:30 ET PCE print today); its structural exit
  thesis is deferred to next week.
- `docs/handoff-2026-05-28.md` — Claude → Codex handoff with the run
  state, the explicit no-touch list (QQQ, SPY, NVO, PFE, XLF), market
  context, and follow-up checklist.

## Unreleased - 2026-05-19 EOD

Claude end-of-day pass. No code changed today; documentation only.
Full session-level review in `docs/eod-2026-05-19.md`.

### Notes

- First full session with autonomous entries enabled since the
  05-18 stale-config finding was resolved. Autopilot ran 261
  pipeline cycles and submitted 6 live orders (5 ORB, 1 VWAP
  reclaim). Account NAV $49.92 → $50.01 (+$0.09, +0.18%). Net
  unrealized across the 8-name book closed essentially flat
  (−$0.01). PDT 1/3 used.
- Provider usage was 100% local fallback for the second straight
  day. The deterministic scorer produced a flat-to-up day on its
  own; no near-term need to top up paid AI quota.
- EOD posture: kill switch ON (operator-paused from dashboard),
  autopilot still armed with entries and exits enabled. The loop
  will resume tomorrow only after the kill switch is cleared.

### Docs

- Archived stale dated session docs into `docs/archive/`:
  `eod-2026-05-18.md`, `handoff-2026-05-18.md`,
  `premarket-2026-05-19.md`.
- Added `docs/eod-2026-05-19.md` with the session review,
  next-day decisions, and archive notes.

## Unreleased - 2026-05-19 Claude pre-market patch

Claude pre-market pass. The autopilot loop was found dead this morning:
overnight (17:40 ET, 2026-05-18) it hit a transient DNS-resolution
`ConnectionError` — almost certainly the WSL host sleeping — and
`run_autopilot_loop` treated that infrastructure blip as fatal, tripping
the kill switch and exiting the process. That left the 5 open positions
with no automated exit coverage. Exit-only autopilot was restored at
09:42 ET and the loop hardened against a repeat. Codex: review, run
backend tests + web build, then push.

### Fixed

- The autopilot loop no longer permanently disables itself on a
  transient network error. `run_autopilot_loop` now classifies the
  exception: a transient network blip (DNS failure, dropped connection,
  timeout — `requests`/`urllib3` connection/timeout errors, builtin
  `ConnectionError`/`TimeoutError`, `socket.gaierror`) is retried for up
  to `_TRANSIENT_ERROR_RETRY_BUDGET` (6) consecutive ticks while the
  loop stays armed, surfaced as a `transient_network_retry:n/6`
  heartbeat. Only an outage that persists past that budget — or any
  non-network exception — still trips the unchanged fail-safe (kill
  switch + disarm + raise). The kill switch keeps firing on genuine
  faults; it no longer false-fires on infrastructure noise and kills
  exit protection for the rest of a session.
- `/api/risk/exit-check` no longer mislabels its read-only preview. The
  exit monitor appended "execution is locked by
  `INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=false`" whenever a signal could
  not execute, but the read-only route always passes `execute=False`,
  so the dashboard exit panel showed that note even when `ALLOW_EXITS`
  is `true`. The note now reports the real cause — the `ALLOW_EXITS`
  message only when the flag is genuinely false, otherwise a "read-only
  preview" note. Display copy only; no exit logic changed.
- The dashboard audit/performance endpoints no longer full-scan the
  large append-only runtime logs on every request. `audit_store.py` now
  uses bounded JSONL tail readers and line counters for recent history,
  daily recap, and safety/audit summaries, cutting local endpoint
  checks from multi-second/full-log scans down to sub-second reads for
  the performance endpoints and low-single-digit seconds for the safety
  snapshot.
- The web lint command is now repo-owned and non-interactive. The
  project has a committed ESLint flat config and `apps/web` now runs
  `eslint .` instead of dropping into the deprecated `next lint` first-
  run wizard.
- The dashboard now includes a dedicated live-arming checklist powered by
  `/api/trading/morning-readiness`. It shows whether entries are truly
  ready, surfaces blockers such as stale loaded config vs `.env`, and
  explains the next operational step instead of leaving the operator to
  decode `entry_execution_locked` from a raw heartbeat string.

### Safety Notes

- Exit-only autopilot was re-armed and the loop relaunched after a
  transient-error auto-disable; entries remain OFF
  (`INVESTMENT_APP_AUTOPILOT_ALLOW_ENTRIES=false`). The kill switch was
  cleared because it had tripped on a network blip, not a trading or
  risk event. No `.env` or risk-gate values were changed.
- No trading logic, scorer, risk-gate math, sizing, or exit decision
  logic changed — only loop error-handling and one operator-facing note
  string.
- Operational note after the follow-up: if the heartbeat still shows
  `entry_execution_locked`, check the **loaded process state**, not just
  `.env`. On 2026-05-19 the local `.env` had live mode, live permission,
  live Alpaca, and both autopilot entry/exit flags enabled, but the
  persisted runtime state still reported `entry_execution_enabled:
  false` because the API/loop had not been restarted after the config
  change. Live entries require an API restart, autopilot re-arm, and a
  fresh `--morning-readiness` / `--autopilot-status` check showing
  `ready_for_autonomous_entries: true` and `entry_execution_enabled:
  true`.

### Codex Handoff

- Files touched: `apps/api/app/services/autopilot.py`,
  `apps/api/app/services/exit_monitor.py`, `apps/api/app/services/audit_store.py`,
  `apps/api/tests/test_audit_store_and_autopilot.py`,
  `apps/web/eslint.config.mjs`, `apps/web/package.json`,
  `apps/web/components/analytics-visuals.tsx`, `package-lock.json`,
  `CHANGELOG.md`, `docs/premarket-2026-05-19.md`.
- Validation: `pytest -q` → 123 passed locally, `npm run build:web` →
  passed, `npm run lint:web` → passed.
- The live loop (relaunched 09:42 ET) already runs the resilience fix;
  the API server predates both edits. A normal build/restart picks them
  up — see the briefing doc.
- See `docs/premarket-2026-05-19.md` for full context and the
  still-open items carried from the 2026-05-18 handoff.

## Unreleased - 2026-05-18 Claude session patch

Claude pre-market + intraday session. Operator hit a confusing "404 Not
Found" when manually selling IWM from the dashboard. Root cause: the IWM
lot is worth $0.98, just under the $1.00 `minimum_order_notional` guard,
so `submit_position_market_sell` raised a guard `ValueError` that the
route blanket-mapped to HTTP 404 — hiding the real reason from the
operator. Codex: please review, run backend tests + web build, then
push.

### Fixed

- Manual broker sell/protect endpoints no longer report guard rejections
  as `404 Not Found`. Added `PositionNotFoundError` (a `ValueError`
  subclass) raised only when a symbol genuinely has no open long
  position. `POST /api/broker/positions/{symbol}/sell-market` and
  `/protect-oco` now return `404` only for that case and `409 Conflict`
  for guard rejections on an existing position (sub-minimum notional, an
  open sell already pending, partial-sell rounds to zero). The
  informative detail string now reaches the dashboard with a status code
  that matches the market-closed / PDT rejections alongside it.
- Web root layout: `<body suppressHydrationWarning>` to silence a benign
  React hydration mismatch caused by browser extensions (Grammarly)
  injecting `data-gr-ext-installed` / `data-new-gr-c-s-check-loaded`
  attributes before hydration. Element-scoped only — genuine markup
  drift elsewhere is still reported.

### Added

- Sell a position by **dollar amount** from the dashboard. Alpaca's
  position-sell API only accepts a share `qty`, so
  `submit_position_market_sell` now takes an optional `dollars` argument
  (mutually exclusive with `percent`) and converts it to shares against
  live market value: `qty = quantity * dollars / market_value`. A
  `dollars` value at or above the position's market value sells it
  whole. `POST /api/broker/positions/{symbol}/sell-market` accepts
  `?dollars=`; the dashboard sell control is now a dollar input
  (placeholder shows the max sellable value) instead of a percent
  dropdown. `percent` remains supported for programmatic callers.
- Partial-sell **remainder guard**. Any partial sell (dollars or
  percent) that would leave a lot below `minimum_order_notional` ($1.00)
  is now rejected with a message telling the operator to sell the full
  position instead — stops the dashboard from creating new stranded
  sub-minimum lots like the $0.98 IWM lot.

### Changed

- `apps/api/.env`: `MAX_OPEN_POSITIONS` `25 → 8`. On a ~$49 NAV account a
  cap of 25 guarantees fragmentation into sub-$3 lots; 8 restores the
  `max_open_positions` risk gate as a real fragmentation brake. Inert
  until autopilot is re-armed; requires an API restart to load.

### Removed (CHANGELOG correction)

- The "Low-NAV fragmentation guard in the risk gate" entry in the
  `2026-05-13 EOD patch` section below is **inaccurate** — that guard was
  reverted in commit `069a9ba` (2026-05-14). `low_nav_max_open_positions`
  is now an inert setting; `max_open_positions` is the live brake.
  Codex: decide whether to delete the setting or re-add NAV-scaled
  enforcement, then clean up that stale "Added" line.

### Codex Handoff

- Files touched: `apps/api/app/services/broker_adapter.py`,
  `apps/api/app/api/routes.py`, `apps/web/app/page.tsx`,
  `apps/web/app/layout.tsx`, `apps/api/.env` (local-only),
  `CHANGELOG.md`, `docs/handoff-2026-05-18.md`.
- No trading logic, scorer, risk-gate math, or exit logic changed —
  status-code mapping, the dollars→shares sell conversion + remainder
  guard, and a hydration attribute.
- Suggested checks: backend tests, `npm run build:web`,
  `npm run lint:web`, then commit/push/release.
- See `docs/handoff-2026-05-18.md` for the full context and open items.

## Unreleased - 2026-05-13 EOD patch

Joint Claude/Codex EOD review of the May 13 session. Both passes agreed
the system is finding signals but the account is too fragmented and
cash-starved for those signals to matter cleanly. Day's lesson: a small
NIO same-day win burned a PDT slot that F later needed for its +$0.30
take-profit, which then locked the loop.

### Added

- Low-NAV fragmentation guard in the risk gate. While portfolio value is
  at or below `INVESTMENT_APP_LOW_PORTFOLIO_THRESHOLD`, the engine
  rejects new entries once `INVESTMENT_APP_LOW_NAV_MAX_OPEN_POSITIONS`
  (default 4) names are already open, regardless of buying power. Stops
  the loop from accumulating sub-$3 lots whose spread and PDT slot cost
  dominate signal edge.
- Profit-locked carry handling. When a take-profit signal is blocked by
  the PDT day-trade guard, the position is persisted to
  `.runtime/profit-locks.json` and surfaced via
  `/api/risk/profit-locks`. Subsequent ticks recognize the lock and stop
  spamming `exit_signal_locked` heartbeats; the operator sees the
  position as a single next-session priority exit instead.
- Morning defragmentation report at `/api/risk/defragmentation-candidates`.
  Lists positions at or below
  `INVESTMENT_APP_DEFRAGMENTATION_MAX_MARKET_VALUE_DOLLARS` (default
  $3.00) whose buy fill is older than the small-win min holding window,
  so liquidating them does not consume a PDT slot. Read-only; the
  operator decides whether to act.
- New `ProfitLockEntry`, `ProfitLockReport`, `DefragmentationCandidate`,
  and `DefragmentationReport` domain models.

### Changed

- Same-day small-win exit threshold is now spread-aware and NAV-aware.
  At low NAV, the estimated *net* profit must clear
  `INVESTMENT_APP_LOW_NAV_SMALL_WIN_MIN_NET_PROFIT_DOLLARS` (default
  $0.18) before a PDT slot is spent. Stops the system from burning
  scarce day-trades on $0.10 gross wins that go negative after spread.
- Exit-monitor blocked-reason copy now reports the active net-profit
  floor in dollars so the audit row explains why a small win was held.
- Dashboard CSS retuned for a broker-console look: removed body
  radial-gradient wash, ticker-bar/trading-action linear gradients,
  chart-line drop-shadow glow, status-dot/PDT-cell soft glows, and
  inline-form focus halo. Panels, lists, and tables now sit on flat
  solid panels with 2-3px corners. Equity chart area fill is a single
  flat translucent green instead of a vertical gradient.

### Safety Notes

- The autopilot stays disabled and the kill switch on at EOD. Before the
  next open, reconcile the broker, then arm autopilot only after
  buying power is meaningful and the profit-lock carry queue is clear.

## v0.2.0 - 2026-05-08

Week-close live trading foundation release.

### Added

- Broader equity universe with rotating per-cycle scan windows.
- High-upside momentum lane with stricter spread, market-regime, news, volume, stop, and take-profit controls.
- Alpaca market-context enrichment for spread, top-of-book depth proxy, volatility regime, broader SPY/QQQ regime, and recent headline sentiment.
- Dashboard-wide broker-state auto-refresh that pauses while the tab is hidden.
- Portfolio live price board with current price, average entry, position value, quantity, unrealized P&L, and snapshot timestamp.
- Options Level 1 foundation for covered calls and cash-secured puts:
  - option domain models
  - deterministic covered-call and cash-secured-put strategy lanes
  - Level-aware options risk gate
  - options guardrail settings
  - 13 focused options tests

### Changed

- Entry sizing now preserves a portfolio-scaled cash reserve and caps per-trade buying-power utilization.
- Wide-spread equity entries are blocked by the risk gate instead of only being penalized by scoring.
- High-upside confidence scoring leaves room between threshold setups and genuinely strong setups.
- Recent-volume ratio calculation now reports true recent volume divided by average recent volume.
- Documentation now reflects Claude/Codex shared review responsibility over both UI and trading logic.

### Safety Notes

- Options trading remains disabled by default with `INVESTMENT_APP_OPTIONS_ENABLED=false`.
- Alpaca Level 1 options only supports covered calls and cash-secured puts. Long calls/puts remain blocked until Level 2 approval.
- At the current tiny account size, Level 1 options candidates are expected to skip because covered calls require 100 shares and cash-secured puts require full strike collateral.
- Live trading paths remain gated by kill switch, live-mode permission, spread guards, PDT guard, minimum-notional checks, duplicate-entry prevention, and cash reserve sizing.

### Validation

- API tests: `72 passed`
- Web build: `npm run build:web` passed
- Diff hygiene: `git diff --check` passed
