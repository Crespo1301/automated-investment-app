# Changelog

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
