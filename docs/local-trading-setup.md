# Local Trading Setup

## Confirmed Starting Choices

- Broker target: Alpaca
- Current Alpaca status: live account connected and verified locally
- Account currency: USD
- Worker location: local machine
- AI provider: OpenAI now, Anthropic/Claude planned after execution safety is stable
- First symbols: `SPY`, `QQQ`, `NVDA`, `TSLA`, `AAPL`
- Starter capital target: `$10`

## Current Reality Check

- This repo is now being prepared for real live trading, starting with tiny attended orders.
- Use active broker checks and reconciliation before every live cycle.
- Keep the notional size tiny until persistence, duplicate checks, kill switch behavior, and market-hours guards have been verified repeatedly.

## Starter Guardrails

The current defaults are intentionally strict:

- max `$2` notional per trade
- max `1` open position
- max `3` live trades per day
- pause if realized daily loss reaches `$2`
- live trading disabled unless explicitly enabled
- outside-market-hours queueing disabled unless explicitly enabled
- duplicate live order detection enabled for the active strategy/order shape

These values live in `apps/api/.env.example` and are loaded by `app.core.config`.

## Secret Handling

Do not commit API keys.

The repository ignores `.env` files. Create `apps/api/.env` from `apps/api/.env.example` and fill in local values there.

Any key pasted into a chat, screenshot, shared document, or issue should be rotated before use. Treat it as exposed even if the repo never commits it.

## Safe Local Worker

## Daily Dashboard Flow

Start the backend first:

```bash
cd /home/cresp3/automated-investment-app
npm run dev:api
```

In a second terminal, start the dashboard:

```bash
cd /home/cresp3/automated-investment-app
npm run dev:web
```

In a third terminal, start supervised autopilot only when you are ready for
scheduled checks:

```bash
cd /home/cresp3/automated-investment-app
npm run dev:autopilot
```

Use `http://localhost:3000` as the main operating surface:

1. Refresh broker state.
2. Review open orders, positions, buying power, kill switch, and market clock.
3. Cancel queued/open orders before placing anything new when the state is unclear.
4. Enable the kill switch before stepping away.
5. Type `QUEUE OPEN` only when intentionally queueing one regular-session order before market open.
6. Type `RUN LIVE` only when intentionally running one live guarded cycle.

If FastAPI is offline, the dashboard disables live actions and shows a backend warning.

Autopilot rules:

- dashboard `Enable` only arms the state after `ENABLE AUTO`
- `npm run dev:autopilot` must be running for scheduled checks
- the loop waits outside regular market hours by default
- the loop uses the same risk engine, duplicate-order checks, market-hours guard, and kill switch
- the loop enables the kill switch and disables itself on runtime errors
- use `npm run autopilot:status` and `npm run autopilot:once` for diagnostics

`Queue For Open` is not an extended-hours trading feature. It keeps the normal
regular-session market order path and uses the broker queue while regular market
hours are closed. True extended-hours execution should be added later as a
separate limit-order workflow because Alpaca requires extended-hours equity
orders to be limit orders.

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

Run a read-only check against the active broker configuration:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --check-broker
```

Fetch active broker account, order, and position state:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --reconcile-broker
```

Show local audit, kill-switch, and market-clock state:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --safety-status
```

Block future submissions locally:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --enable-kill-switch "Pausing after live test order review"
```

Cancel all currently open orders on the active broker configuration:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --cancel-open-orders
python -m app.worker --reconcile-broker
```

Queue one guarded regular-session order while the regular market is closed:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --queue-for-open
```

Supervised autopilot diagnostics:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --autopilot-status
python -m app.worker --enable-autopilot "Testing supervised checks"
python -m app.worker --autopilot-once
python -m app.worker --autopilot-loop
```

The local audit trail is written under `.runtime/` and should remain uncommitted.

The current worker performs:

1. local demo market event
2. deterministic `micro_breakout_v1` evaluation
3. OpenAI score if an API key is configured
4. deterministic risk review
5. broker receipt, local paper unless live mode and live permission are both enabled

It does not submit to Alpaca unless:

1. `INVESTMENT_APP_TRADING_MODE=live`
2. `INVESTMENT_APP_ALLOW_LIVE_TRADING=true`
3. Alpaca credentials are configured

## Live Trading Readiness

Before increasing size, frequency, or autonomy, verify:

- broker account status confirmation
- order reconciliation from Alpaca back into portfolio state
- explicit kill switch endpoint
- persistent order and fill storage
- market-hours guard behavior
- duplicate-order prevention
- manual review of early live order payloads

Current live-readiness status:

- active broker read and reconciliation commands exist
- local JSONL audit storage exists for runs, order events, and reconciliation snapshots
- operator kill switch exists locally and through the API
- duplicate same-strategy open-order checks run before live submission
- market-clock guard blocks outside-hours queueing unless explicitly enabled
