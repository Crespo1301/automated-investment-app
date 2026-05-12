import { DashboardShell } from "@/components/dashboard-shell";
import { currencyFormatter } from "@/lib/format";
import {
  getDailyRecap,
  getOptionsRecent,
  getReconciliation,
  getSafetyStatus,
} from "@/lib/server-data";

export default async function OptionsPage() {
  const [reconciliation, safety, recap, optionsData] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getDailyRecap(),
    getOptionsRecent(),
  ]);

  const account = reconciliation?.account ?? null;
  const enabled = optionsData?.enabled ?? false;
  const level = optionsData?.max_level ?? 0;
  const records = optionsData?.records ?? [];

  const candidates = records.filter((r) => r.payload.candidate);
  const submitted = records.filter((r) => r.payload.receipt);
  const rejected = records.filter(
    (r) => r.payload.decision && r.payload.decision.state === "rejected",
  );

  return (
    <DashboardShell
      active="Options"
      account={account}
      killSwitchEnabled={safety?.safety_state.kill_switch_enabled ?? false}
      marketClock={safety?.market_clock ?? null}
      portfolioDelta={recap?.portfolio_delta ?? null}
      openPositions={reconciliation?.positions.length ?? 0}
      providerUsage={recap?.provider_usage ?? null}
      title="Options desk"
    >
      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Posture</h2>
            <p>
              Level-1 covered calls and cash-secured puts. Live submission
              follows the same autopilot entry and live-trading controls.
            </p>
          </div>
          <span className="state-pill">
            {enabled ? `Enabled · Level ${level}` : "Disabled"}
          </span>
        </div>
        <div className="metric-row">
          <Metric label="Candidates seen" value={candidates.length} />
          <Metric label="Approved & submitted" value={submitted.length} />
          <Metric label="Rejected by gate" value={rejected.length} />
        </div>
        <p className="muted">
          Verify broker chain field names with a paper round-trip before
          first live options submission. The worker caps chain fetches per
          tick to preserve data quota.
        </p>
      </article>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Recent cycles</h2>
            <p>Newest first. Each row is one underlying evaluated this tick.</p>
          </div>
          <span className="state-pill">{records.length} records</span>
        </div>
        {records.length === 0 ? (
          <div className="empty-state">
            No options cycles recorded yet. Once the autopilot tick runs with
            options enabled, results will appear here.
          </div>
        ) : (
          <div className="order-table">
            <div className="order-row table-head">
              <span>Underlying</span>
              <span>Lane</span>
              <span>Contract</span>
              <span>State</span>
              <span>Note</span>
            </div>
            {records.map((row, index) => {
              const p = row.payload;
              const c = p.candidate;
              const d = p.decision;
              const state = p.receipt
                ? `submitted (${p.receipt.status})`
                : d?.state ?? "no_candidate";
              const lane = c?.strategy_id ?? "—";
              const contract = c
                ? `${c.contract.contract_type} ${c.contract.strike} ${c.contract.expiration}`
                : "—";
              return (
                <div className="order-row" key={`${p.underlying}-${index}`}>
                  <strong className="symbol">{p.underlying}</strong>
                  <span>{lane}</span>
                  <span>{contract}</span>
                  <span>{state}</span>
                  <span>{p.note ?? (d ? d.reasons[0] : "")}</span>
                </div>
              );
            })}
          </div>
        )}
      </article>

      {candidates.length > 0 && (
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Latest candidate detail</h2>
              <p>Trigger evidence the lane recorded.</p>
            </div>
          </div>
          {candidates.slice(0, 5).map((row, index) => {
            const c = row.payload.candidate!;
            return (
              <div className="candidate-card" key={`${row.payload.underlying}-detail-${index}`}>
                <header>
                  <strong>{row.payload.underlying}</strong>
                  <span className="state-pill">{c.strategy_id}</span>
                  <span>
                    {c.contracts}× {c.contract.contract_type}{" "}
                    {c.contract.strike} {c.contract.expiration}
                  </span>
                  <span>
                    credit{" "}
                    {c.expected_credit !== null
                      ? currencyFormatter(c.expected_credit)
                      : "—"}
                  </span>
                  <span>
                    collateral {currencyFormatter(c.collateral_required)}
                  </span>
                </header>
                <ul>
                  {c.trigger_evidence.map((reason, ridx) => (
                    <li key={ridx}>{reason}</li>
                  ))}
                </ul>
              </div>
            );
          })}
        </article>
      )}
    </DashboardShell>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  );
}
