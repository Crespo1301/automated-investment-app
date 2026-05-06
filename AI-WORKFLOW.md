# AI Workflow

This repo follows the shared CSolutions AI workflow.

## Role Split

- Claude is the main designer, planner, and concept partner.
- Codex is the daily worker, organizer, maintainer, and GitHub-side closer.

## Default Flow

1. Use Claude when the task is still fuzzy, visual, or copy-heavy.
2. Ask Claude for a short implementation brief with the target repo, page or feature, direction, and acceptance criteria.
3. Move to Codex for implementation, maintenance, cleanup, testing, documentation, and release prep.
4. Go back to Claude only when a built result needs design critique.

## Handoff Rule

Every Claude design or planning pass should leave a short record in
`docs/claude-track-record.md`.

Record:

- the date
- the target surface
- the Claude recommendation
- whether CSolutions accepted, changed, or rejected it
- what Codex implemented from it
- the release or commit where the work landed

If Codex works directly from an already-approved project doc, log that as
`Source: Docs` rather than inventing a Claude recommendation.

## Repo-Local AI Files

Use these local files in every repo:

- `.env.ai.example`
- `.env.ai.local`
- `.mcp.example.json`
- `.mcp.json`
- `scripts/stitch-doctor.sh`
- `scripts/stitch-proxy.sh`
- `scripts/magic-mcp.sh`
- `openspec/config.yaml`

`.env.ai.local` and `.mcp.json` stay local-only and should not be committed.

For 21st.dev in Claude, prefer this pattern:

1. keep shared AI keys in `$HOME/.env.ai.local`
2. use repo-local `.env.ai.local` only when a repo needs an override
3. `cp .mcp.example.json .mcp.json`
4. let `scripts/magic-mcp.sh` map `TWENTYFIRST_API_KEY` into the `API_KEY` env expected by `@21st-dev/magic`

## Local Commands

If this repo has `package.json`, prefer:

```bash
npm run graph:build
npm run graph:status
npm run spec:list
npm run spec:validate
npm run stitch:init
npm run stitch:doctor
npm run stitch:proxy
```

If this repo does not use npm scripts, use:

```bash
bash ./scripts/stitch-doctor.sh
bash ./scripts/stitch-proxy.sh
bash ./scripts/magic-mcp.sh
```

## Tool Rules

- Use Stitch when a section needs stronger design exploration or UI concepting.
- Use 21st.dev for inspiration and component benchmarking.
- Use `ui-ux-pro-max` for premium layout, typography, spacing, and polish decisions.
- In this repo, use `ui-ux-pro-max` mainly for operator dashboard clarity, not for marketing-style visual exploration.
- Do not hardcode AI keys in committed files.

## Shared AI Skill Stack

Use these across active repos so Claude and Codex spend fewer tokens and work with the same operating system:

- `code-review-graph`
  - Use it first for codebase exploration, review, impact checks, and targeted refactors.
  - Install with `uv tool install code-review-graph` or `pipx install code-review-graph`.
  - After install, run `code-review-graph build` inside the repo before expecting good results.
- `Impeccable`
  - Use it for design shaping, critique, polish, hardening, layout, and responsive cleanup.
  - Repo-local skills live under `.claude/skills/impeccable` and `.agents/skills/impeccable`.
- `OpenSpec`
  - Use it for multi-step features, larger rebuilds, and any change that should leave behind a proposal/tasks trail.
  - Install with `npm install -g @fission-ai/openspec@latest`, then run `openspec init` once per repo and `openspec update` when refreshing commands.
- `mattpocock/skills`
  - Use `grill-with-docs`, `tdd`, `diagnose`, `zoom-out`, `to-prd`, `to-issues`, and `improve-codebase-architecture` to keep implementation disciplined.
  - Repo-local skills live under both `.claude/skills/` and `.agents/skills/`.

## Token Efficiency Rule

- Prefer `code-review-graph` plus targeted skills before broad file reads.
- Use Claude for visual, copy, and critique-heavy work.
- Use Codex for implementation, verification, cleanup, and Git closeout.
- Use OpenSpec only when the task is large enough to benefit from explicit proposal/spec/task artifacts.
- For trading work, do not burn tokens on full-repo rereads once the graph and OpenSpec context exist. Rebuild graph or open the exact spec/change instead.

## Real-Money Guardrail

- Alpaca account approval and deposits do not automatically justify live trading work.
- Keep `INVESTMENT_APP_ALLOW_LIVE_TRADING=true` disabled until there is an explicit repo task to enable it.
- Before any live-mode task, confirm:
  - reconciliation is working
  - kill switch behavior is implemented
  - first live order payload is manually reviewed
  - the requested mode change is intentional and documented

## GitHub Closeout

Codex should usually leave one of these behind at the end of an active slice:

- a focused commit
- a push to the active branch
- a version or release note update
- a short handoff note if the work is intentionally left uncommitted

Do not force a commit only to make a repo look clean when the repo is intentionally mid-work.
