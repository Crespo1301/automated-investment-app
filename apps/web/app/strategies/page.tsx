import {
  ProviderPosture,
  ScoreAnatomy,
  SessionScorecard,
  StrategyFunnel,
} from "@/components/analytics-visuals";
import { DashboardShell } from "@/components/dashboard-shell";
import { getDailyRecap, getReconciliation, getSafetyStatus } from "@/lib/server-data";

const fundedAnthropic = Boolean(process.env.ANTHROPIC_API_KEY);
const fundedOpenAi = Boolean(process.env.OPENAI_API_KEY);

const STRATEGY_LANES = [
  {
    id: "opening_range_breakout_v1",
    label: "Opening range breakout",
    prior: 0.78,
    note: "Breaks of the first 5–15 minute range with volume confirmation.",
  },
  {
    id: "vwap_reclaim_v1",
    label: "VWAP reclaim",
    prior: 0.73,
    note: "Symbols reclaiming VWAP after a controlled pullback.",
  },
  {
    id: "relative_volume_spike_v1",
    label: "Relative volume spike",
    prior: 0.71,
    note: "Outsized volume vs. recent baseline with directional pressure.",
  },
  {
    id: "pullback_continuation_v1",
    label: "Pullback continuation",
    prior: 0.7,
    note: "Trend-aligned pullback recoveries off prior support.",
  },
  {
    id: "high_upside_momentum_v1",
    label: "High-upside momentum",
    prior: 0.62,
    note: "Riskier lane for stronger moves, larger volume expansion, supportive market regime, and cleaner spreads.",
  },
  {
    id: "micro_breakout_v1",
    label: "Micro breakout (starter)",
    prior: 0.66,
    note: "Default starter lane for tiny live capital.",
  },
];

export default async function StrategiesPage() {
  const [reconciliation, safety, recap] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getDailyRecap(),
  ]);

  const account = reconciliation?.account ?? null;

  return (
    <DashboardShell
      active="Strategies"
      account={account}
      killSwitchEnabled={safety?.safety_state.kill_switch_enabled ?? false}
      marketClock={safety?.market_clock ?? null}
      portfolioDelta={recap?.portfolio_delta ?? null}
      openPositions={reconciliation?.positions.length ?? 0}
      title="Strategy intelligence"
    >
      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Session funnel</h2>
            <p>Candidate → approved → submitted, today.</p>
          </div>
        </div>
        <SessionScorecard recap={recap ?? null} />
        <div style={{ height: 14 }} />
        <StrategyFunnel strategies={recap?.strategy_usage ?? []} />
      </article>

      <section className="content-grid">
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Scoring posture</h2>
              <p>Tier ordering today: Claude → OpenAI → deterministic local.</p>
            </div>
            <span className="state-pill state-info">3-tier failover</span>
          </div>
          <ProviderPosture
            providers={recap?.provider_usage ?? []}
            fundedAnthropic={fundedAnthropic}
            fundedOpenAi={fundedOpenAi}
          />
          <p className="thesis" style={{ marginTop: 12 }}>
            With API keys unfunded the deterministic local layer carries scoring. Its capped score (0.88 max) and explicit
            concerns are surfaced on every candidate so the risk engine remains the final execution gate.
          </p>
        </article>

        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Local fallback anatomy</h2>
              <p>Weights inside the deterministic scorer. Sums to 100% before cap.</p>
            </div>
            <span className="state-pill state-info">cap 0.88</span>
          </div>
          <ScoreAnatomy />
          <p className="thesis" style={{ marginTop: 12 }}>
            The fallback now uses available market context instead of ignoring it. Missing feeds stay neutral; adverse
            spread, depth, volatility, market-regime, or headline signals reduce conviction before risk review.
          </p>
        </article>
      </section>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Context Inputs</h2>
            <p>What each live Alpaca event tries to carry into candidate scoring.</p>
          </div>
          <span className="state-pill state-info">feed-aware</span>
        </div>
        <div className="visual-grid">
          {[
            ["Spread", "Latest bid/ask spread in basis points to avoid paying too much friction."],
            ["Depth Proxy", "Top-of-book bid/ask size imbalance to spot pressure near the touch."],
            ["Volatility", "Recent minute-bar realized volatility classified as calm, normal, elevated, or extreme."],
            ["Market Regime", "SPY and QQQ benchmark drift classified as risk-on, neutral, or risk-off."],
            ["News", "Recent Alpaca headlines with a deterministic positive, neutral, or negative hint."],
          ].map(([label, description]) => (
            <div className="mini-panel" key={label}>
              <span className="metric-label">{label}</span>
              <strong>{description}</strong>
            </div>
          ))}
        </div>
      </article>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Strategy lanes</h2>
            <p>Active lanes and their strategy prior used by the local scorer.</p>
          </div>
        </div>
        <div className="visual-stack">
          {STRATEGY_LANES.map((lane) => (
            <div className="bar-row" key={lane.id}>
              <div className="bar-label">
                <strong>{lane.label}</strong>
                <span>{lane.note}</span>
              </div>
              <div className="bar-track">
                <span className="bar-fill" style={{ width: `${lane.prior * 100}%` }} />
              </div>
              <span className="positive">{(lane.prior * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </article>
    </DashboardShell>
  );
}
