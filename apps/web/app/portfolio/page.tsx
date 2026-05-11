import {
  AllocationBars,
  CompoundingMatrix,
  PerformanceSparkline,
  PositionPriceBoard,
} from "@/components/analytics-visuals";
import { DashboardShell } from "@/components/dashboard-shell";
import {
  getDailyRecap,
  getPerformanceHistory,
  getReconciliation,
  getSafetyStatus,
} from "@/lib/server-data";
import { currencyFormatter } from "@/lib/format";

export default async function PortfolioPage() {
  const [reconciliation, safety, history, recap] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getPerformanceHistory(),
    getDailyRecap(),
  ]);

  const account = reconciliation?.account ?? null;
  const positions = reconciliation?.positions ?? [];
  const killSwitchEnabled = safety?.safety_state.kill_switch_enabled ?? false;

  return (
    <DashboardShell
      active="Portfolio"
      account={account}
      killSwitchEnabled={killSwitchEnabled}
      marketClock={safety?.market_clock ?? null}
      portfolioDelta={recap?.portfolio_delta ?? null}
      openPositions={positions.length}
      providerUsage={recap?.provider_usage ?? null}
      title="Portfolio"
    >
      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Equity curve</h2>
            <p>Reconciliation snapshots from this account, oldest left to newest right.</p>
          </div>
          <span className={(recap?.portfolio_delta ?? 0) >= 0 ? "state-pill state-healthy" : "state-pill state-blocked"}>
            {recap?.portfolio_delta != null ? currencyFormatter(recap.portfolio_delta) : "-"} day Δ
          </span>
        </div>
        <PerformanceSparkline points={history?.points ?? []} />
      </article>

      <section className="content-grid">
        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Allocation</h2>
              <p>Position size, exposure share, and unrealized movement.</p>
            </div>
          </div>
          <AllocationBars positions={positions} portfolioValue={account?.portfolio_value ?? 0} />
        </article>

        <article className="panel">
          <div className="section-title">
            <div>
              <h2>Posture</h2>
              <p>Headline values for context with the curve above.</p>
            </div>
          </div>
          <div className="recap-metrics">
            <div>
              <span>Portfolio</span>
              <strong>{account ? currencyFormatter(account.portfolio_value) : "-"}</strong>
            </div>
            <div>
              <span>Cash</span>
              <strong>{account ? currencyFormatter(account.cash) : "-"}</strong>
            </div>
            <div>
              <span>Buying power</span>
              <strong>{account ? currencyFormatter(account.buying_power) : "-"}</strong>
            </div>
            <div>
              <span>Open positions</span>
              <strong>{positions.length}</strong>
            </div>
          </div>
          <p className="thesis" style={{ marginTop: 12 }}>
            Cash is what the loop can deploy without touching open positions. Buying power reflects Alpaca&apos;s broker limits, not a target.
          </p>
        </article>
      </section>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Live Price Board</h2>
            <p>Current broker position prices, average entry, value, and unrealized movement.</p>
          </div>
          <span className="state-pill state-info">broker snapshot</span>
        </div>
        <PositionPriceBoard positions={positions} asOf={new Date().toISOString()} />
      </article>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Compounding lab</h2>
            <p>Scenario framework - what the curve looks like at small daily targets. Not a promise.</p>
          </div>
          <span className="state-pill state-info">scenario only</span>
        </div>
        <CompoundingMatrix currentValue={account?.portfolio_value ?? 0} />
        <p className="thesis" style={{ marginTop: 12 }}>
          Aspirational cells (≥60 sessions or ≥2%/day) are amber to remind you that real trading variance, drawdowns, and PDT
          window throttling break clean compound math. Use the matrix to size targets, not to set expectations.
        </p>
      </article>
    </DashboardShell>
  );
}
