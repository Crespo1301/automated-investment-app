## 1. Schema and storage

- [ ] 1.1 Create `data/premarket/` directory with `.gitkeep`; add `.gitignore` rule for `data/premarket/*.json` (allow `*.md` and `schema.example.json`)
- [ ] 1.2 Commit `data/premarket/schema.example.json` showing all v1 fields with realistic values
- [ ] 1.3 Commit `data/premarket/README.md` documenting authoring workflow (Claude evening session → Codex validate → operator review)

## 2. Loader and validator (apps/api)

- [ ] 2.1 Add `apps/api/app/services/premarket_brief.py` with pydantic models for `Brief`, `MarketView`, `Candidate`, `EntryZone`
- [ ] 2.2 Implement `load_brief(session_date: date) -> Brief | None` with structured logging on missing/invalid/expired
- [ ] 2.3 Add `schema_version` check; reject unsupported majors with explicit log
- [ ] 2.4 Add per-process cache + `reload_brief()` for hot reload support
- [ ] 2.5 Add unit tests covering: valid, missing, invalid-schema, version-mismatch, expired

## 3. Scoring integration

- [ ] 3.1 Extend candidate record type with `brief_thesis`, `brief_catalyst`, `brief_levels`, `brief_author` fields
- [ ] 3.2 In the scorer entry path, merge briefed symbols into the candidate set (priority seed)
- [ ] 3.3 Apply bounded additive boost = `boost_coefficient * conviction` (default coefficient `0.05`, configurable via env)
- [ ] 3.4 Apply hard `-inf` score for symbols on `blocklist`
- [ ] 3.5 Stop reconciliation: choose tighter of (brief stop, scorer stop); never widen
- [ ] 3.6 Honor optional `max_position_pct` cap in sizer when present
- [ ] 3.7 Unit tests: boost applied, gates still reject, blocklist hard-blocks, stop never widens

## 4. Worker wiring

- [ ] 4.1 Update `apps/api/app/worker.py` and `local_worker.py` to call `load_brief()` at session start
- [ ] 4.2 Emit telemetry counters: `premarket_brief.loaded`, `.missing`, `.invalid`, `.expired`
- [ ] 4.3 Pass active brief (or None) into the scoring cycle
- [ ] 4.4 Gate the entire integration behind `PREMARKET_BRIEF_ENABLED` env flag (default `false`)

## 5. API + dashboard surface

- [ ] 5.1 Add `GET /api/premarket/today` returning brief + per-candidate execution state
- [ ] 5.2 Add authenticated `POST /api/premarket/reload` for hot reload
- [ ] 5.3 In `apps/web/`, add a "Today's plan" panel inside `/strategies` showing brief content + per-symbol status
- [ ] 5.4 Add a clear "scenario framework, not a promise" banner on the panel
- [ ] 5.5 Add a "no brief loaded" dashboard banner when applicable

## 6. CLI validator script

- [ ] 6.1 Add `scripts/validate_premarket_brief.py` that loads a JSON path and runs the pydantic validator
- [ ] 6.2 Wire `npm run premarket:validate` in root `package.json` to call the script
- [ ] 6.3 Validator emits file/line context on failure and cross-checks JSON symbols against the MD note (warn-only)

## 7. Tests and verification

- [ ] 7.1 Integration test in `apps/api/tests/test_trading_pipeline.py`: brief present, briefed name fires; brief present, blocklisted name does not fire; brief absent, behavior unchanged
- [ ] 7.2 Run `npm run lint:web` and api test suite; both green
- [ ] 7.3 Manual dry-run: author a brief for tomorrow, flag off → verify dashboard shows it, autopilot ignores it
- [ ] 7.4 Manual live-flag run with tiny size: flag on, verify boost + blocklist + thesis-in-log

## 8. Docs and closeout

- [ ] 8.1 Update `CLAUDE.md` "Current Scoring Posture" section to mention the brief input
- [ ] 8.2 Update `AI-WORKFLOW.md` with the evening-brief authoring step
- [ ] 8.3 Codex: commit, push, version bump, release note
