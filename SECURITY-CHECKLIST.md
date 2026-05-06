# Security Checklist

Canonical source: `/home/cresp3/Portfolio/docs/next-steps/security-next-steps.md`

This repo uses the shared CSolutions security baseline. Run the checklist before launches, before client handoff, and before any release that changes auth, forms, billing, storage, or external integrations.

## Quick Start

1. Open `docs/next-steps/security-next-steps.md`.
2. Work the checklist from top to bottom.
3. Log real findings before you ship.

## Local Reminder

- Keep secrets in `.env.local`, `.env.ai.local`, platform env settings, or another local-only secret store.
- Do not commit `.mcp.json` or `.env.ai.local`.
- Rotate any key that has already appeared in code, screenshots, or shared chat history.
- For this repo specifically, treat broker credentials as higher-risk than ordinary app keys. Paper keys and live keys should never share the same local file without clear labeling.
- Funding an Alpaca account is not a security or workflow milestone by itself. Live-mode changes need explicit review, documented intent, and a rollback path.
