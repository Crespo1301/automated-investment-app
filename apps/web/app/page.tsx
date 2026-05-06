import { StatusCard } from "@/components/status-card";
import { LivePerformancePanel } from "@/components/live-performance-panel";
import { revalidatePath } from "next/cache";
import type {
  AuditSummary,
  BrokerReconciliationSnapshot,
  DashboardSnapshot,
  PipelinePreview,
  ProtectionPlan,
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

async function postApi(path: string) {
  "use server";

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      method: "POST",
    });

    if (!response.ok) {
      console.error(`Investment API request failed: ${path} returned ${response.status}`);
    }
  } catch (error) {
    console.error(`Investment API request failed: ${path}`, error);
  }

  revalidatePath("/");
}

async function refreshDashboard() {
  "use server";

  revalidatePath("/");
}

async function cancelOpenOrders() {
  "use server";

  await postApi("/api/broker/cancel-open-orders");
}

async function enableKillSwitch(formData: FormData) {
  "use server";

  const reason = String(formData.get("reason") || "Paused from dashboard.");
  await postApi(`/api/safety/kill-switch/enable?reason=${encodeURIComponent(reason)}`);
}

async function disableKillSwitch() {
  "use server";

  await postApi("/api/safety/kill-switch/disable");
}

async function runTradingCycle(formData: FormData) {
  "use server";

  const confirmation = String(formData.get("confirmation") || "").trim();
  if (confirmation !== "RUN LIVE") {
    return;
  }

  await postApi("/api/trading/run-cycle");
}

async function queueForOpen(formData: FormData) {
  "use server";

  const confirmation = String(formData.get("confirmation") || "").trim();
  if (confirmation !== "QUEUE OPEN") {
    return;
  }

  await postApi("/api/trading/queue-for-open");
}

async function enableAutopilot(formData: FormData) {
  "use server";

  const confirmation = String(formData.get("confirmation") || "").trim();
  if (confirmation !== "ENABLE AUTO") {
    return;
  }

  const reason = String(formData.get("reason") || "Armed from dashboard.");
  await postApi(`/api/autopilot/enable?reason=${encodeURIComponent(reason)}`);
}

async function disableAutopilot() {
  "use server";

  await postApi("/api/autopilot/disable");
}

async function runAutopilotTick(formData: FormData) {
  "use server";

  const confirmation = String(formData.get("confirmation") || "").trim();
  if (confirmation !== "AUTO TICK") {
    return;
  }

  await postApi("/api/autopilot/tick");
}

async function sellPosition(formData: FormData) {
  "use server";

  const symbol = String(formData.get("symbol") || "").trim().toUpperCase();
  const confirmation = String(formData.get("confirmation") || "").trim().toUpperCase();
  if (!symbol || confirmation !== `SELL ${symbol}`) {
    return;
  }

  await postApi(`/api/broker/positions/${encodeURIComponent(symbol)}/sell-market`);
}

async function getReconciliation(): Promise<BrokerReconciliationSnapshot | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/broker/reconciliation`, {
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

async function getSafetyStatus(): Promise<AuditSummary | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/safety/status`, {
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

async function getProtectionPlan(): Promise<ProtectionPlan | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/risk/protection-plan`, {
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
  const safety = await getSafetyStatus();
  const protectionPlan = await getProtectionPlan();
  const account = reconciliation?.account;
  const orders = reconciliation?.orders ?? [];
  const positions = reconciliation?.positions ?? [];
  const killSwitchEnabled = safety?.safety_state.kill_switch_enabled ?? false;
  const autopilot = safety?.autopilot_state;
  const marketOpen = safety?.market_clock?.is_open ?? false;
  const openOrders = orders.filter((order) =>
    ["ACCEPTED", "NEW", "PENDING_NEW", "PARTIALLY_FILLED", "PENDING_CANCEL"].includes(
      cleanEnum(order.status).toUpperCase(),
    ),
  );
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
          <span className={killSwitchEnabled ? "status-dot danger-dot" : "status-dot"} />
          {killSwitchEnabled ? "Kill switch on" : account ? `${account.account_mode} broker` : "API offline"}
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
            <span className={marketOpen ? "state-pill state-healthy" : "state-pill state-warning"}>
              {marketOpen ? "Market open" : "Market closed"}
            </span>
          </div>
        </header>

        <section className={account && !killSwitchEnabled ? "notice-row" : "notice-row warning-row"}>
          <strong>
            {killSwitchEnabled
              ? "Kill switch is enabled."
              : account
                ? `${account.account_mode} account connected.`
                : "Backend API offline."}
          </strong>
          <span>
            {killSwitchEnabled
              ? safety?.safety_state.reason ?? "Submissions are blocked until the operator disables the kill switch."
              : account
                ? `Read-only dashboard data is coming from Alpaca account ${account.account_id_hint}.`
              : "Start the FastAPI server to show active Alpaca reconciliation data."}
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

        <LivePerformancePanel />

        <section className="content-grid">
          <div className="stack">
            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Daily Usage</h2>
                  <p>One place for the routine that used to live in terminal commands.</p>
                </div>
              </div>

              <div className="daily-grid">
                {!account ? (
                  <div className="action-warning" role="status">
                    Start the FastAPI server before using kill switch, cancel, or live-cycle actions.
                  </div>
                ) : null}

                <div className="daily-step">
                  <span className="step-number">1</span>
                  <div>
                    <strong>Refresh Broker State</strong>
                    <p className="thesis">Reconcile account, orders, positions, safety, and market clock.</p>
                  </div>
                  <form action={refreshDashboard}>
                    <button className="secondary-action" type="submit">Refresh</button>
                  </form>
                </div>

                <div className="daily-step">
                  <span className="step-number">2</span>
                  <div>
                    <strong>Review Active Risk</strong>
                    <p className="thesis">
                      {openOrders.length} open orders, {positions.length} positions, kill switch{" "}
                      {killSwitchEnabled ? "enabled" : "clear"}.
                    </p>
                  </div>
                  <span className={openOrders.length ? "state-pill state-warning" : "state-pill state-healthy"}>
                    {openOrders.length ? "review" : "clear"}
                  </span>
                </div>

                <div className="daily-step">
                  <span className="step-number">3</span>
                  <div>
                    <strong>Pause Or Resume</strong>
                    <p className="thesis">Use the kill switch before stepping away or changing settings.</p>
                  </div>
                  {killSwitchEnabled ? (
                    <form action={disableKillSwitch}>
                      <button className="secondary-action" disabled={!account} type="submit">Disable</button>
                    </form>
                  ) : (
                    <form action={enableKillSwitch} className="inline-form">
                      <input name="reason" placeholder="Pause reason" />
                      <button className="danger-action" disabled={!account} type="submit">Enable</button>
                    </form>
                  )}
                </div>

                <div className="daily-step">
                  <span className="step-number">4</span>
                  <div>
                    <strong>Cancel Queued Orders</strong>
                    <p className="thesis">Cancel all open broker orders, then refresh reconciliation.</p>
                  </div>
                  <form action={cancelOpenOrders}>
                    <button className="danger-action" disabled={!account} type="submit">Cancel All</button>
                  </form>
                </div>

                <div className="daily-step trading-action">
                  <span className="step-number">5</span>
                  <div>
                    <strong>Queue For Open</strong>
                    <p className="thesis">
                      Type QUEUE OPEN to submit one regular-session order while the market is closed.
                    </p>
                  </div>
                  <form action={queueForOpen} className="inline-form">
                    <input name="confirmation" placeholder="QUEUE OPEN" />
                    <button className="secondary-action" disabled={!account || marketOpen} type="submit">Queue</button>
                  </form>
                </div>

                <div className="daily-step trading-action">
                  <span className="step-number">6</span>
                  <div>
                    <strong>Run One Cycle</strong>
                    <p className="thesis">
                      Type RUN LIVE to submit one configured strategy cycle through the current safeguards.
                    </p>
                  </div>
                  <form action={runTradingCycle} className="inline-form">
                    <input name="confirmation" placeholder="RUN LIVE" />
                    <button className="primary-action" disabled={!account} type="submit">Run</button>
                  </form>
                </div>
              </div>
            </article>

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
                  <span>Action</span>
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
                        <form action={sellPosition} className="inline-form table-action">
                          <input name="symbol" type="hidden" value={position.symbol} />
                          <input name="confirmation" placeholder={`SELL ${position.symbol}`} />
                          <button className="danger-action" disabled={!marketOpen} type="submit">Sell</button>
                        </form>
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
                  <p>Read-only Alpaca order reconciliation from the active account.</p>
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
                  <div className="empty-state">No Alpaca orders returned yet.</div>
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
                  <h2>Autopilot</h2>
                  <p>Supervised loop state for hands-off checks.</p>
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
                  <span>Entry execution</span>
                  <strong>{autopilot?.entry_execution_enabled ? "enabled" : "locked"}</strong>
                </div>
                <div className="autopilot-row">
                  <span>Last heartbeat</span>
                  <strong>{autopilot?.last_heartbeat_at ? new Date(autopilot.last_heartbeat_at).toLocaleTimeString() : "none"}</strong>
                </div>
                <div className="autopilot-row">
                  <span>Last action</span>
                  <strong>{autopilot?.last_action ?? "none"}</strong>
                </div>
              </div>

              {autopilot?.last_error ? (
                <div className="action-warning" role="status">{autopilot.last_error}</div>
              ) : null}

              <div className="autopilot-actions">
                {autopilot?.enabled ? (
                  <form action={disableAutopilot}>
                    <button className="danger-action" disabled={!account} type="submit">Disable</button>
                  </form>
                ) : (
                  <form action={enableAutopilot} className="inline-form">
                    <input name="reason" placeholder="Arm reason" />
                    <input name="confirmation" placeholder="ENABLE AUTO" />
                    <button className="secondary-action" disabled={!account || killSwitchEnabled} type="submit">Enable</button>
                  </form>
                )}

                <form action={runAutopilotTick} className="inline-form">
                  <input name="confirmation" placeholder="AUTO TICK" />
                  <button className="primary-action" disabled={!account || killSwitchEnabled} type="submit">Tick</button>
                </form>
              </div>

              <p className="thesis">
                The dashboard arms autopilot, but the separate worker loop must be running for scheduled checks.
              </p>
            </article>

            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Protection Plan</h2>
                  <p>Read-only exit readiness before unattended entries.</p>
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
                        <strong>{plan.symbol}</strong>
                        <span className={plan.status === "protected" ? "state-pill state-healthy" : "state-pill state-warning"}>
                          {plan.status.replace("_", " ")}
                        </span>
                      </div>
                      <p className="thesis">
                        Suggested review stop:{" "}
                        {plan.suggested_stop_price ? currencyFormatter(plan.suggested_stop_price) : "pending price"}.
                      </p>
                      <p className="thesis">{plan.notes[plan.notes.length - 1]}</p>
                    </div>
                  ))
                ) : (
                  <div className="empty-state">
                    {protectionPlan?.notes[0] ?? "Start the API to load protection status."}
                  </div>
                )}
              </div>
            </article>

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
                  <h2>Safety Controls</h2>
                  <p>Local audit trail and execution guardrails.</p>
                </div>
              </div>
              <div className="list">
                <div className="list-item">
                  <div className="row-top">
                    <strong>Kill Switch</strong>
                    <span className={killSwitchEnabled ? "state-pill state-blocked" : "state-pill state-healthy"}>
                      {killSwitchEnabled ? "enabled" : "clear"}
                    </span>
                  </div>
                  <p className="thesis">
                    {safety?.safety_state.reason ?? "No local kill-switch reason recorded."}
                  </p>
                </div>
                <div className="list-item">
                  <div className="row-top">
                    <strong>Market Session</strong>
                    <span className={marketOpen ? "state-pill state-healthy" : "state-pill state-warning"}>
                      {marketOpen ? "open" : "closed"}
                    </span>
                  </div>
                  <p className="thesis">
                    Next open: {safety?.market_clock?.next_open ?? "unknown"}
                  </p>
                </div>
                <div className="list-item">
                  <div className="row-top">
                    <strong>Audit Trail</strong>
                    <span className="state-pill">{safety?.order_events ?? 0} events</span>
                  </div>
                  <p className="thesis">
                    {safety
                      ? `${safety.pipeline_runs} runs, ${safety.reconciliation_snapshots} reconciliation snapshots.`
                      : "Start the API to load local audit state."}
                  </p>
                </div>
              </div>
            </article>
          </div>
        </section>
      </section>
    </main>
  );
}
