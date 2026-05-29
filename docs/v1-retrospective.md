# v1.0 Retrospective — Pre-Release Audit

Compiled 2026-05-28 EOD. Closes the v1 development cycle and seeds the
v2 ground-up rebuild. The dataset for the final pass closes at the
2026-05-29 EOD; this document is the *first* pass and will be amended
after tomorrow's session.

## Scope of v1.0

A supervised, live-broker (Alpaca) automated trading scaffold for tiny
real-money accounts (~$50). Five intraday strategy lanes feed a risk
gate and either a paid AI scorer (Claude → OpenAI) or a deterministic
local fallback. A dashboard surfaces account state, autopilot status,
exit-readiness, defrag candidates, and a morning-readiness check. The
operator (Carlos) supervises; the autopilot runs continuously when the
kill switch is off and entries are armed.

## Timeline and scale

- **22 days of development** (2026-05-06 → 2026-05-28).
- **47 commits**, single contributor.
- **18 trading sessions** with live fills.
- **132 unique filled broker orders** (68 buys, 64 sells).
- **930 autopilot pipeline runs** recorded.
- **NAV trajectory:** the account ends day 22 at **$50.20** with **8 open positions**, having processed real fills across NVDA, SPY, QQQ, VOO, XLE, XLF, NVO, PFE, F, RIVN, MDT, NFLX, EL, BAC, UNH, AAPL, NEE, VZ, IWM, ARKG, and others.

## What worked

1. **The risk gate.** 92.7% of pipeline runs (862/930) were *correctly
   rejected* before execution. The gate is the most load-bearing
   component in the system and the reason a fractional, leverage-free
   $50 account has not blown up.

2. **The lane architecture.** Five distinct entry strategies actually
   produced fills, with clear attribution via client_order_id prefixes:

   | Lane | Buys | Notional deployed |
   |---|---|---|
   | opening_range_breakout_v1 | 31 | $87.69 |
   | micro_breakout_v1 | 14 | $43.91 |
   | vwap_reclaim_v1 | 9 | $35.81 |
   | pullback_continuation_v1 | 8 | $23.20 |
   | relative_volume_spike_v1 | 6 | $20.78 |

3. **Defrag mechanism.** `/api/risk/defragmentation-candidates`
   correctly identified stuck sub-$3 lots and >48h losing laggards,
   enabling capital recycling without PDT impact. Used successfully
   on 2026-05-28.

4. **Transient-error resilience.** The 2026-05-19 fix that classifies
   network blips (`requests`/`urllib3`/`socket.gaierror`) and retries
   for `_TRANSIENT_ERROR_RETRY_BUDGET = 6` ticks before tripping the
   kill switch resolved the recurring WSL-host-sleep false-fault that
   killed exit protection overnight.

5. **Live broker integration.** Alpaca live mode with fractional
   notional market orders works end-to-end. Manual sells, OCO
   protection, and reconciliation snapshots have all been exercised in
   production.

## Recurring roadblocks

Pulled from rejected-pipeline-runs reason buckets:

| Rejections | Reason bucket | Implication |
|---|---|---|
| 348 (37%) | Open position limit reached | We max out position count because BP is fragmented across many tiny lots |
| 226 (24%) | Daily live trade count cap | Overly conservative cap for the regime; ratchets up rejection rate |
| 106 (11%) | PDT cap (3/3) | 5-day rolling PDT is the dominant ceiling on a sub-$25K account |
| 67  (7%) | Low-NAV fragmentation guard | Partially removed in 069a9ba but still firing |
| 53  (6%) | Local fallback score 0 | Scorer flat-rejects; usually wide-spread or no-volume |

Other recurring patterns:

- **Process bug — ghost script execution (2026-05-28).** A pre-parsed
  bash for-loop survived an in-place file edit and fired an unintended
  XLE sell. Mitigation noted: process-locking + idempotent
  client_order_ids keyed on (date, symbol, intent).
- **Manual exits dominate.** 56 sells under `manual_*` client IDs vs
  effectively 0 autopilot-attributed sells. **Autopilot enters but does
  not exit cleanly.** Exits get triggered by the operator or by the
  defrag scripts.
- **100% local fallback scoring for 2+ days.** Paid Claude/OpenAI quota
  unavailable; deterministic fallback carried scoring. Performed
  acceptably but removes the original AI-first design premise.
- **6 `disabled_by_error` events**, all from Alpaca HTTPS connection
  failures (DNS) caused by WSL host sleep. Transient-retry fix reduced
  but did not eliminate these.

## Code bloat signals

Targets for v2 simplification:

- `apps/api/app/services/broker_adapter.py` — **1382 lines** in one
  file. Holds the local paper broker, the Alpaca broker, position
  sells, OCO protection, options support, and the news client wiring.
  Should be split into transport (Alpaca client), domain operations
  (entries/exits/protection), and pluggable broker interface.
- `apps/api/app/services/ai_scorer.py` — 665 lines. Heavy provider
  fanout (Claude → OpenAI → fallback). Could be a thin strategy
  pattern with one file per provider.
- `apps/api/app/services/local_worker.py` — 661 lines.
- `apps/api/app/services/audit_store.py` — 656 lines for a JSONL
  tailing layer. Replace with SQLite (queryable, indexable,
  compactable).
- `apps/web/components/analytics-visuals.tsx` — **727 lines** for a
  single component. Split per-chart.
- **Tests: 4 files for 7824 backend LOC** (~0.05% file ratio). v2
  should establish baseline coverage targets before code grows.
- **Audit JSONL: 274 MB** (`order-events.jsonl` 151 MB,
  `portfolio-snapshots.jsonl` 123 MB) on a 22-day-old project.
  Rotation/compaction is mandatory before this becomes a real
  production system.

## v2 architectural recommendations (preview, not commitments)

Keep:
- Lane-attributed client_order_ids (great for retro analysis).
- Risk gate as the primary safety mechanism.
- Live-broker integration with fractional notional orders.
- Defrag-driven capital recycling.
- Kill switch + autopilot pause as the two-button safety surface.

Drop / rebuild:
- Single 1382-line broker_adapter — split it.
- JSONL audit store — SQLite + rotation.
- 5 entry lanes that all earn similar P&L — validate edge per lane on
  v1's dataset before re-implementing all five.
- Daily trade cap (we already have PDT and BP guards; the third cap is
  redundant).
- Sub-$3 position creation — minimum lot size should match the
  account's BP, not be a global flag.

Add:
- Idempotent client_order_ids: `f"{date}-{lane}-{symbol}-{intent}"`,
  not random UUIDs. Eliminates the ghost-script bug class.
- Single-process orchestrator with file lock; no parallel runners.
- First-class exit lanes mirroring entry lane structure.
- A real backtest harness (we have 132 fills as ground truth — use
  them).
- Audit log rotation: daily compressed archives, hot tail capped at
  ~10 MB.

## Next-day amendment plan

After 2026-05-29 close:
1. Append the day's order tape + rotation outcome to this doc as a
   final-pass section.
2. Tag the repository `v1.0` once the trading day is closed cleanly.
3. Open the v2 scaffold in a sibling repo (not as a refactor of v1)
   so the v1 record stays immutable as a teaching artifact.
