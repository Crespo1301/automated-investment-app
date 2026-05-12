import type {
  AuditSummary,
  BrokerReconciliationSnapshot,
  DailyTradeRecap,
  ExitCheckResult,
  PerformanceHistory,
  ProtectionPlan,
  RiskLimits,
} from "@/lib/contracts";

export const apiBaseUrl = process.env.INVESTMENT_WEB_API_BASE_URL ?? "http://127.0.0.1:8000";

async function getApi<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
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

export function getReconciliation() {
  return getApi<BrokerReconciliationSnapshot>("/api/broker/reconciliation");
}

export function getSafetyStatus() {
  return getApi<AuditSummary>("/api/safety/status");
}

export function getProtectionPlan() {
  return getApi<ProtectionPlan>("/api/risk/protection-plan");
}

export function getExitCheck() {
  return getApi<ExitCheckResult>("/api/risk/exit-check");
}

export function getDailyRecap() {
  return getApi<DailyTradeRecap>("/api/performance/daily-recap");
}

export function getPerformanceHistory() {
  return getApi<PerformanceHistory>("/api/performance/history");
}

export function getTradingConfig() {
  return getApi<RiskLimits>("/api/trading/config");
}

export type OptionsCycleRecord = {
  event_type: string;
  payload: {
    underlying: string;
    note: string | null;
    candidate: {
      strategy_id: string;
      action: string;
      contracts: number;
      expected_credit: number | null;
      collateral_required: number;
      confidence_hint: number;
      contract: {
        occ_symbol: string;
        expiration: string;
        strike: number;
        contract_type: string;
        bid: number | null;
        ask: number | null;
      };
      trigger_evidence: string[];
    } | null;
    decision: {
      state: string;
      approved_contracts: number;
      approved_collateral: number;
      reasons: string[];
    } | null;
    receipt: {
      broker_order_id: string;
      status: string;
      submitted_notional: number | null;
    } | null;
    recorded_at: string;
  };
};

export function getOptionsRecent() {
  return getApi<{
    enabled: boolean;
    max_level: number;
    records: OptionsCycleRecord[];
  }>("/api/options/recent?limit=50");
}
