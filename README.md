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
