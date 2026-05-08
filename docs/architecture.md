# Architecture

## Objective

Build a personal autonomous trading platform that can:

- monitor live markets
- detect strategy-specific patterns
- use AI to score and contextualize signals
- validate trades against deterministic risk rules
- place broker orders without requiring constant manual supervision
- visualize portfolio state, gains, losses, and system health

## System Boundaries

The project is intentionally split into explicit lanes:

1. Market ingress
2. Feature and signal generation
3. AI scoring
4. Risk validation
5. Execution and reconciliation
6. Portfolio and operator dashboard

Each lane should communicate through versioned contracts rather than direct implicit coupling.

## Initial Service Layout

### `apps/api`

Owns:

- domain models
- API routes
- orchestration surface
- broker adapters
- risk engine
- strategy engine
- AI scoring adapters

### `apps/web`

Owns:

- operator dashboard
- strategy controls
- risk and alert views
- portfolio visualization
- execution audit views

## Execution Philosophy

This system supports autonomous execution, but autonomy is constrained by policy:

- AI may rank or contextualize candidates.
- AI should not be the final authority for position sizing or rule bypass.
- Deterministic controls gate every live trade.
- Paper mode and live mode should preserve the same pipeline shape.

## Planned Back-End Modules

### `market_data`

Responsibilities:

- ingest broker or market provider streams
- normalize raw events
- stamp provenance and timestamps
- publish replayable internal events
- enrich events with quote spread, top-of-book depth proxy, intraday volatility,
  broader market regime, and recent headline context when available

### `strategy_engine`

Responsibilities:

- evaluate predefined strategies
- emit trade candidates
- attach trigger evidence
- respect symbol universe configuration

### `ai_scorer`

Responsibilities:

- add confidence and context
- summarize news or regime factors
- preserve prompt and model provenance
- fail over through Claude, OpenAI, then deterministic scoring that still uses
  available liquidity, volatility, market-regime, and news context

### `risk_engine`

Responsibilities:

- validate size and notional limits
- enforce drawdown and cooldown logic
- reject trades that violate portfolio rules
- produce explicit approval or rejection artifacts

### `broker_adapter`

Responsibilities:

- translate execution intents into broker-native requests
- route to paper or live mode
- track receipts, fills, and rejections
- reconcile broker account state

## First Build Milestones

1. Scaffold dashboard and API contracts
2. Add database schema for accounts, positions, orders, fills, and strategy runs
3. Add Alpaca broker adapter with paper mode
4. Add streaming ingestion and one deterministic strategy
5. Add AI scoring provider behind a narrow interface
6. Add notifications, kill switch, and reconciliation jobs
