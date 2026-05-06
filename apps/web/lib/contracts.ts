export type MetricCard = {
  label: string;
  value: string;
  change?: string | null;
};

export type PositionSummary = {
  symbol: string;
  name: string;
  allocation: number;
  unrealized_pnl_percent: number;
  thesis: string;
};

export type StrategyStatus = {
  name: string;
  mode: "paper" | "live" | "disabled";
  last_event: string;
  risk_state: "healthy" | "warning" | "blocked";
};

export type DashboardSnapshot = {
  metrics: MetricCard[];
  positions: PositionSummary[];
  strategies: StrategyStatus[];
  alerts: string[];
};

export type PipelineStep = {
  name: string;
  owner: string;
  input_contract: string;
  output_contract: string;
  purpose: string;
};

export type PipelinePreview = {
  pipeline_name: string;
  summary: string;
  steps: PipelineStep[];
};

export type BrokerAccountStatus = {
  broker: string;
  account_mode: "paper" | "live";
  account_id_hint: string;
  status: string;
  currency: string;
  buying_power: number;
  cash: number;
  portfolio_value: number;
  pattern_day_trader: boolean | null;
};

export type BrokerOrderSummary = {
  broker_order_id: string;
  client_order_id?: string | null;
  symbol: string;
  side: string;
  order_type: string;
  status: string;
  submitted_quantity?: number | null;
  submitted_notional?: number | null;
  filled_quantity: number;
  filled_average_price?: number | null;
  submitted_at?: string | null;
  filled_at?: string | null;
};

export type BrokerPositionSummary = {
  symbol: string;
  quantity: number;
  market_value: number;
  cost_basis: number;
  unrealized_pl: number;
  unrealized_pl_percent: number;
  current_price?: number | null;
};

export type BrokerReconciliationSnapshot = {
  account: BrokerAccountStatus;
  orders: BrokerOrderSummary[];
  positions: BrokerPositionSummary[];
};

export type MarketClockStatus = {
  is_open: boolean;
  timestamp?: string | null;
  next_open?: string | null;
  next_close?: string | null;
};

export type SafetyState = {
  kill_switch_enabled: boolean;
  reason?: string | null;
  updated_at: string;
};

export type AuditSummary = {
  pipeline_runs: number;
  reconciliation_snapshots: number;
  order_events: number;
  last_event_at?: string | null;
  latest_order_status?: string | null;
  latest_order_symbol?: string | null;
  latest_order_notional?: number | null;
  safety_state: SafetyState;
  market_clock?: MarketClockStatus | null;
  notes: string[];
};
