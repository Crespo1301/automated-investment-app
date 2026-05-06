import { StatusCard } from "@/components/status-card";
import type {
  BrokerReconciliationSnapshot,
  DashboardSnapshot,
  PipelinePreview,
} from "@/lib/contracts";

const demoSnapshot: DashboardSnapshot = {
  metrics: [
    { label: "Net liquidation", value: "$102,480.22", change: "+1.82% today" },
    { label: "Open risk", value: "1.4%", change: "of deployable capital" },
    { label: "Active strategies", value: "2 live / 1 paper" },
    { label: "Signals pending", value: "3", change: "awaiting risk review" },
  ],
  positions: [
    {
      symbol: "NVDA",
      name: "NVIDIA",
      allocation: 0.18,
      unrealized_pnl_percent: 12.3,
      thesis: "Momentum leader tracked by the intraday breakout lane.",
    },
    {
      symbol: "SPY",
      name: "SPDR S&P 500 ETF",
      allocation: 0.34,
      unrealized_pnl_percent: 4.8,
      thesis: "Core benchmark exposure used to measure market regime drift.",
    },
    {
      symbol: "CASH",
      name: "Deployable cash",
      allocation: 0.21,
      unrealized_pnl_percent: 0,
      thesis: "Held back to respect drawdown limits and new-signal capacity.",
    },
  ],
  strategies: [
    {
      name: "Intraday Breakout",
      mode: "live",
      last_event: "Entered NVDA after a volume expansion confirmation.",
      risk_state: "healthy",
    },
    {
      name: "Mean Reversion",
      mode: "paper",
      last_event: "Queued two oversold names for paper validation only.",
      risk_state: "healthy",
    },
    {
      name: "Overnight Swing",
      mode: "disabled",
      last_event: "Awaiting symbol universe and stop policy.",
      risk_state: "warning",
    },
  ],
  alerts: [
    "Broker passthrough is still a scaffold; no orders are routed yet.",
    "AI scoring contract is documented but not wired to a live provider.",
    "Risk engine shape is fixed early so we can preserve paper/live parity.",
  ],
};

const demoPipeline: PipelinePreview = {
  pipeline_name: "Live Pattern To Order Lifecycle",
  summary:
    "Each candidate trade carries provenance through signal generation, AI scoring, risk review, and final execution intent.",
  steps: [
    {
      name: "Market ingress",
      owner: "market-data worker",
      input_contract: "broker/websocket events",
      output_contract: "normalized market event",
      purpose: "Normalize raw provider payloads into one internal event shape.",
    },
    {
      name: "Signal generation",
      owner: "strategy engine",
      input_contract: "normalized event + strategy config",
      output_contract: "trade candidate",
      purpose: "Detect tradeable patterns from a defined strategy lane.",
    },
    {
      name: "AI scoring",
      owner: "ai scorer",
      input_contract: "trade candidate + portfolio context",
      output_contract: "scored trade candidate",
      purpose: "Rank confidence and add explanatory context for the operator.",
    },
    {
      name: "Risk validation",
      owner: "risk engine",
      input_contract: "scored trade candidate + current exposure",
      output_contract: "execution intent or rejection",
      purpose: "Apply sizing, drawdown, concentration, and mode controls.",
    },
    {
      name: "Order execution",
      owner: "broker adapter",
      input_contract: "execution intent",
      output_contract: "broker receipt",
      purpose: "Route approved intents and reconcile the broker response.",
    },
  ],
};

const navItems = ["Overview", "Portfolio", "Strategies", "Risk", "Orders", "Settings"];

const apiBaseUrl = process.env.INVESTMENT_WEB_API_BASE_URL ?? "http://127.0.0.1:8000";

async function getReconciliation(): Promise<BrokerReconciliationSnapshot | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/broker/alpaca/reconciliation`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return response.json();
  } catch {
    return null;
  }
}

function percentFormatter(value: number) {
  return `${Math.round(value * 100)}%`;
}

function currencyFormatter(value: number) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    style: "currency",
  }).format(value);
}

function cleanEnum(value: string) {
  return value.includes(".") ? value.split(".").at(-1) ?? value : value;
}

export default async function HomePage() {
  const reconciliation = await getReconciliation();
  const account = reconciliation?.account;
  const orders = reconciliation?.orders ?? [];
  const positions = reconciliation?.positions ?? [];
  const dashboardMetrics = account
    ? [
        {
          label: "Portfolio value",
          value: currencyFormatter(account.portfolio_value),
          change: `${account.account_mode} account`,
        },
        {
          label: "Buying power",
          value: currencyFormatter(account.buying_power),
          change: account.currency,
        },
        {
          label: "Open positions",
          value: `${positions.length}`,
          change: positions.length === 0 ? "none currently" : "from Alpaca",
        },
        {
          label: "Recent orders",
          value: `${orders.length}`,
          change: orders[0] ? cleanEnum(orders[0].status) : "none",
        },
      ]
    : demoSnapshot.metrics;

  return (
    <main className="app-frame">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">AI</div>
          <div>
            <div className="brand-name">Portfolio Ops</div>
            <div className="brand-subtitle">Local trading worker</div>
          </div>
        </div>
        <nav className="nav-list" aria-label="Main navigation">
          {navItems.map((item) => (
            <a className={item === "Overview" ? "nav-item active" : "nav-item"} href="#" key={item}>
              {item}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" />
          Paper-safe mode
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Automated Investment App</p>
            <h1>Portfolio management console</h1>
          </div>
          <div className="topbar-actions">
            <span className="environment-badge">{account?.currency ?? "USD"}</span>
            <span className="environment-badge">
              {account ? `Alpaca ${account.account_mode}` : "API offline"}
            </span>
            <button className="primary-action" type="button">Run local cycle</button>
          </div>
        </header>

        <section className={account ? "notice-row" : "notice-row warning-row"}>
          <strong>{account ? "Paper account connected." : "Backend API offline."}</strong>
          <span>
            {account
              ? `Read-only dashboard data is coming from Alpaca account ${account.account_id_hint}; live trading remains locked.`
              : "Start the FastAPI server to show live Alpaca paper reconciliation data."}
          </span>
        </section>

        <section className="grid metrics">
          {dashboardMetrics.map((metric) => (
            <StatusCard
              key={metric.label}
              label={metric.label}
              value={metric.value}
              change={metric.change}
            />
          ))}
        </section>

        <section className="content-grid">
          <div className="stack">
            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Portfolio posture</h2>
                  <p>Allocation, conviction notes, and current exposure.</p>
                </div>
              </div>
              <div className="data-table">
                <div className="table-row table-head">
                  <span>Asset</span>
                  <span>Market value</span>
                  <span>P&amp;L</span>
                </div>
                {positions.length > 0
                  ? positions.map((position) => (
                      <div className="table-row" key={position.symbol}>
                        <div>
                          <strong>{position.symbol}</strong>
                          <p>{position.quantity.toFixed(6)} shares</p>
                          <p className="thesis">
                            Current price:{" "}
                            {position.current_price
                              ? currencyFormatter(position.current_price)
                              : "pending"}
                          </p>
                        </div>
                        <span>{currencyFormatter(position.market_value)}</span>
                        <span className={position.unrealized_pl >= 0 ? "positive" : "negative"}>
                          {currencyFormatter(position.unrealized_pl)}
                        </span>
                      </div>
                    ))
                  : demoSnapshot.positions.map((position) => (
                      <div className="table-row" key={position.symbol}>
                        <div>
                          <strong>{position.symbol}</strong>
                          <p>{position.name}</p>
                          <p className="thesis">{position.thesis}</p>
                        </div>
                        <span>{percentFormatter(position.allocation)}</span>
                        <span className={position.unrealized_pnl_percent >= 0 ? "positive" : "negative"}>
                          {position.unrealized_pnl_percent.toFixed(1)}%
                        </span>
                      </div>
                    ))}
              </div>
            </article>

            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Recent broker orders</h2>
                  <p>Read-only Alpaca paper order reconciliation.</p>
                </div>
              </div>
              <div className="order-table">
                <div className="order-row table-head">
                  <span>Symbol</span>
                  <span>Side</span>
                  <span>Status</span>
                  <span>Notional</span>
                  <span>Filled</span>
                </div>
                {orders.length > 0 ? (
                  orders.map((order) => (
                    <div className="order-row" key={order.broker_order_id}>
                      <strong>{order.symbol}</strong>
                      <span>{cleanEnum(order.side)}</span>
                      <span>{cleanEnum(order.status)}</span>
                      <span>
                        {order.submitted_notional
                          ? currencyFormatter(order.submitted_notional)
                          : "qty order"}
                      </span>
                      <span>{order.filled_quantity.toFixed(6)}</span>
                    </div>
                  ))
                ) : (
                  <div className="empty-state">No Alpaca paper orders returned yet.</div>
                )}
              </div>
            </article>

            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>{demoPipeline.pipeline_name}</h2>
                  <p>{demoPipeline.summary}</p>
                </div>
              </div>
              <div className="pipeline-list">
                {demoPipeline.steps.map((step, index) => (
                  <div className="pipeline-step" key={step.name}>
                    <span className="step-number">{index + 1}</span>
                    <div>
                      <div className="row-top">
                        <strong>{step.name}</strong>
                        <span className="muted">{step.owner}</span>
                      </div>
                      <p className="thesis">{step.purpose}</p>
                      <div className="contract-line">
                        {step.input_contract} -&gt; {step.output_contract}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          </div>

          <div className="stack">
            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Strategy lanes</h2>
                  <p>Mode, state, and latest event per lane.</p>
                </div>
              </div>
              <div className="list">
                {demoSnapshot.strategies.map((strategy) => (
                  <div className="list-item strategy-row" key={strategy.name}>
                    <div className="row-top">
                      <strong>{strategy.name}</strong>
                      <span className={`state-pill state-${strategy.risk_state}`}>{strategy.mode}</span>
                    </div>
                    <p className="thesis">{strategy.last_event}</p>
                  </div>
                ))}
              </div>
            </article>

            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Build notes</h2>
                  <p>Integration work before live deployment.</p>
                </div>
              </div>
              <div className="list">
                {demoSnapshot.alerts.map((alert) => (
                  <div className="list-item" key={alert}>
                    <p className="thesis">{alert}</p>
                  </div>
                ))}
              </div>
            </article>
          </div>
        </section>
      </section>
    </main>
  );
}
