# Release Notes — v1.0

**Release date:** 2026-05-29

**Repo:** [automated-investment-app](https://github.com/Crespo1301/automated-investment-app)

## What this is

A supervised, live-broker automated trading scaffold for sub-$25K
fractional accounts. Built over 22 days as a "show-the-work" prototype
that takes real fractional orders on a real Alpaca live account, with
an operator-supervised kill switch and a deterministic risk gate as
the primary safety mechanism.

This release is the closing snapshot of v1. Work on v2 begins from
scratch in a sibling effort using the lessons captured in
[`docs/v1-retrospective.md`](docs/v1-retrospective.md).

## What it does

- Runs an autopilot loop that proposes intraday entries from five
  distinct strategy lanes (`opening_range_breakout_v1`,
  `micro_breakout_v1`, `vwap_reclaim_v1`, `pullback_continuation_v1`,
  `relative_volume_spike_v1`).
- Scores each candidate via a paid AI provider (Claude → OpenAI) with
  a deterministic local fallback when paid quota is unavailable.
- Filters candidates through a risk gate that enforces buying-power
  minimums, PDT cap awareness, position-count limits, quote-spread
  checks, and lane-diversity guards.
- Executes fractional notional market orders through Alpaca live mode.
- Surfaces account state, defrag candidates, profit locks,
  protection plans, and morning-readiness in a Next.js dashboard.
- Tracks every pipeline run, broker order, and account snapshot in
  append-only JSONL audit logs.

## What's running in production today

- Live Alpaca account (sub-$100 NAV; intentional small-money
  validation).
- Autopilot armed with both entry and exit execution flags enabled.
- Kill switch as the operator-facing pause.
- 132 unique filled broker orders across 18 trading sessions to date.

## Reference numbers (lifetime through 2026-05-28)

- 47 commits, single contributor.
- 26 backend Python files, 7,824 LOC.
- 19 frontend TS/TSX files, 3,357 LOC.
- 930 pipeline runs recorded; 7.3% reached execution, 92.7% blocked at
  the risk gate.

## What's *not* shipped in v1

- Backtest harness (validated only on live forward fills).
- A proper test suite beyond 4 integration-style files.
- Audit log rotation (JSONL grows monotonically; 274 MB and counting).
- Multi-broker support.
- Options execution past scaffold.

## v2 plan

Started immediately after the 2026-05-29 close. v2 is a ground-up
rebuild, not a refactor — the v1 repo stays as the immutable teaching
record. Top items the retrospective surfaces for v2:

- Split `broker_adapter.py` (1,382 LOC) into transport + domain ops.
  *(Already partially landed in the pre-release cleanup branch — the
  single file is now a 46-LOC shim re-exporting from a focused
  `services/brokers/` subpackage. v2 will complete the split by
  collapsing the shim and updating every call site.)*
- Replace JSONL audit with rotating SQLite.
- Idempotent client_order_ids (eliminates the 2026-05-28 ghost-script
  bug class).
- Validate edge per strategy lane on v1's 132-fill dataset before
  re-implementing them all.
- First-class exit lanes that mirror entry lane structure (v1's
  autopilot enters but does not exit cleanly; 56 of 64 sells were
  manual).
- Account-aware minimum lot sizing so we stop fragmenting BP into
  sub-$3 lots.

See [`docs/v1-retrospective.md`](docs/v1-retrospective.md) for the
full pre-release audit and roadblock analysis.

## Safety note

This repository runs against a real brokerage with real money. Anyone
forking it should:

1. Read `CLAUDE.md` and the safety language in
   [`apps/api/.env.example`](apps/api/.env.example).
2. Default `INVESTMENT_APP_ALPACA_PAPER=true` until they have done
   their own audit.
3. Treat the kill switch as a real circuit breaker, not a UI element.
