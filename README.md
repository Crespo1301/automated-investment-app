# Automated Investment App

Internal trading and portfolio-management scaffold for future automation work.

## Role In The Business

- This repo is an internal product lane, not a front-line client acquisition surface.
- It is useful for long-term product ambition, but it ranks below `Portfolio/`, `highvolume_CRM/`, and maintained client sites in the weekly CSolutions workflow.
- Live trading stays disabled unless explicitly approved.

## Shared Docs

- `CLAUDE.md`
- `AI-WORKFLOW.md`
- `SECURITY-CHECKLIST.md`
- `openspec/config.yaml`
- `docs/architecture.md`
- `docs/passthroughs.md`
- `docs/local-trading-setup.md`

## Current Scope

This scaffold includes:

- `apps/api`: FastAPI service for market data, signals, risk, and execution intent
- `apps/web`: Next.js dashboard shell for visibility and operator controls
- `docs/`: architecture, handoffs, and local operating notes

## Product Principles

1. AI can help rank and contextualize trade candidates.
2. Deterministic risk rules remain the final gate before order placement.
3. Major handoffs must be documented and auditable.
4. Paper and live flows should stay as close as possible.

## Local Development

## Daily Dashboard Usage

Run the app with two local servers:

1. Start the FastAPI backend from `apps/api`.
2. Start the Next.js dashboard from the repo root.
3. Open the dashboard and use the Daily Usage panel instead of routine CLI commands.

Backend:

```bash
cd /home/cresp3/automated-investment-app
npm run dev:api
```

Dashboard:

```bash
cd /home/cresp3/automated-investment-app
npm run dev:web
```

Optional supervised autopilot loop:

```bash
cd /home/cresp3/automated-investment-app
npm run dev:autopilot
```

Quick API check:

```bash
npm run check:api
```

Morning readiness check:

```bash
npm run morning:status
```

Then open `http://localhost:3000`. If the dashboard says `Backend API offline`, the
FastAPI process is not running on `127.0.0.1:8000`.

Daily operator flow:

1. Refresh broker state.
2. Review account value, buying power, open orders, positions, kill switch, and market clock.
3. Cancel queued/open orders when needed before placing anything new.
4. Enable the kill switch before stepping away or changing settings.
5. Use `Queue For Open` only when the regular market is closed and you intentionally type `QUEUE OPEN`.
6. Use `Run One Cycle` only when the API is online, the market/session state is acceptable, and the confirmation field is typed exactly as `RUN LIVE`.
7. Use position-level `Sell` only during regular market hours after typing `SELL SYMBOL`.

The dashboard is an operator console, not a set-and-forget trading bot. Keep early
live usage attended and tiny while the app is still building persistent history,
review tools, and safer automation.

Autopilot is now a supervised local loop:

- Dashboard **Enable** only arms the state after you type `ENABLE AUTO`.
- `npm run dev:autopilot` must be running for scheduled checks.
- The loop waits outside regular market hours by default.
- Entry execution is locked by default with `INVESTMENT_APP_AUTOPILOT_ALLOW_ENTRIES=false`.
- Exit execution is locked by default with `INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=false`.
- Keep entry execution locked until exit checks have been observed and intentionally enabled.
- Synthetic demo-market entries are blocked by default with `INVESTMENT_APP_ALLOW_DEMO_LIVE_ENTRIES=false`.
- The loop disables itself and enables the kill switch if a runtime error occurs.
- Use `npm run autopilot:status` and `npm run autopilot:once` for diagnostics.

The dashboard Protection Plan is read-only. It shows whether current positions
appear to have an open sell order and suggests a starter stop review level, but
it does not submit protective orders yet.

The dashboard Exit Signals panel is also read-only unless
`INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=true`. It checks regular-hours positions
against `INVESTMENT_APP_AUTOPILOT_STOP_LOSS_PERCENT` and
`INVESTMENT_APP_AUTOPILOT_TAKE_PROFIT_PERCENT`, then uses a market sell to close
the position only when exit execution is explicitly enabled.

Recommended morning modes:

- **Watch Mode**: API, dashboard, and autopilot armed, with entries/exits locked.
  Use this when validating behavior or manually queueing/running one cycle.
- **Exit-Managed Mode**: turn on `INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=true`, keep
  entries locked, and observe exit signals before allowing autonomous buys.
- **Autonomous Entry Mode**: only after exit checks are verified, turn on both
  `INVESTMENT_APP_AUTOPILOT_ALLOW_EXITS=true` and
  `INVESTMENT_APP_AUTOPILOT_ALLOW_ENTRIES=true`, then wire real market data before
  allowing live entries.

The Live Performance panel refreshes every 15 seconds through a same-origin web
proxy and charts local broker reconciliation history. It reflects snapshots the
app has recorded locally, not a guarantee of future returns.

The watchlist is controlled by `INVESTMENT_APP_ALLOWED_SYMBOLS`. The default
example includes broad ETFs and large liquid names, but every symbol should be
treated as an operator-approved universe, not an automatic recommendation.

`Queue For Open` does not turn on extended-hours trading. It submits the same
regular-session day market order path through the existing risk gate while the
regular market is closed. True pre-market or after-hours execution should use a
separate limit-order path with explicit extended-hours controls.

### API

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

Run one local paper pipeline cycle:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker
```

### Web

```bash
npm install
npm run dev:web
```

Useful build commands:

```bash
npm run build:web
npm run lint:web
npm run graph:build
npm run graph:status
npm run spec:list
npm run spec:validate
```

Useful live-operator commands:

```bash
cd apps/api
source .venv/bin/activate
python -m app.worker --check-broker
python -m app.worker --reconcile-broker
python -m app.worker --safety-status
python -m app.worker --enable-kill-switch "reason"
python -m app.worker --cancel-open-orders
python -m app.worker --queue-for-open
python -m app.worker --autopilot-status
python -m app.worker --enable-autopilot "reason"
python -m app.worker --autopilot-once
python -m app.worker --autopilot-loop
```

## Environment Notes

- `apps/web` reads `INVESTMENT_WEB_API_BASE_URL`, defaulting to `http://127.0.0.1:8000`
- start the API before the dashboard if you want live paper-account data
- Alpaca verification or account funding does not imply permission to trade live from this repo
- do not enable `INVESTMENT_APP_ALLOW_LIVE_TRADING=true` without explicit approval
- use `python -m app.worker --check-alpaca` and `python -m app.worker --reconcile-alpaca` before any discussion of live execution
- use `python -m app.worker --check-broker` and `python -m app.worker --reconcile-broker` for the active paper/live configuration
- local runtime audit files live under `.runtime/` and must not be committed

## Security Notes

Run `SECURITY-CHECKLIST.md` before any deploy or environment change. For this repo, pay special attention to broker keys, outbound execution controls, and preventing unsafe transitions from paper to live flows.
