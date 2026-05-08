import { DashboardShell } from "@/components/dashboard-shell";
import { cleanEnum, currencyFormatter } from "@/lib/format";
import type { BrokerOrderSummary } from "@/lib/contracts";
import { getDailyRecap, getReconciliation, getSafetyStatus } from "@/lib/server-data";

const TERMINAL_STATUSES = new Set([
  "FILLED",
  "CANCELED",
  "EXPIRED",
  "REJECTED",
  "DONE_FOR_DAY",
  "REPLACED",
]);

export default async function OrdersPage() {
  const [reconciliation, safety, recap] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getDailyRecap(),
  ]);
  const account = reconciliation?.account ?? null;
  const orders = reconciliation?.orders ?? [];
  const open = orders.filter(
    (o) => !TERMINAL_STATUSES.has(cleanEnum(o.status).toUpperCase()),
  );
  const closed = orders.filter((o) =>
    TERMINAL_STATUSES.has(cleanEnum(o.status).toUpperCase()),
  );

  return (
    <DashboardShell
      active="Orders"
      account={account}
      killSwitchEnabled={safety?.safety_state.kill_switch_enabled ?? false}
      marketClock={safety?.market_clock ?? null}
      portfolioDelta={recap?.portfolio_delta ?? null}
      openPositions={reconciliation?.positions.length ?? 0}
      title="Order ledger"
    >
      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Open</h2>
            <p>Working broker orders pending fill or cancel.</p>
          </div>
          <span className="state-pill">{open.length} open</span>
        </div>
        <OrderTable orders={open} emptyLabel="No working orders." />
      </article>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Recent</h2>
            <p>Filled, canceled, expired, replaced.</p>
          </div>
          <span className="state-pill">{closed.length} returned</span>
        </div>
        <OrderTable orders={closed} emptyLabel="No completed orders returned." />
      </article>
    </DashboardShell>
  );
}

function OrderTable({
  orders,
  emptyLabel,
}: {
  orders: BrokerOrderSummary[];
  emptyLabel: string;
}) {
  return (
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
            <strong className="symbol">{order.symbol}</strong>
            <span>{cleanEnum(order.side)}</span>
            <span>{cleanEnum(order.status)}</span>
            <span>{order.submitted_notional ? currencyFormatter(order.submitted_notional) : "qty"}</span>
            <span>{order.filled_quantity.toFixed(6)}</span>
          </div>
        ))
      ) : (
        <div className="empty-state">{emptyLabel}</div>
      )}
    </div>
  );
}
