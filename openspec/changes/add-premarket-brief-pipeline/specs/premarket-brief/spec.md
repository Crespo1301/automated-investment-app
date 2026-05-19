## ADDED Requirements

### Requirement: Daily brief artifact pair
The system SHALL accept one pre-market brief per ET trading date, stored as a pair of files under `data/premarket/`: `<YYYY-MM-DD>.json` (machine-readable, validated) and `<YYYY-MM-DD>.md` (human narrative). The JSON file SHALL be the authoritative source for autopilot behavior; the MD file SHALL NOT be parsed by code.

#### Scenario: Brief pair present and valid
- **WHEN** `data/premarket/2026-05-15.json` exists, validates against schema v1, and `valid_until` is in the future
- **THEN** the loader returns a Brief object and the autopilot uses it for the 2026-05-15 session

#### Scenario: JSON missing, MD present
- **WHEN** only `data/premarket/2026-05-15.md` exists for the session date
- **THEN** the loader returns None, logs `premarket_brief.missing`, and autopilot proceeds with pure-scorer behavior

#### Scenario: JSON invalid
- **WHEN** the JSON file fails schema validation (unknown field, missing required, schema_version mismatch)
- **THEN** the loader returns None, logs `premarket_brief.invalid` with validator output, and autopilot proceeds with pure-scorer behavior

### Requirement: Schema versioning
The brief JSON SHALL declare `schema_version` at the top level. The loader SHALL reject any brief whose major schema version is not supported by the current build.

#### Scenario: Supported version
- **WHEN** brief declares `schema_version: 1` and loader supports v1
- **THEN** brief is accepted

#### Scenario: Unsupported major version
- **WHEN** brief declares `schema_version: 2` and loader supports only v1
- **THEN** loader returns None and logs an explicit version-mismatch error

### Requirement: Brief expiry
A brief SHALL include a `valid_until` timestamp. Once that timestamp is in the past relative to the system clock, the brief MUST be treated as absent.

#### Scenario: Expired brief
- **WHEN** the current time is after `valid_until`
- **THEN** the loader returns None and the autopilot operates as if no brief exists

### Requirement: Hot reload
The system SHALL expose an authenticated admin endpoint that re-reads the brief from disk without restarting the worker, so the operator can correct or extend the brief intra-session.

#### Scenario: Operator edits brief mid-session
- **WHEN** the operator edits the JSON file and calls the reload endpoint
- **THEN** the loader re-validates and the new brief takes effect on the next scoring cycle

### Requirement: Read endpoint for dashboard
The API SHALL expose `GET /api/premarket/today` returning the active brief plus per-candidate execution state (queued / filled / blocked-by-reason / skipped).

#### Scenario: Dashboard fetches active brief
- **WHEN** the web dashboard requests `/api/premarket/today`
- **THEN** the response includes the brief content and a per-symbol status array reflecting autopilot decisions so far

#### Scenario: No active brief
- **WHEN** no brief is loaded for the session
- **THEN** the endpoint returns a 200 with `{ "brief": null, "reason": "missing"|"invalid"|"expired" }`

## ADDED Requirements

### Requirement: Validator CLI
A repo script SHALL validate a brief JSON file against the v1 schema and report errors with file/line context.

#### Scenario: Codex runs validator before commit
- **WHEN** Codex runs `npm run premarket:validate -- data/premarket/2026-05-15.json`
- **THEN** the script exits 0 on success or non-zero with line-level errors on failure
