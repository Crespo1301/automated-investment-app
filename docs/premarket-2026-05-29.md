# Pre-market — 2026-05-29 (Claude)

**Context shift for this session:** tomorrow's push is **v1.0 public showcase**. After today's close we begin a ground-up v2 rebuild informed by what v1 taught us. Trading posture today: *small, surgical, no avoidable risk*. Don't blow up the showcase day. Save big ideas for v2.

## Starting state (from 2026-05-28 EOD)

- NAV $50.20 · BP $9.56 · PDT 1/3 (one slot already burned by yesterday's ARKG round-trip)
- 8 open positions: F, NVDA, PFE, QQQ, RIVN, SPY, VOO, XLF
- Net unrealized +$0.13. No position above $9.01 (QQQ).

## Macro setup for Friday 2026-05-29

1. **Month-end rebalancing day.** Expect afternoon order flow distortion regardless of news. First and last hour will be the highest-conviction tape; midday drift is meaningless.
2. **Yesterday's PCE digested as bullish** — core 0.2% beat. SPY/Nasdaq closed at record highs. Risk-on regime intact going into Friday.
3. **Fed cuts off the table for the rest of 2026** per the hot 3.8% headline PCE. Bearish for KRE, TLT; supportive for GLD, USO, energy reflation names.
4. **Oil at $90 WTI** with ME risk premium holding — energy and oil-correlated names have a tailwind.
5. **No major US data Friday** (Chicago PMI, U Mich sentiment final are minor). Quiet macro = stock-specific moves dominate.

## Hidden-gem watchlist (within our allowed universe)

Conviction order, with explicit catalyst:

| Symbol | Thesis | Catalyst | Risk |
|---|---|---|---|
| **SMH** | Semis ride NVDA capex + AI infra theme without single-name event risk. Broader exposure than holding NVDA alone. | AI capex cycle, sector flow | Crowded trade, vol on any AI sentiment shift |
| **GLD** | Sticky inflation + Fed on hold = real-rate tailwind for gold. Underowned vs equities right now. | PCE hot print, month-end rebalance into hedges | Trending but slow; not a quick mover |
| **USO** | Oil at $90, ME risk premium, EIA Q3 supply still tight per Hormuz disruption. | Geopolitics, EIA inventories | Reversal risk if ME ceasefire holds |
| **RIVN** *(already long)* | R2 deliveries start **June 9** — 11 days out, classic event-drift window. | R2 customer ship date | EV sentiment fragile, RIVN down 26% YTD |
| **XBI** | Biotech breadth — CYTK, AXSM, LNTH all flagged as breakout candidates this week. ETF avoids single-name binary risk. | Sector rotation into laggards | Highly noisy; needs tight stop |

Notes:
- **Don't add NVDA on weakness today** — it's already in the book and last week's "beat-and-fade" 4-in-a-row pattern still applies.
- **Don't add ARKG** — burned a PDT slot yesterday; same lane gets a 5-day cool-down.
- **Don't touch KRE / TLT** — Fed-on-hold thesis works against both.

## Morning checklist (operator)

1. Confirm API is up (`curl /healthz`), web is up, autopilot armed (last action shouldn't be `disarmed`).
2. Read `scripts/morning_defrag_2026-05-28.log` if not already — confirm yesterday's tape.
3. Review the 8-name book. Anything that gapped >2% overnight gets a fresh exit-check; anything down >3% from cost gets eyes.
4. With $9.56 BP, the autopilot has room for ~2 fresh fractional entries. Let it choose from the lanes; manual entries reserved for the watchlist above if a clean trigger prints.
5. **PDT discipline**: only 2 slots left this 5-day window. No day-trips today unless it's a clean exit on a same-day winner > +3%.

## Hard rules for v1.0 showcase day

- No experimental code merges into the running API/web today. The repo we showcase is the repo we run.
- No autopilot config changes (interval, lane weights, risk caps) during the session.
- If something breaks, the kill switch + manual exits are the answer. Don't push a fix into a live process.
- All EOD logging on. End-of-session brief becomes the first artifact of the v2 retrospective.

## After close — v1.0 → v2 transition plan (preview, not actions)

Tomorrow's after-market work (separate session): full ground-up review covering
- code/strategy bloat audit
- which scoring lanes actually produced edge vs noise
- recurring roadblocks (PDT, BP fragmentation, the process bug above, kill-switch transient trips)
- a clean v2 architecture proposal that keeps what worked and drops what didn't

That review uses the full audit history in `apps/api/.runtime/*.jsonl` plus the docs/ trail since project start.

Sources:
- [Motley Fool — Stock Market Today 5/28](https://www.fool.com/coverage/stock-market-today/2026/05/28/stock-market-today-may-28-inflation-isn-t-stopping-this-stock-market-rally/)
- [Benzinga — April PCE 3.8%, highest since May 2023](https://www.benzinga.com/markets/macro-economic-events/26/05/52835775/us-pce-inflation-report-april-2026)
- [marketshost — biotech momentum names May 2026](https://www.marketshost.com/news/articles/15-biotech-pharma-stocks-with-strong-buy-signals-in-may-2026-ai-powered-technical-analysis-reveals-top-entry-points-102639)
- [SEC 8-K — Rivian R2 deliveries Q2 2026](https://www.sec.gov/Archives/edgar/data/0001874178/000187417826000033/ex-9911q26rivianearningspr.htm)
- [Medium — Month-end flows into June 2026](https://medium.com/coinmonks/nordfx-thin-liquidity-and-month-end-flows-usd-gold-and-oil-into-june-ee4294cd451a)
