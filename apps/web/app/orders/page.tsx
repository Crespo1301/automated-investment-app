import { DashboardShell } from "@/components/dashboard-shell";
import { cleanEnum, currencyFormatter } from "@/lib/format";
import type { BrokerOrderSummary } from "@/lib/contracts";
import { getDailyRecap, getReconciliation, getSafetyStatus, getTradingConfig } from "@/lib/server-data";

const TERMINAL_STATUSES = new Set([
  "FILLED",
  "CANCELED",
  "EXPIRED",
  "REJECTED",
  "DONE_FOR_DAY",
  "REPLACED",
]);

export default async function OrdersPage() {
  const [reconciliation, safety, recap, tradingConfig] = await Promise.all([
    getReconciliation(),
    getSafetyStatus(),
    getDailyRecap(),
    getTradingConfig(),
  ]);
  const account = reconciliation?.account ?? null;
  const orders = reconciliation?.orders ?? [];
  const estimatedPnl = estimateNetPnlByOrder(orders, tradingConfig?.max_entry_spread_bps ?? 40);
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
      providerUsage={recap?.provider_usage ?? null}
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
        <OrderTable
          orders={open}
          emptyLabel="No working orders."
          estimatedPnl={estimatedPnl}
        />
      </article>

      <article className="panel">
        <div className="section-title">
          <div>
            <h2>Recent</h2>
            <p>Filled, canceled, expired, replaced.</p>
          </div>
          <span className="state-pill">{closed.length} returned</span>
        </div>
        <OrderTable
          orders={closed}
          emptyLabel="No completed orders returned."
          estimatedPnl={estimatedPnl}
        />
      </article>
    </DashboardShell>
  );
}

function OrderTable({
  orders,
  emptyLabel,
  estimatedPnl,
}: {
  orders: BrokerOrderSummary[];
  emptyLabel: string;
  estimatedPnl: Map<string, NetPnlEstimate>;
}) {
  return (
    <div className="order-table">
      <div className="order-row table-head">
        <span>Symbol</span>
        <span>Side</span>
        <span>Status</span>
        <span>Notional</span>
        <span>Filled</span>
        <span>Est. Net</span>
      </div>
      {orders.length > 0 ? (
        orders.map((order) => {
          const pnl = estimatedPnl.get(order.broker_order_id);
          return (
            <div className="order-row" key={order.broker_order_id}>
              <strong className="symbol">{order.symbol}</strong>
              <span>{cleanEnum(order.side)}</span>
              <span>{cleanEnum(order.status)}</span>
              <span>{order.submitted_notional ? currencyFormatter(order.submitted_notional) : "qty"}</span>
              <span>{order.filled_quantity.toFixed(6)}</span>
              <span className={pnl ? (pnl.net >= 0 ? "positive" : "negative") : ""}>
                {pnl ? `${pnl.net >= 0 ? "+" : ""}${currencyFormatter(pnl.net)}` : "—"}
              </span>
            </div>
          );
        })
      ) : (
        <div className="empty-state">{emptyLabel}</div>
      )}
    </div>
  );
}

type BuyLot = {
  quantity: number;
  price: number;
};

type NetPnlEstimate = {
  gross: number;
  estimatedSpreadCost: number;
  net: number;
};

function estimateNetPnlByOrder(
  orders: BrokerOrderSummary[],
  maxEntrySpreadBps: number,
): Map<string, NetPnlEstimate> {
  const estimates = new Map<string, NetPnlEstimate>();
  const lotsBySymbol = new Map<string, BuyLot[]>();
  const halfSpreadRate = Math.max(0, maxEntrySpreadBps) / 2 / 10_000;
  const sorted = orders
    .filter((order) => order.filled_quantity > 0 && order.filled_average_price)
    .sort((a, b) => {
      const aTime = a.filled_at ? Date.parse(a.filled_at) : 0;
      const bTime = b.filled_at ? Date.parse(b.filled_at) : 0;
      return aTime - bTime;
    });

  for (const order of sorted) {
    const side = cleanEnum(order.side).toLowerCase();
    const symbol = order.symbol.toUpperCase();
    const price = order.filled_average_price ?? 0;
    if (side === "buy") {
      const lots = lotsBySymbol.get(symbol) ?? [];
      lots.push({ quantity: order.filled_quantity, price });
      lotsBySymbol.set(symbol, lots);
      continue;
    }

    if (side !== "sell") continue;

    const lots = lotsBySymbol.get(symbol) ?? [];
    let remaining = order.filled_quantity;
    let gross = 0;
    let estimatedSpreadCost = 0;

    while (remaining > 0 && lots.length > 0) {
      const lot = lots[0];
      const matched = Math.min(remaining, lot.quantity);
      gross += matched * (price - lot.price);
      estimatedSpreadCost += matched * (price + lot.price) * halfSpreadRate;
      lot.quantity -= matched;
      remaining -= matched;
      if (lot.quantity <= 0.000000001) lots.shift();
    }

    if (gross !== 0 || estimatedSpreadCost !== 0) {
      estimates.set(order.broker_order_id, {
        gross,
        estimatedSpreadCost,
        net: gross - estimatedSpreadCost,
      });
    }
  }

  return estimates;
}
