import { PdtMeter } from "@/components/analytics-visuals";
import { DashboardShell } from "@/components/dashboard-shell";
import {
  getDailyRecap,
  getDefragmentationCandidates,
  getExitCheck,
  getProfitLocks,
  getProtectionPlan,
  getReconciliation,
  getSafetyStatus,
} from "@/lib/server-data";
import { currencyFormatter } from "@/lib/format";

export default async function RiskPage() {
  const [reconciliation, safety, protectionPlan, exitCheck, profitLocks, defrag, recap] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getProtectionPlan(),
    getExitCheck(),
    getProfitLocks(),
    getDefragmentationCandidates(),
    getDailyRecap(),
  ]);

  const account = reconciliation?.account ?? null;
  const positions = reconciliation?.positions ?? [];
  const killSwitchEnabled = safety?.safety_state.kill_switch_enabled ?? false;

  return (
    <DashboardShell
      active="Risk"
      account={account}
      killSwitchEnabled={killSwitchEnabled}
      marketClock={safety?.market_clock ?? null}
      openPositions={positions.length}
      portfolioDelta={recap?.portfolio_delta ?? null}
      providerUsage={recap?.provider_usage ?? null}
      title="Risk and exits"
    >
      <section className="content-grid">
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Profit Locks</h2>
              <p>Take-profit signals queued as exit priorities. Day-trade cap retired — these now clear same-session.</p>
            </div>
            <span className={profitLocks?.entries.length ? "state-pill state-warning" : "state-pill state-healthy"}>
              {profitLocks?.entries.length ? `${profitLocks.entries.length} locked` : "clear"}
            </span>
          </div>
          <div className="list">
            {profitLocks && profitLocks.entries.length > 0 ? (
              profitLocks.entries.map((entry) => (
                <div className="list-item" key={`${entry.symbol}-${entry.locked_at ?? "lock"}`}>
                  <div className="row-top">
                    <strong className="symbol">{entry.symbol}</strong>
                    <span className={(entry.unrealized_pl ?? 0) >= 0 ? "positive" : "negative"}>
                      {entry.unrealized_pl != null ? currencyFormatter(entry.unrealized_pl) : "-"}
                    </span>
                  </div>
                  <p className="thesis">
                    Current {entry.current_price != null ? currencyFormatter(entry.current_price) : "-"} vs avg{" "}
                    {entry.average_entry_price != null ? currencyFormatter(entry.average_entry_price) : "-"}.
                    Value {entry.market_value != null ? ` ${currencyFormatter(entry.market_value)}` : " -"}.
                  </p>
                  <p className="thesis">{entry.block_reason}</p>
                </div>
              ))
            ) : (
              <div className="empty-state">{profitLocks?.notes[0] ?? "No profit-locked carries recorded."}</div>
            )}
          </div>
        </article>

        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Defragmentation</h2>
              <p>Stale tiny lots that can be rotated to reclaim buying power for stronger setups.</p>
            </div>
            <span className={defrag?.candidates.length ? "state-pill state-info" : "state-pill state-healthy"}>
              {defrag?.candidates.length ? `${defrag.candidates.length} candidates` : "none"}
            </span>
          </div>
          <div className="list">
            {defrag && defrag.candidates.length > 0 ? (
              defrag.candidates.map((candidate) => (
                <div className="list-item" key={candidate.symbol}>
                  <div className="row-top">
                    <strong className="symbol">{candidate.symbol}</strong>
                    <span className={candidate.unrealized_pl >= 0 ? "positive" : "negative"}>
                      {currencyFormatter(candidate.unrealized_pl)}
                    </span>
                  </div>
                  <p className="thesis">
                    {currencyFormatter(candidate.market_value)} lot held for {Math.floor(candidate.age_minutes / 60)}h{" "}
                    {candidate.age_minutes % 60}m. Last buy {new Date(candidate.last_buy_filled_at).toLocaleString()}.
                  </p>
                </div>
              ))
            ) : (
              <div className="empty-state">{defrag?.notes[0] ?? "No defragmentation candidates right now."}</div>
            )}
          </div>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Day-trade activity</h2>
              <p>PDT cap retired 2026-06-04. Count is informational — no ceiling on entries or same-day exits.</p>
            </div>
          </div>
          <PdtMeter daytradeCount={account?.daytrade_count} />
        </article>

        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Active guardrails</h2>
              <p>What is keeping the loop honest right now.</p>
            </div>
          </div>
          <div className="autopilot-grid">
            <div className="autopilot-row">
              <span>Kill switch</span>
              <strong>{killSwitchEnabled ? "ENABLED" : "clear"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Reason</span>
              <strong>{safety?.safety_state.reason ?? "-"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Open positions</span>
              <strong>{positions.length}</strong>
            </div>
            <div className="autopilot-row">
              <span>Exit signals</span>
              <strong>{exitCheck?.signals.length ?? 0}</strong>
            </div>
            <div className="autopilot-row">
              <span>Protection</span>
              <strong>{protectionPlan?.status.replace("_", " ") ?? "offline"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Audit trail</span>
              <strong>{safety?.order_events ?? 0} events</strong>
            </div>
          </div>
          <p className="thesis" style={{ marginTop: 12 }}>
            No raw daily order cap and no day-trade cap (PDT retired 2026-06-04). Entries flow through risk,
            buying-power, open-position, min-notional, and kill-switch checks. Same-day exits are always honored.
          </p>
        </article>
      </section>

      <section className="content-grid">
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Protection plan</h2>
              <p>Position-level exit readiness and fractional-order constraints.</p>
            </div>
            <span className={
              protectionPlan?.status === "ready"
                ? "state-pill state-healthy"
                : protectionPlan?.status === "no_positions"
                  ? "state-pill"
                  : "state-pill state-warning"
            }>
              {protectionPlan?.status.replace("_", " ") ?? "offline"}
            </span>
          </div>
          <div className="list">
            {protectionPlan && protectionPlan.plans.length > 0 ? (
              protectionPlan.plans.map((plan) => (
                <div className="list-item" key={plan.symbol}>
                  <div className="row-top">
                    <strong className="symbol">{plan.symbol}</strong>
                    <span className={plan.status === "protected" ? "state-pill state-healthy" : "state-pill state-warning"}>
                      {plan.status.replace("_", " ")}
                    </span>
                  </div>
                  <p className="thesis">
                    Stop {plan.suggested_stop_price ? currencyFormatter(plan.suggested_stop_price) : "pending"} -
                    take profit {plan.suggested_take_profit_price ? currencyFormatter(plan.suggested_take_profit_price) : "pending"}
                  </p>
                  <p className="thesis">{plan.notes[plan.notes.length - 1]}</p>
                </div>
              ))
            ) : (
              <div className="empty-state">{protectionPlan?.notes[0] ?? "Protection plan unavailable."}</div>
            )}
          </div>
        </article>

        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Exit signals</h2>
              <p>Read-only review before any sell execution.</p>
            </div>
            <span className={exitCheck?.signals.length ? "state-pill state-warning" : "state-pill state-healthy"}>
              {exitCheck?.signals.length ? `${exitCheck.signals.length} active` : "clear"}
            </span>
          </div>
          <div className="list">
            {exitCheck && exitCheck.signals.length > 0 ? (
              exitCheck.signals.map((signal) => (
                <div className="list-item" key={`${signal.symbol}-${signal.reason}`}>
                  <div className="row-top">
                    <strong className="symbol">{signal.symbol}</strong>
                    <span className="state-pill state-warning">{signal.reason.replace("_", " ")}</span>
                  </div>
                  <p className="thesis">
                    Current {currencyFormatter(signal.current_price)} vs trigger {currencyFormatter(signal.trigger_price)} -{" "}
                    {signal.execution_allowed ? "execution enabled" : "execution locked"}
                  </p>
                </div>
              ))
            ) : (
              <div className="empty-state">{exitCheck?.notes[0] ?? "Exit check unavailable."}</div>
            )}
          </div>
        </article>
      </section>
    </DashboardShell>
  );
}
