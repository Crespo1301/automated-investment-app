# v1 — Final (End of the v1 Autotrader Line)

**Closed: 2026-06-02.** This marks the end of the first version of the
autotrader. The next work is the **v2.0** program
([`v2.0-operating-model.md`](./v2.0-operating-model.md)).

## Version timeline

- **`v0.2.0`** — 2026-05-09, early scaffold.
- **`v1.0`** — 2026-05-29 (commit `04828a9`, "Prepare v1.0 release").
  This is the **first version showcased publicly** as the autotrader.
- **`v1.1.0`** — **2026-06-02, this build. The final v1 release.** Adds
  the discretionary `buy-market` endpoint and is the build that proved
  the supervised operating flow live in production. Everything between
  the v1.0 tag and here was real trading with uncommitted code; this tag
  captures the true final v1 state.

v1.0 remains the public "first version" reference; `v1.1.0` is the v1
line's closeout. They are the same product line — v1.1.0 is consistent
with what was showcased, not a divergence.

## What the final v1 build contains

The supervised, live-broker (Alpaca) autotrader for a tiny real-money
account (~$50): intraday strategy lanes → deterministic risk gate →
scorer (paid Claude/OpenAI, currently disabled → local deterministic
fallback) → fractional notional market orders, plus a route-based
dashboard. New since `v1.0`:

- **Discretionary `buy-market` endpoint** (`POST
  /api/broker/positions/{symbol}/buy-market`) — the founded-entry path
  that lets the supervising Claude session place operator-chosen entries
  through the same risk gates the autopilot honors. This is the
  mechanism behind the v2.0 operating model.

Full v1 audit: [`v1-retrospective.md`](./v1-retrospective.md) and
[`v1-lane-analysis.md`](./v1-lane-analysis.md).

## Final session — 2026-06-02 (validated the operating flow live)

- **Close:** $50.94 (+0.34%) on a **red broad-market tape** (Iran/AI
  risk-off) — outperformed the market.
- **Book:** 8 positions (BAC, CMCSA, SOXX, PFE, VOO, XLK, ARKK, WFC);
  cash $6.65; **PDT 2/3 preserved**; reserve intact.
- **Discretionary judgment in action:** restarted a frozen loop twice;
  ran live catalyst research (defense/M&A/energy); **declined** to force
  a founded RTX entry past the reserve guard and a 499 bps stale-quote
  spread; **declined** the WFC small-win exit to preserve the last PDT
  bullet. Green on a red tape, every guardrail intact.

## Tagging

**Codex closeout:** create annotated tag `v1.1.0` at the v1-final commit
and push (tag + commit) per the workspace workflow. Claude prepared the
commit locally; Codex owns the push/release.
