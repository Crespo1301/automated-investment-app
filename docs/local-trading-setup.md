# Local Trading Setup

## Confirmed Starting Choices

- Broker target: Alpaca
- Current Alpaca status: paper trading account configured in the Alpaca dashboard
- Account currency: USD
- Worker location: local machine
- AI provider: OpenAI
- First symbols: `SPY`, `QQQ`, `NVDA`, `TSLA`, `AAPL`
- Starter capital target: `$10`

## Current Reality Check

- Alpaca approval or funding does not flip this repo into live mode.
- The safe path is still: paper account checks, reconciliation checks, documented guardrails, then a deliberate live-mode task later.
- Until that specific task exists, treat this repo as paper-first.

## Starter Guardrails

The current defaults are intentionally strict:

- max `$2` notional per trade
- max `1` open position
- max `3` live trades per day
- pause if realized daily loss reaches `$2`
- live trading disabled unless explicitly enabled

These values live in `apps/api/.env.example` and are loaded by `app.core.config`.

## Secret Handling

Do not commit API keys.

The repository ignores `.env` files. Create `apps/api/.env` from `apps/api/.env.example` and fill in local values there.

Any key pasted into a chat, screenshot, shared document, or issue should be rotated before use. Treat it as exposed even if the repo never commits it.

## Safe Local Worker

Run:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker
```

Run a read-only Alpaca paper account check:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --check-alpaca
```

This fetches a redacted account status and does not place orders.

Submit one risk-gated demo order to Alpaca paper:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --paper-order
```

This still uses paper mode, the approved watchlist, and the `$2` starter notional.
Do not use this command until the read-only account check succeeds.

Fetch Alpaca paper reconciliation state:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --reconcile-alpaca
```

This returns account status, recent orders, and open positions in a redacted
dashboard-safe shape.

The current worker performs:

1. local demo market event
2. deterministic `micro_breakout_v1` evaluation
3. OpenAI score if an API key is configured
4. deterministic risk review
5. local paper broker receipt

It does not submit to Alpaca unless:

1. `INVESTMENT_APP_TRADING_MODE=live`
2. `INVESTMENT_APP_ALLOW_LIVE_TRADING=true`
3. Alpaca credentials are configured

## Before Live Trading

Before enabling live mode, we still need:

- broker account status confirmation
- order reconciliation from Alpaca back into portfolio state
- explicit kill switch endpoint
- persistent order and fill storage
- manual review of the first live order payload
