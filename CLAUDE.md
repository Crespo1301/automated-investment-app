# CLAUDE.md

Repo role: internal investment and trading scaffold, lower weekly priority than the core CSolutions business repos.

## Business Context

- This repo is not a front-line client acquisition asset.
- Shared workflow rules live in `/home/cresp3/Portfolio/AI-WORKFLOW.md`.
- Architecture and handoffs live in `docs/`.

## Claude Role Here

- Claude may review and propose changes across the whole project, including trading logic, execution flow, dashboard UX, data visualization, naming, and planning, when this repo is the explicit target.
- Claude should treat live-trading paths as real-money sensitive: propose or edit carefully, preserve deterministic risk gates, and explain any strategy or execution change in plain operator language.
- Codex remains responsible for final implementation review, test/build passes, repo organization, GitHub closeout, and catching issues Claude missed.
- When taking over from Codex, preserve server actions, typed confirmation fields, kill-switch behavior, PDT guard copy, spread guards, market-context scoring, and route-level data fetching.

## Working Notes

- API runs from `apps/api`.
- Web dashboard runs from `apps/web`.
- The app has been tested with tiny live Alpaca orders. Treat every execution path as real-money sensitive.
- Paid Claude/OpenAI API quota may be unavailable. The deterministic fallback scorer is expected to carry the system until provider funding is available.
- The dashboard is now route-based: `/`, `/portfolio`, `/strategies`, `/risk`, `/orders`, and `/settings`.
- Claude design passes should make these surfaces feel like a serious broker/operator console while keeping warnings, confirmations, and safety language visible.

## Current Scoring Posture

- Scoring priority is Claude API, then OpenAI API, then deterministic local fallback.
- The local fallback blends strategy prior, confidence hint, trigger evidence quality, setup structure, stop distance, and market-context health.
- Market context now includes quote spread, top-of-book depth proxy, volatility regime, SPY/QQQ broader-market regime, and Alpaca headline sentiment when available.
- The strategy stack is split between steadier small-win compounder lanes and a riskier `high_upside_momentum_v1` lane for larger-move candidates across a broader watchlist.
- Do not remove deterministic explanations. Improve visual presentation without hiding why a trade was approved or rejected.

## Next Claude Design Pass

- Start with `/portfolio`, `/strategies`, `/risk`, `/orders`, and `/settings`; these are intentionally scaffolded for design takeover.
- Improve visual hierarchy, charts, tables, and broker-console polish without changing server actions or route data contracts.
- Add richer explanatory visuals for compounding scenarios, strategy funnel, provider usage, PDT posture, and exit readiness.
- Keep all projections labeled as scenario frameworks, not promises.
- After Claude changes, Codex should run backend tests, web build, review the diff, and handle commit/push/release.

## Useful Commands

```bash
npm run dev:web
npm run build:web
npm run lint:web
npm run graph:build
npm run graph:status
npm run spec:list
npm run spec:validate
npm run stitch:init
npm run stitch:doctor
npm run stitch:proxy
```

## Shared AI Tooling

- Follow `AI-WORKFLOW.md` for the shared CSolutions AI stack.
- Use repo-local `.claude/skills/` for `code-review-graph`, `Impeccable`, `ui-ux-pro-max`, `OpenSpec`, and `mattpocock/skills` workflows.
- Use repo-local `.codex/skills/` for Codex-side `ui-ux-pro-max` and `OpenSpec` workflows when the repo is the active target.
- Use `.mcp.json` with `code-review-graph` after `npm run graph:build` so exploration and reviews stay token-efficient.
- Use OpenSpec for larger trading, execution, or dashboard changes that benefit from proposal, spec, and task artifacts.
