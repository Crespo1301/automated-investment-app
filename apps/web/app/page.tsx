import { StatusCard } from "@/components/status-card";
import { LivePerformancePanel } from "@/components/live-performance-panel";
import { revalidatePath } from "next/cache";
import type {
  AuditSummary,
  BrokerReconciliationSnapshot,
  DailyTradeRecap,
  ExitCheckResult,
  PipelinePreview,
  ProtectionPlan,
} from "@/lib/contracts";

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

const navItems = [
  { label: "Overview", href: "#overview" },
  { label: "Portfolio", href: "#portfolio" },
  { label: "Strategies", href: "#strategies" },
  { label: "Risk", href: "#risk" },
  { label: "Orders", href: "#orders" },
  { label: "Settings", href: "#settings" },
];

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

async function protectPosition(formData: FormData) {
  "use server";

  const symbol = String(formData.get("symbol") || "").trim().toUpperCase();
  const confirmation = String(formData.get("confirmation") || "").trim().toUpperCase();
  if (!symbol || confirmation !== `PROTECT ${symbol}`) {
    return;
  }

  await postApi(`/api/broker/positions/${encodeURIComponent(symbol)}/protect-oco`);
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

async function getExitCheck(): Promise<ExitCheckResult | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/risk/exit-check`, {
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

async function getDailyRecap(): Promise<DailyTradeRecap | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/performance/daily-recap`, {
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
  const exitCheck = await getExitCheck();
  const dailyRecap = await getDailyRecap();
  const account = reconciliation?.account;
  const orders = reconciliation?.orders ?? [];
  const positions = reconciliation?.positions ?? [];
  const killSwitchEnabled = safety?.safety_state.kill_switch_enabled ?? false;
  const autopilot = safety?.autopilot_state;
  const marketOpen = safety?.market_clock?.is_open ?? false;
  const strategyLanes = [
    {
      name: "Micro Breakout v1",
      mode: account?.account_mode ?? "offline",
      risk_state: killSwitchEnabled
        ? "blocked"
        : autopilot?.entry_execution_enabled
          ? "warning"
          : "healthy",
      last_event: autopilot?.entry_execution_enabled
        ? "Autonomous entries are armed and scanning the live watchlist for breakout setups."
        : "Entry execution is locked while we keep the live account in watch mode.",
    },
    {
      name: "Exit Monitor",
      mode: autopilot?.exit_execution_enabled ? "live" : "locked",
      risk_state: exitCheck?.signals.length ? "warning" : "healthy",
      last_event: exitCheck?.signals.length
        ? `${exitCheck.signals.length} exit signal waiting on current protections and execution settings.`
        : "No stop-loss or take-profit signals are active right now.",
    },
    {
      name: "Queue For Open",
      mode: marketOpen ? "closed" : "ready",
      risk_state: marketOpen ? "blocked" : "healthy",
      last_event: marketOpen
        ? "Regular session is open, use live execution controls instead of queue-for-open."
        : `Queue-for-open is available until ${safety?.market_clock?.next_open ?? "market open"}.`,
    },
  ];
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
        {
          label: "Day trades",
          value: account.daytrade_count === null || account.daytrade_count === undefined ? "N/A" : `${account.daytrade_count}/3`,
          change: "Alpaca rolling PDT count",
        },
      ]
    : [
        { label: "Portfolio value", value: "Offline", change: "API not connected" },
        { label: "Buying power", value: "Offline", change: "API not connected" },
        { label: "Open positions", value: "0", change: "No broker data yet" },
        { label: "Allowed symbols", value: "Offline", change: "Start the API to load config" },
      ];

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
            <a className={item.label === "Overview" ? "nav-item active" : "nav-item"} href={item.href} key={item.label}>
              {item.label}
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

        <section id="overview" className={account && !killSwitchEnabled ? "notice-row page-anchor" : "notice-row warning-row page-anchor"}>
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

        <section className="grid metrics" aria-label="Account overview metrics">
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

        <section className="recap-grid" aria-label="Daily compounding recap">
          <article className="panel">
            <div className="section-title">
              <div>
                <h2>Daily Recap</h2>
                <p>Provider usage, strategy activity, and portfolio delta for today's loop.</p>
              </div>
              <span className={(dailyRecap?.portfolio_delta ?? 0) >= 0 ? "state-pill state-healthy" : "state-pill state-blocked"}>
                {dailyRecap?.portfolio_delta != null
                  ? `${dailyRecap.portfolio_delta >= 0 ? "+" : ""}${currencyFormatter(dailyRecap.portfolio_delta)}`
                  : "offline"}
              </span>
            </div>

            <div className="recap-metrics">
              <div>
                <span>Runs</span>
                <strong>{dailyRecap?.pipeline_runs ?? 0}</strong>
              </div>
              <div>
                <span>Candidates</span>
                <strong>{dailyRecap?.candidate_count ?? 0}</strong>
              </div>
              <div>
                <span>Approved</span>
                <strong>{dailyRecap?.approved_count ?? 0}</strong>
              </div>
              <div>
                <span>Submitted</span>
                <strong>{dailyRecap?.submitted_orders ?? 0}</strong>
              </div>
            </div>

            <div className="recap-columns">
              <div>
                <h3>Providers</h3>
                <div className="compact-list">
                  {dailyRecap && dailyRecap.provider_usage.length > 0 ? (
                    dailyRecap.provider_usage.map((provider) => (
                      <div className="compact-row" key={provider.provider}>
                        <span>{provider.provider}</span>
                        <strong>{provider.count}</strong>
                      </div>
                    ))
                  ) : (
                    <p className="thesis">No scored candidates recorded today.</p>
                  )}
                </div>
              </div>

              <div>
                <h3>Strategies</h3>
                <div className="compact-list">
                  {dailyRecap && dailyRecap.strategy_usage.length > 0 ? (
                    dailyRecap.strategy_usage.map((strategy) => (
                      <div className="compact-row" key={strategy.strategy_id}>
                        <span>{strategy.strategy_id}</span>
                        <strong>{strategy.submitted}/{strategy.candidates}</strong>
                      </div>
                    ))
                  ) : (
                    <p className="thesis">No strategy candidates recorded today.</p>
                  )}
                </div>
              </div>
            </div>
          </article>
        </section>

        <section className="content-grid">
          <div className="stack">
            <article className="panel" id="settings">
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

            <article className="panel" id="portfolio">
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
                  : (
                    <div className="empty-state">
                      No live Alpaca positions are open yet. This section will populate from broker reconciliation once the account actually holds something.
                    </div>
                  )}
              </div>
            </article>

            <article className="panel" id="orders">
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

            <article className="panel" id="strategies">
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
            <article className="panel" id="risk">
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
                  <span>Exit execution</span>
                  <strong>{autopilot?.exit_execution_enabled ? "enabled" : "locked"}</strong>
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
                      <p className="thesis">
                        Suggested take profit:{" "}
                        {plan.suggested_take_profit_price
                          ? currencyFormatter(plan.suggested_take_profit_price)
                          : "pending price"}.
                      </p>
                      <p className="thesis">{plan.notes[plan.notes.length - 1]}</p>
                      {plan.status === "unprotected" && plan.protection_action === "broker_oco" ? (
                        <form action={protectPosition} className="inline-form">
                          <input name="symbol" type="hidden" value={plan.symbol} />
                          <input name="confirmation" placeholder={`PROTECT ${plan.symbol}`} />
                          <button className="secondary-action" disabled={!marketOpen} type="submit">Protect</button>
                        </form>
                      ) : null}
                      {plan.status === "unprotected" && plan.protection_action === "app_managed" ? (
                        <p className="thesis">
                          Broker OCO is blocked for this fractional quantity. Keep exit monitor enabled while this position is open.
                        </p>
                      ) : null}
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
                  <h2>Exit Signals</h2>
                  <p>App-managed stop-loss and take-profit checks.</p>
                </div>
                <span className={exitCheck?.signals.length ? "state-pill state-warning" : "state-pill state-healthy"}>
                  {exitCheck?.signals.length ? `${exitCheck.signals.length} signal` : "clear"}
                </span>
              </div>

              <div className="list">
                {exitCheck && exitCheck.signals.length > 0 ? (
                  exitCheck.signals.map((signal) => (
                    <div className="list-item" key={`${signal.symbol}-${signal.reason}`}>
                      <div className="row-top">
                        <strong>{signal.symbol}</strong>
                        <span className="state-pill state-warning">{signal.reason.replace("_", " ")}</span>
                      </div>
                      <p className="thesis">
                        Current {currencyFormatter(signal.current_price)}, trigger{" "}
                        {currencyFormatter(signal.trigger_price)}.
                      </p>
                      <p className="thesis">
                        Execution {signal.execution_allowed ? "enabled" : "locked"}.
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="empty-state">
                    {exitCheck?.notes[0] ?? "Start the API to load exit checks."}
                  </div>
                )}
              </div>
            </article>

            <article className="panel">
              <div className="section-title">
                <div>
                  <h2>Strategy lanes</h2>
                  <p>Configured lanes and current live readiness.</p>
                </div>
              </div>
              <div className="list">
                {strategyLanes.map((strategy) => (
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
