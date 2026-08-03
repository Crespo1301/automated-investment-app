import { revalidatePath } from "next/cache";
import { ArmingChecklist } from "@/components/arming-checklist";
import { DashboardShell } from "@/components/dashboard-shell";
import { LivePerformancePanel } from "@/components/live-performance-panel";
import { ProviderBars, SessionScorecard } from "@/components/analytics-visuals";
import {
  apiBaseUrl,
  getDailyRecap,
  getExitCheck,
  getMorningReadiness,
  getProtectionPlan,
  getReconciliation,
  getSafetyStatus,
} from "@/lib/server-data";
import { cleanEnum, currencyFormatter } from "@/lib/format";
import type { PipelinePreview } from "@/lib/contracts";

const demoPipeline: PipelinePreview = {
  pipeline_name: "Live Pattern → Order Lifecycle",
  summary:
    "Each candidate carries provenance through ingest, signal, scoring, risk, and execution.",
  steps: [
    {
      name: "Market ingress",
      owner: "market-data worker",
      input_contract: "broker / websocket events",
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
      input_contract: "candidate + portfolio context",
      output_contract: "scored candidate",
      purpose: "Rank confidence and add explanatory context for the operator.",
    },
    {
      name: "Risk validation",
      owner: "risk engine",
      input_contract: "scored candidate + exposure",
      output_contract: "execution intent / rejection",
      purpose: "Apply sizing, drawdown, concentration, PDT, and mode controls.",
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

async function postApi(path: string) {
  "use server";
  try {
    const operatorToken = process.env.INVESTMENT_WEB_OPERATOR_API_TOKEN?.trim();
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
      method: "POST",
      headers: operatorToken ? { Authorization: `Bearer ${operatorToken}` } : undefined,
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
  if (confirmation !== "RUN LIVE") return;
  await postApi("/api/trading/run-cycle");
}

async function queueForOpen(formData: FormData) {
  "use server";
  const confirmation = String(formData.get("confirmation") || "").trim();
  if (confirmation !== "QUEUE OPEN") return;
  await postApi("/api/trading/queue-for-open");
}

async function enableAutopilot(formData: FormData) {
  "use server";
  const confirmation = String(formData.get("confirmation") || "").trim();
  if (confirmation !== "ENABLE AUTO") return;
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
  if (confirmation !== "AUTO TICK") return;
  await postApi("/api/autopilot/tick");
}

async function sellPosition(formData: FormData) {
  "use server";
  const symbol = String(formData.get("symbol") || "").trim().toUpperCase();
  const confirmation = String(formData.get("confirmation") || "").trim().toUpperCase();
  if (!symbol || confirmation !== `SELL ${symbol}`) return;
  // Operator sells by dollar amount. Alpaca only accepts a share quantity on
  // a position sell, so the API converts dollars to shares against live
  // market value. Blank / invalid / non-positive -> whole-position sell.
  const dollarsRaw = String(formData.get("dollars") || "").trim();
  const dollars = Number(dollarsRaw);
  const query =
    dollarsRaw !== "" && Number.isFinite(dollars) && dollars > 0
      ? `?dollars=${dollars}`
      : "";
  await postApi(`/api/broker/positions/${encodeURIComponent(symbol)}/sell-market${query}`);
}

async function protectPosition(formData: FormData) {
  "use server";
  const symbol = String(formData.get("symbol") || "").trim().toUpperCase();
  const confirmation = String(formData.get("confirmation") || "").trim().toUpperCase();
  if (!symbol || confirmation !== `PROTECT ${symbol}`) return;
  await postApi(`/api/broker/positions/${encodeURIComponent(symbol)}/protect-oco`);
}

export default async function HomePage() {
  const [reconciliation, safety, protectionPlan, exitCheck, dailyRecap, morningReadiness] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getProtectionPlan(),
    getExitCheck(),
    getDailyRecap(),
    getMorningReadiness(),
  ]);

  const account = reconciliation?.account ?? null;
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

  return (
    <DashboardShell
      active="Overview"
      account={account}
      killSwitchEnabled={killSwitchEnabled}
      marketClock={safety?.market_clock ?? null}
      marketOpen={marketOpen}
      portfolioDelta={dailyRecap?.portfolio_delta ?? null}
      openPositions={positions.length}
      providerUsage={dailyRecap?.provider_usage ?? null}
      title="Cockpit"
    >
      <section className={account && !killSwitchEnabled ? "notice-row" : "notice-row warning-row"}>
        <strong>
          {killSwitchEnabled
            ? "Kill switch enabled."
            : account
              ? `Alpaca ${account.account_mode} connected.`
              : "Backend API offline."}
        </strong>
        <span>
          {killSwitchEnabled
            ? safety?.safety_state.reason ?? "Submissions are blocked until the operator disables the kill switch."
            : account
              ? `Reconciliation streaming from account ${account.account_id_hint}.`
              : "Start the FastAPI server to show active Alpaca data."}
        </span>
      </section>

      <SessionScorecard recap={dailyRecap ?? null} />

      <section className="content-grid">
        <div className="stack">
          <article className="panel">
            <div className="section-title">
              <div>
                <h2>Operate</h2>
                <p>Daily routine. Each step preserves the typed-confirmation guardrails.</p>
              </div>
            </div>

            <div className="daily-grid">
              {!account ? (
                <div className="action-warning" role="status">
                  Start the FastAPI server before using kill switch, cancel, cycle, or autopilot actions.
                </div>
              ) : null}

              <div className="daily-step">
                <span className="step-number">1</span>
                <div>
                  <strong>Refresh broker state</strong>
                  <p className="thesis">Reconcile account, orders, positions, safety, and market clock.</p>
                </div>
                <form action={refreshDashboard}>
                  <button className="secondary-action" type="submit">Refresh</button>
                </form>
              </div>

              <div className="daily-step">
                <span className="step-number">2</span>
                <div>
                  <strong>Review active risk</strong>
                  <p className="thesis">
                    {openOrders.length} open orders - {positions.length} positions - kill switch{" "}
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
                  <strong>Pause or resume</strong>
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
                  <strong>Cancel queued orders</strong>
                  <p className="thesis">Cancel all open broker orders, then refresh reconciliation.</p>
                </div>
                <form action={cancelOpenOrders}>
                  <button className="danger-action" disabled={!account} type="submit">Cancel All</button>
                </form>
              </div>

              <div className="daily-step trading-action">
                <span className="step-number">5</span>
                <div>
                  <strong>Queue for open</strong>
                  <p className="thesis">Type QUEUE OPEN to submit one regular-session order while the market is closed.</p>
                </div>
                <form action={queueForOpen} className="inline-form">
                  <input name="confirmation" placeholder="QUEUE OPEN" />
                  <button className="secondary-action" disabled={!account || marketOpen} type="submit">Queue</button>
                </form>
              </div>

              <div className="daily-step trading-action">
                <span className="step-number">6</span>
                <div>
                  <strong>Run one cycle</strong>
                  <p className="thesis">Type RUN LIVE to submit one strategy cycle through the current safeguards.</p>
                </div>
                <form action={runTradingCycle} className="inline-form">
                  <input name="confirmation" placeholder="RUN LIVE" />
                  <button className="primary-action" disabled={!account} type="submit">Run</button>
                </form>
              </div>
            </div>
          </article>

          <LivePerformancePanel />

          <article className="panel">
            <div className="section-title">
              <div>
                <h2>Open positions</h2>
                <p>Live Alpaca holdings with typed sell confirmation.</p>
              </div>
              <span className="state-pill">{positions.length} held</span>
            </div>
            <div className="data-table">
              <div className="table-row table-head">
                <span>Asset</span>
                <span>Market value</span>
                <span>P&amp;L</span>
                <span>Action</span>
              </div>
              {positions.length > 0 ? (
                positions.map((position) => (
                  <div className="table-row" key={position.symbol}>
                    <div>
                      <strong className="symbol">{position.symbol}</strong>
                      <p>
                        {position.quantity.toFixed(6)} sh -{" "}
                        {position.current_price ? currencyFormatter(position.current_price) : "pending"}
                      </p>
                    </div>
                    <span>{currencyFormatter(position.market_value)}</span>
                    <span className={position.unrealized_pl >= 0 ? "positive" : "negative"}>
                      {currencyFormatter(position.unrealized_pl)}
                    </span>
                    <form action={sellPosition} className="inline-form table-action">
                      <input name="symbol" type="hidden" value={position.symbol} />
                      <input
                        name="dollars"
                        type="number"
                        min="0"
                        step="0.01"
                        max={position.market_value.toFixed(2)}
                        placeholder={`$ (max ${position.market_value.toFixed(2)})`}
                        aria-label={`Dollar amount to sell for ${position.symbol}, blank sells all`}
                      />
                      <input name="confirmation" placeholder={`SELL ${position.symbol}`} />
                      <button className="danger-action" disabled={!marketOpen} type="submit">Sell</button>
                    </form>
                  </div>
                ))
              ) : (
                <div className="empty-state">
                  No live Alpaca positions are open. This populates from broker reconciliation when the account holds something.
                </div>
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
                      {step.input_contract} → {step.output_contract}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </div>

        <div className="stack">
          <ArmingChecklist readiness={morningReadiness} />

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
              <div className="action-warning" role="status" style={{ marginTop: 12 }}>{autopilot.last_error}</div>
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
                <h2>Protection plan</h2>
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
                    {plan.status === "unprotected" && plan.protection_action === "broker_oco" ? (
                      <form action={protectPosition} className="inline-form" style={{ marginTop: 8 }}>
                        <input name="symbol" type="hidden" value={plan.symbol} />
                        <input name="confirmation" placeholder={`PROTECT ${plan.symbol}`} />
                        <button className="secondary-action" disabled={!marketOpen} type="submit">Protect</button>
                      </form>
                    ) : null}
                    {plan.status === "unprotected" && plan.protection_action === "app_managed" ? (
                      <p className="thesis">
                        Broker OCO blocked for this fractional quantity. Keep exit monitor enabled while this position is open.
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
                <h2>Exit signals</h2>
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
                      <strong className="symbol">{signal.symbol}</strong>
                      <span className="state-pill state-warning">{signal.reason.replace("_", " ")}</span>
                    </div>
                    <p className="thesis">
                      {currencyFormatter(signal.current_price)} vs trigger {currencyFormatter(signal.trigger_price)} -{" "}
                      {signal.execution_allowed ? "execution enabled" : "execution locked"}
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
                <h2>Today&apos;s scoring</h2>
                <p>Provider mix carrying the loop right now.</p>
              </div>
            </div>
            <ProviderBars providers={dailyRecap?.provider_usage ?? []} />
          </article>
        </div>
      </section>
    </DashboardShell>
  );
}
