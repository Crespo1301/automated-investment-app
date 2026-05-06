# Inputs Needed From You

These decisions will let us move from scaffold to a working autonomous trading system.

## 1. First Broker

Choose the first execution target:

Confirmed: Alpaca.

Needed from you later:

- paper API keys
- live API keys only when we are ready
- account approval status after review completes

## 2. Asset Universe

Confirmed first universe:

- `SPY`
- `QQQ`
- `NVDA`
- `TSLA`
- `AAPL`

## 3. Strategy Scope

Starter lane selected by default:

- `micro_breakout_v1`

This can be changed after paper testing.

## 4. Risk Limits

Confirmed starter defaults:

- max `$2` notional per live trade
- max `1` open position
- max `3` live trades per day
- stop trading for the day at `$2` realized loss
- paper mode first, then tiny live capital after explicit confirmation

## 5. AI Provider

Confirmed: OpenAI.

Needed from you:

- rotated API key stored in local `.env`
- whether the model is used for scoring only or also for daily summaries

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
