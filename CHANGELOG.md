# Changelog

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
