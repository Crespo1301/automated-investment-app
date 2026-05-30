import type { MorningReadiness } from "@/lib/contracts";

function deriveNextStep(readiness: MorningReadiness | null) {
  if (!readiness) {
    return "Start the FastAPI server to load live arming readiness.";
  }
  if (readiness.ready_for_autonomous_entries) {
    return "Entries are armed. Start the autopilot loop when you are ready to trade live.";
  }

  const blockers = new Set(readiness.blockers);

  if (blockers.has("Kill switch is enabled.")) {
    return "Disable the kill switch, then rerun readiness before starting the live loop.";
  }
  if (blockers.has("Autopilot is not armed.")) {
    return "Run `python -m app.worker --enable-autopilot \"Arming live entries after config reload\"`.";
  }
  if (blockers.has("Trading mode is not live.") || blockers.has("Live trading permission is disabled.")) {
    return "Reload the API after confirming live mode and live permission in apps/api/.env.";
  }
  if (blockers.has("Alpaca is still in paper mode.")) {
    return "Switch Alpaca out of paper mode in apps/api/.env, then restart the API.";
  }
  if (blockers.has("Autopilot entry execution is locked.")) {
    return "The loaded process still has entry execution locked. Restart the API and re-arm autopilot.";
  }
  if (
    readiness.blockers.some((blocker) =>
      blocker.startsWith("Autonomous entries cannot fetch Alpaca market data."),
    )
  ) {
    return "Market data access is blocking entries. Verify Alpaca live data entitlements and connectivity.";
  }
  if (blockers.has("Regular market is currently closed.")) {
    return "The stack is configured correctly. Entries will arm once the regular market is open.";
  }
  if (
    readiness.blockers.some((blocker) => blocker.startsWith("Buying power $"))
  ) {
    return "The stack is armed, but buying power is below the minimum order guard.";
  }

  return "Resolve the listed blockers, then rerun morning readiness and autopilot status.";
}

export function ArmingChecklist({ readiness }: { readiness: MorningReadiness | null }) {
  const blockers = readiness?.blockers ?? [];
  const autopilot = readiness?.autopilot_state;
  const nextStep = deriveNextStep(readiness);

  return (
    <article className="panel">
      <div className="section-title">
        <div>
          <h2>Live arming checklist</h2>
          <p>One source of truth for whether entries are truly ready to submit.</p>
        </div>
        <span
          className={
            readiness?.ready_for_autonomous_entries
              ? "state-pill state-healthy"
              : readiness
                ? "state-pill state-warning"
                : "state-pill state-blocked"
          }
        >
          {readiness?.ready_for_autonomous_entries ? "entries ready" : readiness ? "blocked" : "offline"}
        </span>
      </div>

      <div className="autopilot-grid">
        <div className="autopilot-row">
          <span>Watch mode</span>
          <strong>{readiness?.ready_for_watch_mode ? "ready" : "not ready"}</strong>
        </div>
        <div className="autopilot-row">
          <span>Autonomous entries</span>
          <strong>{readiness?.ready_for_autonomous_entries ? "ready" : "blocked"}</strong>
        </div>
        <div className="autopilot-row">
          <span>Loaded entry state</span>
          <strong>{autopilot?.entry_execution_enabled ? "enabled" : "locked"}</strong>
        </div>
        <div className="autopilot-row">
          <span>Loaded exit state</span>
          <strong>{autopilot?.exit_execution_enabled ? "enabled" : "locked"}</strong>
        </div>
        <div className="autopilot-row">
          <span>Market clock</span>
          <strong>{readiness?.market_clock?.is_open ? "open" : "closed"}</strong>
        </div>
        <div className="autopilot-row">
          <span>Last action</span>
          <strong>{autopilot?.last_action ?? "none"}</strong>
        </div>
      </div>

      <div className="action-warning" role="status" style={{ marginTop: 12 }}>
        {nextStep}
      </div>

      {blockers.length > 0 ? (
        <div className="list" style={{ marginTop: 12 }}>
          {blockers.map((blocker) => (
            <div className="list-item" key={blocker}>
              <p className="thesis">{blocker}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="thesis" style={{ marginTop: 12 }}>
          No blockers reported. Run `python -m app.worker --autopilot-once` for a final supervised live-entry check.
        </p>
      )}
    </article>
  );
}
