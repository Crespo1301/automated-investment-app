# Inputs Needed From You

These decisions will let us move from scaffold to a working autonomous trading system.

## 1. First Broker

Choose the first execution target:

Confirmed: Alpaca.

Confirmed:

- Alpaca account is approved.
- Live API keys are configured locally only.
- Tiny live-capital testing has started.

## 2. Asset Universe

The default universe is now ~145 symbols spanning broad ETFs, sector and
thematic ETFs, mega caps, semis, software, fintech, financials, healthcare,
energy, consumer, industrials, comms, EVs, ADRs, and speculative names. The
canonical list lives in `DEFAULT_ALLOWED_SYMBOLS` in
`apps/api/app/core/config.py`. Override via the `INVESTMENT_APP_ALLOWED_SYMBOLS`
environment variable.

Because the universe is wider than what a single tick can scan, the worker
rotates through buckets of `INVESTMENT_APP_MAX_SYMBOLS_PER_CYCLE` symbols
(default 90) per cycle. Two buckets cover the full universe at the default
30-second tick.

## 2b. Options Trading (Level 1)

Alpaca approved options Level 1 on this account. Level 1 permits only:

- **Covered calls** (`covered_call_v1`) — sell calls against ≥100 owned shares.
- **Cash-secured puts** (`cash_secured_put_v1`) — sell puts backed by cash.

Long calls/puts require Level 2; multi-leg spreads require Level 3.

### Foundation status
- Domain types (`OptionContract`, `OptionsTradeCandidate`, `OptionsRiskDecision`,
  `OptionsExecutionIntent`, `OptionsRiskLimits`) live in
  `apps/api/app/domain/trading.py`.
- Strategy lanes are in `apps/api/app/services/options_strategy.py`. They
  consume an `OptionsChainSnapshot` and emit candidates only when liquidity,
  DTE, OI, and premium-yield gates all pass.
- Level-1 enforcement and collateral checks live in
  `apps/api/app/services/options_risk.py:OptionsRiskGate`. The
  `LEVEL_PERMISSIONS` table is the single source of truth for what each
  level allows; updating it to flip Level 2 on later is a one-line change.
- 13 tests in `apps/api/tests/test_options_pipeline.py` cover Level-1
  enforcement, both lanes, liquidity gates, and small-account skip.

### What is intentionally NOT yet wired
- Alpaca options chain fetcher in `broker_adapter.py` — needs the live
  options endpoint and paper-account testing. Codex round when ready.
- AI scoring path for options. The local fallback today only knows equity
  candidates; an options-aware scorer is its own design pass.
- Dashboard surface for options posture, eligible underlyings, options
  orders. Held back until at least one paper options trade has been wired
  end-to-end.

### Knobs (env-overridable)
- `INVESTMENT_APP_OPTIONS_ENABLED` (default `False`) — operator flips on
  when ready to scan.
- `INVESTMENT_APP_OPTIONS_MAX_LEVEL` (default `1`) — flip to `2` when
  Alpaca approves Level 2.
- `INVESTMENT_APP_OPTIONS_ALLOWED_UNDERLYINGS` — defaults to a liquid
  mega-cap subset.
- `INVESTMENT_APP_OPTIONS_MIN_OPEN_INTEREST` (default `500`).
- `INVESTMENT_APP_OPTIONS_MAX_BID_ASK_SPREAD_PERCENT` (default `0.05`).
- `INVESTMENT_APP_OPTIONS_TARGET_DTE_MIN` / `_MAX` (default `30` / `45`).
- `INVESTMENT_APP_OPTIONS_MIN_PREMIUM_TO_COLLATERAL_RATIO` (default
  `0.005` = 0.5% of collateral as premium per CC/CSP).
- `INVESTMENT_APP_OPTIONS_MAX_OPEN_CONTRACTS` (default `2`).

### Small-account reality
At the current account size, Level 1 collateral requirements (≥100 shares
for a covered call, strike × 100 cash for a CSP on liquid mega-caps) are
not affordable. The foundation is ready and tested; lanes will simply
return no candidates until the portfolio grows enough — or Level 2 lands
and unlocks long calls/puts which only require premium paid.

## 3. Strategy Scope

Steady-compounder lanes (every funded symbol):

- `micro_breakout_v1`
- `opening_range_breakout_v1`
- `vwap_reclaim_v1`
- `relative_volume_spike_v1`
- `pullback_continuation_v1`

High-upside hunter lane (stricter gates, larger stops/targets):

- `high_upside_momentum_v1`
  - move ≥ `INVESTMENT_APP_HIGH_UPSIDE_BREAKOUT_THRESHOLD` (default 1.2%)
  - recent volume ≥ `INVESTMENT_APP_HIGH_UPSIDE_MIN_RECENT_VOLUME_RATIO` × the recent average (default 3×)
  - quote spread ≤ `INVESTMENT_APP_HIGH_UPSIDE_MAX_SPREAD_BPS` (default 50 bps)
  - market regime must not be `risk_off`; `unknown` blocks unless
    `INVESTMENT_APP_HIGH_UPSIDE_REQUIRE_KNOWN_MARKET_REGIME=False`
  - news sentiment must not be `negative`; `unknown` is allowed unless
    `INVESTMENT_APP_HIGH_UPSIDE_REQUIRE_KNOWN_NEWS_SENTIMENT=True`
  - stop = 4% (`INVESTMENT_APP_HIGH_UPSIDE_STOP_LOSS_PERCENT`)
  - take-profit = 12% (`INVESTMENT_APP_HIGH_UPSIDE_TAKE_PROFIT_PERCENT`)

## 4. Risk Limits

Current live guardrails:

- position size targets `25%` of current portfolio value
  (`INVESTMENT_APP_POSITION_SIZE_PERCENT`)
- per-trade buying-power utilization cap: `50%` of *currently available*
  buying power (`INVESTMENT_APP_MAX_BUYING_POWER_UTILIZATION_PER_TRADE`).
  Prevents the loop from eating 100% of remaining buying power on a single
  trade once a few positions are already open — sizing decays smoothly
  instead of cliffing to zero.
- portfolio-scaled cash reserve: `10%` of current portfolio value held back
  before sizing (`INVESTMENT_APP_CASH_RESERVE_PERCENT_OF_PORTFOLIO`).
  Scales with the account: a $10 portfolio reserves $1, a $1000 portfolio
  reserves $100. Preferred over a fixed dollar floor because the buffer
  doesn't cliff at Alpaca's $1 minimum as the portfolio grows.
- max `6` open positions
- no raw daily trade-count cap
- same-day sells use a PDT guard backed by Alpaca `daytrade_count`
- max `3` day trades in the rolling five-business-day PDT window
- entry quote spread limit defaults to `75 bps` (`max_entry_spread_bps`); the
  high-upside lane is tighter at `50 bps` by default
- do not submit orders below Alpaca's `$1` fractional minimum
- stop trading for the day at the configured realized-loss limit
- live mode is only for tiny attended tests until the operator explicitly expands scope

> ⚠️ Compounding-budget note: the high-upside lane uses a 4% stop. On a small
> account at 25% sizing, a single losing high-upside trade ≈ 1% portfolio
> drawdown. If the daily-loss kill is set near 1% of account value, the
> high-upside lane is effectively one-shot per day before the kill switch
> trips. Tune `INVESTMENT_APP_MAX_DAILY_LOSS` accordingly, or accept this as
> the intended risk budget while the lane is being validated.

## 5. AI Provider

Confirmed priority:

- Claude API first when funded/configured
- OpenAI API second when funded/configured
- deterministic local fallback when provider quota or billing is unavailable

## 6. Operating Preferences

Confirmed direction:

- autonomous within strict limits
- local worker first

Still needed:

- notifications preference
- allowed trading hours
- whether overnight holds are allowed

## 7. Deployment Target

Confirmed: local machine first.

## 8. Data Persistence Priorities

Tell me what matters most from day one.

Possible priorities:

- accurate P&L
- full audit log
- tax-lot history
- strategy replay
- benchmark comparisons
