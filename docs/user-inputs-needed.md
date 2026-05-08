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

Current approved universe:

- `SPY`
- `QQQ`
- `DIA`
- `IWM`
- `VTI`
- `VOO`
- `SCHD`
- `XLK`
- `XLF`
- `XLV`
- `XLI`
- `XLE`
- `XLP`
- `XLY`
- `SMH`
- `SOXX`
- `AAPL`
- `AMZN`
- `AMD`
- `AVGO`
- `COST`
- `GOOGL`
- `HD`
- `JPM`
- `MA`
- `META`
- `MSFT`
- `NVDA`
- `PG`
- `UNH`
- `V`
- `WMT`
- `XOM`

## 3. Strategy Scope

Current lanes:

- `micro_breakout_v1`
- `opening_range_breakout_v1`
- `vwap_reclaim_v1`
- `relative_volume_spike_v1`
- `pullback_continuation_v1`

## 4. Risk Limits

Current live guardrails:

- position size targets `25%` of current portfolio value
- max `6` open positions
- no raw daily trade-count cap
- same-day sells use a PDT guard backed by Alpaca `daytrade_count`
- max `3` day trades in the rolling five-business-day PDT window
- do not submit orders below Alpaca's `$1` fractional minimum
- stop trading for the day at the configured realized-loss limit
- live mode is only for tiny attended tests until the operator explicitly expands scope

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
