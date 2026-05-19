## Why

The autopilot currently enters the trading day with no qualitative thesis behind any candidate — the deterministic scorer ranks setups on math (spread, depth, regime, structure) but nothing carries a catalyst, a sector view, or a written reason-to-trade into the queue. Performance has been weak and the operator's read is that we are reacting to whatever the scorer surfaces at 9:30 instead of arriving with a plan. We also do not want to burn paid Claude/OpenAI quota at the open to "think" — research is cheaper and better done the night before in a Claude session.

## What Changes

- Introduce a **pre-market brief artifact** authored by Claude (and reviewed/edited by Codex) the evening before each session, containing researched candidates with thesis, catalyst, entry zone, stop, target, strategy lane, and conviction.
- The artifact ships as **two files per day**: a machine-readable `data/premarket/YYYY-MM-DD.json` consumed by the autopilot and a human `data/premarket/YYYY-MM-DD.md` write-up the operator can read.
- Autopilot loads the brief at startup and treats listed tickers as a **priority seed list with a conviction boost** in the deterministic scorer. Existing risk gates (PDT, spread, depth, regime, stop distance) still gate execution — the brief never bypasses them.
- If no brief exists for the session date, the autopilot logs a warning and falls back to today's pure-scorer behavior. No brief never means broken autopilot.
- The dashboard exposes a `/premarket` (or surfaces inside `/strategies`) view showing the active brief: tickers, theses, levels, and which ones the autopilot has acted on so far.

## Capabilities

### New Capabilities
- `premarket-brief`: schema, on-disk format, loader, and validation for the daily brief artifact (JSON + MD pair).
- `brief-aware-scoring`: deterministic scorer extension that applies a priority-seed boost to briefed tickers and attaches the brief's thesis/levels to candidate records so they flow through to execution logs and the dashboard.

### Modified Capabilities
<!-- No existing specs in openspec/specs/ yet; nothing to delta. -->

## Impact

- Code:
  - `apps/api/app/services/` — new `premarket_brief.py` loader + validator.
  - `apps/api/app/services/risk_engine.py` and the scorer path — read brief, apply seed/boost, attach thesis metadata.
  - `apps/api/app/worker.py` and `local_worker.py` — load brief at session start, log presence/absence, emit telemetry.
  - `apps/api/app/api/routes.py` — add a read endpoint exposing the active brief to the web dashboard.
  - `apps/web/` — add a brief view (route or panel) labeled clearly as scenario/plan, not promise.
- Data:
  - New directory `data/premarket/` (gitignored for daily files, schema + example checked in).
- Workflow:
  - Claude evening session authors the JSON+MD pair; Codex validates with `npm run premarket:validate` (new script) and commits the MD note.
- Risk:
  - Real-money sensitive. The change must preserve deterministic risk gates, kill switch, PDT guard, and spread guards. The brief is *advisory input*, not an override.
