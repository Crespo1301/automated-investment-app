import { ProviderPosture } from "@/components/analytics-visuals";
import { DashboardShell } from "@/components/dashboard-shell";
import {
  getDailyRecap,
  getReconciliation,
  getSafetyStatus,
} from "@/lib/server-data";

const fundedAnthropic = Boolean(process.env.ANTHROPIC_API_KEY);
const fundedOpenAi = Boolean(process.env.OPENAI_API_KEY);

const handoffItems = [
  "API must be online before dashboard actions show live Alpaca state.",
  "Autopilot still requires the separate local loop process.",
  "Paid AI providers are optional while deterministic local fallback is active.",
  "Claude design pass preserves controls, confirmations, PDT copy, and risk language.",
];

export default async function SettingsPage() {
  const [reconciliation, safety, recap] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getDailyRecap(),
  ]);
  const account = reconciliation?.account ?? null;
  const autopilot = safety?.autopilot_state;

  return (
    <DashboardShell
      active="Settings"
      account={account}
      killSwitchEnabled={safety?.safety_state.kill_switch_enabled ?? false}
      marketClock={safety?.market_clock ?? null}
      portfolioDelta={recap?.portfolio_delta ?? null}
      openPositions={reconciliation?.positions.length ?? 0}
      title="Operator settings"
    >
      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Scoring providers</h2>
            <p>Tier order: Anthropic → OpenAI → deterministic local. Local always carries weight.</p>
          </div>
          <span className="state-pill state-info">3-tier failover</span>
        </div>
        <ProviderPosture
          providers={recap?.provider_usage ?? []}
          fundedAnthropic={fundedAnthropic}
          fundedOpenAi={fundedOpenAi}
        />
      </article>

      <section className="content-grid">
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Autopilot runtime</h2>
              <p>Local state pulled from the API audit file.</p>
            </div>
            <span className={autopilot?.enabled ? "state-pill state-warning" : "state-pill state-blocked"}>
              {autopilot?.enabled ? "armed" : "off"}
            </span>
          </div>
          <div className="autopilot-grid">
            <div className="autopilot-row">
              <span>Interval</span>
              <strong>{autopilot ? `${autopilot.interval_seconds}s` : "offline"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Scope</span>
              <strong>{autopilot?.market_open_only ? "market open only" : "all sessions"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Entries</span>
              <strong>{autopilot?.entry_execution_enabled ? "enabled" : "locked"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Exits</span>
              <strong>{autopilot?.exit_execution_enabled ? "enabled" : "locked"}</strong>
            </div>
            <div className="autopilot-row">
              <span>Last action</span>
              <strong>{autopilot?.last_action ?? "none"}</strong>
            </div>
          </div>
        </article>

        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Claude handoff</h2>
              <p>Design constraints and implementation guardrails.</p>
            </div>
          </div>
          <div className="list">
            {handoffItems.map((item) => (
              <div className="list-item" key={item}>
                <p className="thesis">{item}</p>
              </div>
            ))}
          </div>
        </article>
      </section>
    </DashboardShell>
  );
}
