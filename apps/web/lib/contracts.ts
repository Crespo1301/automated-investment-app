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
  daytrade_count?: number | null;
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

export type RiskLimits = {
  allowed_symbols: string[];
  target_position_percent: number;
  max_open_positions: number;
  max_day_trades_5_business_days: number;
  max_daily_loss: number;
  max_entry_spread_bps: number;
  allow_live_trading: boolean;
  allow_outside_market_hours: boolean;
  duplicate_order_lookback_minutes: number;
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

export type AutopilotState = {
  enabled: boolean;
  reason?: string | null;
  updated_at: string;
  last_heartbeat_at?: string | null;
  last_action?: string | null;
  last_error?: string | null;
  interval_seconds: number;
  market_open_only: boolean;
  entry_execution_enabled: boolean;
  exit_execution_enabled: boolean;
};

export type PositionProtectionPlan = {
  symbol: string;
  quantity: number;
  market_value: number;
  current_price?: number | null;
  average_entry_price?: number | null;
  suggested_stop_price?: number | null;
  suggested_take_profit_price?: number | null;
  suggested_stop_notional?: number | null;
  broker_protection_supported: boolean;
  protection_action: "none" | "app_managed" | "broker_oco";
  status: "protected" | "needs_review" | "unprotected";
  notes: string[];
};

export type ExitSignal = {
  symbol: string;
  reason: "stop_loss" | "small_win" | "take_profit";
  current_price: number;
  average_entry_price: number;
  trigger_price: number;
  quantity: number;
  market_value: number;
  execution_allowed: boolean;
};

export type ExitCheckResult = {
  signals: ExitSignal[];
  submitted_receipts: unknown[];
  notes: string[];
};

export type ProtectionPlan = {
  status: "no_positions" | "ready" | "needs_review" | "unprotected";
  plans: PositionProtectionPlan[];
  notes: string[];
};

export type ProfitLockEntry = {
  symbol: string;
  locked_at?: string | null;
  block_reason: string;
  average_entry_price?: number | null;
  current_price?: number | null;
  market_value?: number | null;
  unrealized_pl?: number | null;
};

export type ProfitLockReport = {
  entries: ProfitLockEntry[];
  notes: string[];
};

export type DefragmentationCandidate = {
  symbol: string;
  market_value: number;
  unrealized_pl: number;
  last_buy_filled_at: string;
  age_minutes: number;
};

export type DefragmentationReport = {
  candidates: DefragmentationCandidate[];
  notes: string[];
};

export type PerformancePoint = {
  timestamp: string;
  portfolio_value: number;
  buying_power: number;
  cash: number;
  open_orders: number;
  open_positions: number;
};

export type PerformanceHistory = {
  points: PerformancePoint[];
  notes: string[];
};

export type SymbolPerformancePoint = {
  timestamp: string;
  market_value: number;
  unrealized_pl: number;
  unrealized_pl_percent: number;
  current_price: number | null;
};

export type SymbolPerformanceSeries = {
  symbol: string;
  points: SymbolPerformancePoint[];
};

export type SymbolPerformanceHistory = {
  series: SymbolPerformanceSeries[];
  notes: string[];
};

export type ProviderUsageSummary = {
  provider: string;
  count: number;
};

export type StrategyUsageSummary = {
  strategy_id: string;
  candidates: number;
  approved: number;
  submitted: number;
};

export type DailyTradeRecap = {
  date: string;
  starting_portfolio_value?: number | null;
  ending_portfolio_value?: number | null;
  portfolio_delta?: number | null;
  pipeline_runs: number;
  candidate_count: number;
  approved_count: number;
  rejected_count: number;
  pdt_rejected_count: number;
  spread_rejected_count: number;
  submitted_orders: number;
  provider_usage: ProviderUsageSummary[];
  strategy_usage: StrategyUsageSummary[];
  notes: string[];
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
  autopilot_state: AutopilotState;
  market_clock?: MarketClockStatus | null;
  notes: string[];
};

export type MorningReadiness = {
  ready_for_watch_mode: boolean;
  ready_for_autonomous_entries: boolean;
  blockers: string[];
  account: BrokerAccountStatus;
  market_clock: MarketClockStatus;
  safety_state: SafetyState;
  autopilot_state: AutopilotState;
  risk_limits: RiskLimits;
  notes: string[];
};
