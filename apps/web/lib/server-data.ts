import type {
  AuditSummary,
  BrokerReconciliationSnapshot,
  DailyTradeRecap,
  ExitCheckResult,
  PerformanceHistory,
  ProtectionPlan,
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
