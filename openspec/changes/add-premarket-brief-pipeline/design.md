## Context

The autopilot is a real-money-sensitive Python service in `apps/api` that runs a deterministic scorer over a watchlist and queues orders via Alpaca. Paid Claude/OpenAI quota is intermittently unavailable, so the scorer is the workhorse. Today the system has no qualitative thesis: it ranks by math and trades whatever ranks. The operator wants to arrive at the open with a *plan* — a small set of researched names with written reasons, prepared the night before by Claude (and reviewed by Codex), without spending paid API quota at 9:30.

Constraints:
- Must preserve deterministic risk gates, kill switch, PDT guard, spread/depth guards (`CLAUDE.md`).
- Must degrade cleanly when no brief exists for the session.
- Brief is authored in an off-hours Claude session — it lives on disk, not in a runtime API call.
- Codex owns implementation; Claude owns brief authorship and structural critique.

## Goals / Non-Goals

**Goals:**
- A daily on-disk artifact pair (`.json` + `.md`) under `data/premarket/` keyed by ET session date.
- Autopilot loads, validates, and applies the brief at session start, attaching thesis + levels to the candidate stream.
- Briefed tickers get a *priority seed + conviction boost* in the deterministic scorer; risk gates remain authoritative.
- Dashboard surface shows the active brief, which tickets have fired, and which were blocked (and why).
- Clear validator + schema so Codex can lint a brief before commit.

**Non-Goals:**
- Auto-generating briefs from a live LLM API at runtime (explicitly avoided — that's the quota cost we're side-stepping).
- Letting the brief *override* risk gates or stop logic.
- Multi-day or multi-session briefs. One brief per ET trading date.
- Replacing the deterministic scorer. The brief is an input, not a replacement.

## Decisions

**1. Artifact shape: JSON + MD pair, not one or the other.**
- `data/premarket/2026-05-15.json` is the machine contract. Strict schema. Loader fails closed on validation error (treat as "no brief").
- `data/premarket/2026-05-15.md` is the human write-up. Free-form thesis, sector view, macro notes, links to research. The MD is not parsed by code — it's for the operator and for git history.
- Alternatives considered: MD-only with a parser (rejected — fragile; small format drift breaks live trading). JSON-only (rejected — loses the narrative that makes briefs worth doing).

**2. Schema (v1) — concrete fields:**
```
{
  "session_date": "2026-05-15",       // ET trading date, ISO
  "author": "claude" | "codex" | "operator",
  "generated_at": "2026-05-14T22:30:00-04:00",
  "market_view": {
    "spy_bias": "bullish"|"neutral"|"bearish",
    "qqq_bias": "...",
    "vix_regime": "low"|"normal"|"elevated"|"stressed",
    "notes": "<=500 chars"
  },
  "candidates": [
    {
      "symbol": "NVDA",
      "lane": "high_upside_momentum_v1" | "small_win_compounder" | ...,
      "thesis": "<=600 chars",
      "catalyst": "earnings 5/14 AMC beat, guide raise",
      "entry_zone": { "low": 920.0, "high": 928.0 },
      "stop": 905.0,
      "target": 955.0,
      "conviction": 1..5,
      "max_position_pct": 0.0..0.25,     // optional cap honored by sizer
      "valid_until": "2026-05-15T16:00:00-04:00"
    }
  ],
  "blocklist": ["TSLA"]                  // optional: names not to trade today regardless of scorer
}
```
Versioned via top-level `schema_version: 1`. Loader rejects unknown majors.

**3. Loader location: `apps/api/app/services/premarket_brief.py`.**
- Single `load_brief(session_date) -> Brief | None`.
- Validates with pydantic. Logs structured warning on missing/invalid and returns None.
- Caches per-process; reload on SIGHUP or via admin endpoint for in-session edits (rare, but supported).

**4. Scoring integration: boost, not override.**
- Briefed symbols enter the candidate set even if not in the regular watchlist (priority seed).
- Conviction 1..5 maps to a bounded additive score boost (e.g., `0.05 * conviction`) — small enough that a broken regime or wide spread still kills the trade.
- `blocklist` entries get a hard `-inf` so they cannot fire regardless of math.
- Candidate records carry `brief_thesis`, `brief_levels`, `brief_author` fields downstream so logs, dashboard, and order memos show *why* a trade was taken.
- Alternative considered: hard override (rejected per operator preference — keeps risk engine authoritative).

**5. Stop/target reconciliation.**
- If brief provides a stop tighter than the scorer's computed stop, use the brief's (safer).
- If brief stop is looser than the scorer's computed stop, use the scorer's (never widen risk based on a thesis).
- If brief target is set, use it as a take-profit hint; existing trailing/exit logic still owns realized exits.

**6. Fallback behavior.**
- No brief file → log `premarket_brief.missing` warning, emit dashboard banner, continue with pure-scorer behavior.
- Invalid brief → same as missing, plus a `premarket_brief.invalid` error with validator output.
- Brief expired (`valid_until` in past) → ignored, treated as missing.

**7. Dashboard surface.**
- New read endpoint `GET /api/premarket/today` returns the active brief plus per-candidate execution state (queued / filled / blocked-by-X / skipped).
- Web route exposed inside `/strategies` as a "Today's plan" panel (keeps route count flat per CLAUDE.md guidance). Clearly labeled "scenario framework, not a promise."

**8. Authoring workflow (off-code, but documented in repo).**
- Claude evening session writes `data/premarket/<date>.{json,md}` based on: existing watchlist, news/earnings calendar, sector regime, SPY/QQQ posture, Alpaca headline sentiment if available, recent price action.
- Codex runs `npm run premarket:validate` (new script wrapping the pydantic validator) before committing the MD note. JSON file is gitignored by default to keep daily noise out of git; operator can opt-in to commit by flipping a `.gitignore` exception.

## Risks / Trade-offs

- **Risk: brief becomes stale or wrong by the open.** → Schema requires `valid_until`; loader ignores expired briefs; operator can hot-reload via admin endpoint.
- **Risk: bad brief drags the autopilot into bad trades.** → Boost is bounded; risk gates remain authoritative; blocklist exists for hard "don't touch today" names.
- **Risk: silent failure if file path or schema drifts.** → Loader emits structured warnings; dashboard banner makes "no brief loaded" visible to operator before the open.
- **Risk: drift between MD narrative and JSON facts (Claude writes a thesis that doesn't match the levels).** → Validator can cross-check that every JSON `symbol` is mentioned in the MD; warn (don't fail) on mismatch.
- **Trade-off: JSON+MD doubles authoring surface.** → Accepted; the narrative is the whole point of the change.
- **Trade-off: bounded boost may feel weak when conviction is genuinely high.** → Operator can raise the boost coefficient via config; we keep the *shape* (bounded, additive) to protect the risk engine.

## Migration Plan

1. Ship loader + schema + validator behind a feature flag (`PREMARKET_BRIEF_ENABLED`, default off).
2. Author 3–5 dry-run briefs and verify the dashboard surface and logs are sensible while autopilot ignores them (flag off).
3. Flip flag on for one session with tight position sizes; review fills + logs.
4. Remove flag once stable.

Rollback: set `PREMARKET_BRIEF_ENABLED=false`. No data migration required (artifacts are file-system only).

## Open Questions

- Should `blocklist` also block manual orders placed from the dashboard, or only autopilot? (Default: autopilot only.)
- Conviction → boost coefficient: start at `0.05` per point, or expose as config from day one?
- Do we want a second JSON section for *pairs/spreads* later, or keep v1 strictly single-name?
