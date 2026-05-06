# CLAUDE.md

Repo role: internal investment and trading scaffold, lower weekly priority than the core CSolutions business repos.

## Business Context

- This repo is not a front-line client acquisition asset.
- Shared workflow rules live in `/home/cresp3/Portfolio/AI-WORKFLOW.md`.
- Architecture and handoffs live in `docs/`.

## Claude Role Here

- Use Claude for architecture, operator UX, naming, and planning only when this repo is the explicit target.
- Let Codex handle implementation, test passes, repo organization, and GitHub closeout.

## Working Notes

- API runs from `apps/api`.
- Web dashboard runs from `apps/web`.
- Alpaca verification and funding do not change the live-trading rule by themselves.
- Live trading stays disabled unless explicitly approved and deliberately enabled.
- Treat this repo as paper-first until reconciliation, kill switch coverage, and first-live-order review are in place.

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
