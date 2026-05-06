"use client";

import { useEffect, useMemo, useState } from "react";
import type { PerformanceHistory, PerformancePoint } from "@/lib/contracts";

const emptyHistory: PerformanceHistory = {
  points: [],
  notes: ["Waiting for broker reconciliation history."],
};

function currencyFormatter(value: number) {
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    style: "currency",
  }).format(value);
}

function buildPath(points: PerformancePoint[]) {
  if (points.length < 2) {
    return "";
  }

  const values = points.map((point) => point.portfolio_value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(0.01, max - min);

  return points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 100;
      const y = 42 - ((point.portfolio_value - min) / range) * 34;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export function LivePerformancePanel() {
  const [history, setHistory] = useState<PerformanceHistory>(emptyHistory);

  useEffect(() => {
    let active = true;

    async function loadHistory() {
      try {
        const response = await fetch("/api/performance/history", { cache: "no-store" });
        const payload = (await response.json()) as PerformanceHistory;
        if (active) {
          setHistory(payload);
        }
      } catch {
        if (active) {
          setHistory(emptyHistory);
        }
      }
    }

    void loadHistory();
    const interval = window.setInterval(loadHistory, 15_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const points = history.points;
  const latest = points.at(-1);
  const first = points[0];
  const path = useMemo(() => buildPath(points), [points]);
  const gain = latest && first ? latest.portfolio_value - first.portfolio_value : 0;
  const gainPercent =
    latest && first && first.portfolio_value > 0 ? (gain / first.portfolio_value) * 100 : 0;

  return (
    <article className="panel performance-panel">
      <div className="section-title">
        <div>
          <h2>Live Performance</h2>
          <p>Auto-refreshing account value, buying power, and open risk.</p>
        </div>
        <span className={gain >= 0 ? "state-pill state-healthy" : "state-pill state-blocked"}>
          {gain >= 0 ? "+" : ""}
          {gainPercent.toFixed(2)}%
        </span>
      </div>

      <div className="performance-metrics">
        <div>
          <span>Portfolio</span>
          <strong>{latest ? currencyFormatter(latest.portfolio_value) : "offline"}</strong>
        </div>
        <div>
          <span>Buying Power</span>
          <strong>{latest ? currencyFormatter(latest.buying_power) : "offline"}</strong>
        </div>
        <div>
          <span>Open Orders</span>
          <strong>{latest ? latest.open_orders : 0}</strong>
        </div>
      </div>

      <div className="chart-frame">
        {path ? (
          <svg viewBox="0 0 100 48" role="img" aria-label="Portfolio value trend">
            <path className="chart-area" d={`${path} L 100 48 L 0 48 Z`} />
            <path className="chart-line" d={path} />
          </svg>
        ) : (
          <div className="empty-state">Refresh broker state to build chart history.</div>
        )}
      </div>

      <p className="thesis">{history.notes[0]}</p>
    </article>
  );
}
