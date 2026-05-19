## ADDED Requirements

### Requirement: Brief as priority seed
When a valid brief is loaded, every symbol listed in `candidates` SHALL be included in the scorer's candidate set for that session, even if it is not in the regular watchlist.

#### Scenario: Briefed symbol outside watchlist
- **WHEN** the brief lists `XYZ` and `XYZ` is not in the default watchlist
- **THEN** the scorer evaluates `XYZ` this session

#### Scenario: No brief loaded
- **WHEN** no brief is loaded
- **THEN** the candidate set is unchanged from current behavior

### Requirement: Bounded conviction boost
Briefed candidates SHALL receive an additive score boost proportional to `conviction` (1..5), bounded so that the boost alone cannot cause a trade that the deterministic gates would otherwise reject.

#### Scenario: Boost applied
- **WHEN** a briefed candidate with conviction 4 passes all risk gates
- **THEN** its final score equals scorer_score + (boost_coefficient * 4)

#### Scenario: Boost cannot override gates
- **WHEN** a briefed candidate fails a hard risk gate (spread too wide, regime stressed, PDT slot unavailable)
- **THEN** the candidate is rejected regardless of conviction

### Requirement: Blocklist is authoritative
Symbols listed in the brief's `blocklist` SHALL NOT be traded by the autopilot for that session, regardless of scorer output.

#### Scenario: Blocklisted symbol ranks high
- **WHEN** `TSLA` is on the blocklist and the scorer ranks `TSLA` highly
- **THEN** the autopilot does not stage or fill any order for `TSLA` this session

### Requirement: Risk-conservative stop reconciliation
When a briefed candidate provides a `stop`, the autopilot SHALL use the tighter of (brief stop, scorer-computed stop). A brief MUST NOT widen risk.

#### Scenario: Brief stop is tighter
- **WHEN** brief stop = 905 and scorer stop = 902
- **THEN** the executed stop is 905

#### Scenario: Brief stop is looser
- **WHEN** brief stop = 895 and scorer stop = 902
- **THEN** the executed stop is 902

### Requirement: Thesis metadata flows downstream
Candidate records derived from a brief SHALL carry `brief_thesis`, `brief_catalyst`, `brief_levels`, and `brief_author` fields through scoring, order placement, and execution logs so the operator can read the *why* in every surface.

#### Scenario: Order log shows thesis
- **WHEN** the autopilot places an order for a briefed candidate
- **THEN** the order log entry includes the brief thesis and catalyst strings

#### Scenario: Dashboard shows thesis
- **WHEN** the dashboard renders a candidate originating from the brief
- **THEN** the thesis and catalyst are visible in the candidate detail view

### Requirement: Feature flag
The brief-aware scoring path SHALL be gated by `PREMARKET_BRIEF_ENABLED`. When disabled, the system MUST behave exactly as it does today, even if a brief file exists on disk.

#### Scenario: Flag disabled
- **WHEN** `PREMARKET_BRIEF_ENABLED=false` and a valid brief is on disk
- **THEN** the loader is not called and scoring is unmodified

#### Scenario: Flag enabled
- **WHEN** `PREMARKET_BRIEF_ENABLED=true` and a valid brief is on disk
- **THEN** the loader runs and briefed candidates receive seed + boost
