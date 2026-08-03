import type {
  BrokerPositionSummary,
  DailyTradeRecap,
  PerformancePoint,
  ProviderUsageSummary,
  StrategyUsageSummary,
  SymbolPerformanceSeries,
} from "@/lib/contracts";

// Distinct line colors for the per-symbol return chart. Cycles if a portfolio
// ever holds more names than colors.
const SYMBOL_LINE_COLORS = [
  "#3B82F6",
  "#F59E0B",
  "#10B981",
  "#EF4444",
  "#A855F7",
  "#06B6D4",
  "#EC4899",
  "#84CC16",
];
import { currencyFormatter, percentFormatter } from "@/lib/format";

export function AllocationBars({
  positions,
  portfolioValue,
}: {
  positions: BrokerPositionSummary[];
  portfolioValue: number;
}) {
  return (
    <div className="visual-stack">
      {positions.length > 0 ? (
        positions.map((position) => {
          const allocation = portfolioValue > 0 ? position.market_value / portfolioValue : 0;
          return (
            <div className="bar-row" key={position.symbol}>
              <div className="bar-label">
                <strong className="symbol">{position.symbol}</strong>
                <span>
                  {currencyFormatter(position.market_value)} - {percentFormatter(allocation)}
                </span>
              </div>
              <div className="bar-track" aria-label={`${position.symbol} allocation`}>
                <span className="bar-fill" style={{ width: `${Math.max(4, allocation * 100)}%` }} />
              </div>
              <span className={position.unrealized_pl >= 0 ? "positive" : "negative"}>
                {percentFormatter(position.unrealized_pl_percent)}
              </span>
            </div>
          );
        })
      ) : (
        <div className="empty-state">No open positions to visualize yet.</div>
      )}
    </div>
  );
}

export function PositionPriceBoard({
  positions,
  asOf,
  history,
}: {
  positions: BrokerPositionSummary[];
  // ISO timestamp of the reconciliation snapshot. Server passes
  // ``new Date().toISOString()`` so the operator can see how stale a card is
  // on a slow tape.
  asOf?: string;
  // Optional per-symbol history; when present each card shows a return sparkline.
  history?: SymbolPerformanceSeries[];
}) {
  const stampLabel = (() => {
    if (!asOf) return null;
    try {
      return new Date(asOf).toLocaleTimeString();
    } catch {
      return null;
    }
  })();

  // Visual reference for the move-from-entry micro-track. Anything beyond
  // ±5% saturates the bar. Linear, data-honest, no magic 500 multiplier.
  const PRICE_BOARD_REFERENCE = 0.05;

  return (
    <div className="price-board">
      {positions.length > 0 ? (
        positions.map((position) => {
          const averageEntry =
            position.quantity > 0 && position.cost_basis > 0
              ? position.cost_basis / position.quantity
              : null;
          const moveFromEntry =
            averageEntry && averageEntry > 0 && position.current_price
              ? (position.current_price - averageEntry) / averageEntry
              : null;
          const trackWidth =
            moveFromEntry == null
              ? 4
              : Math.min(
                  100,
                  Math.max(4, (Math.abs(moveFromEntry) / PRICE_BOARD_REFERENCE) * 100),
                );

          // Per-card return sparkline from this symbol's snapshot history.
          const series = history?.find((s) => s.symbol === position.symbol);
          const sparkline = (() => {
            if (!series || series.points.length < 2) return null;
            const values = series.points.map((p) => p.unrealized_pl_percent);
            const low = Math.min(...values);
            const high = Math.max(...values);
            const span = Math.max(0.0001, high - low);
            return series.points
              .map((p, i) => {
                const x = (i / (series.points.length - 1)) * 100;
                const y = 18 - ((p.unrealized_pl_percent - low) / span) * 16;
                return `${x.toFixed(1)},${y.toFixed(1)}`;
              })
              .join(" ");
          })();

          return (
            <article className="price-card" key={position.symbol}>
              <div className="row-top">
                <strong className="symbol">{position.symbol}</strong>
                <span className={position.unrealized_pl >= 0 ? "positive" : "negative"}>
                  {percentFormatter(position.unrealized_pl_percent)}
                </span>
              </div>
              <div className="price-main">
                {position.current_price != null ? currencyFormatter(position.current_price) : "No price"}
              </div>
              {stampLabel ? (
                <div className="price-stamp" aria-label="Snapshot age">
                  as of {stampLabel}
                </div>
              ) : null}
              {sparkline ? (
                <svg
                  viewBox="0 0 100 20"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label={`${position.symbol} return history`}
                  style={{ width: "100%", height: 24, marginTop: 8 }}
                >
                  <polyline
                    points={sparkline}
                    fill="none"
                    stroke={position.unrealized_pl >= 0 ? "#10B981" : "#EF4444"}
                    strokeWidth="1.4"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
              ) : null}
              <div className="price-meta">
                <span>Avg {averageEntry ? currencyFormatter(averageEntry) : "-"}</span>
                <span>Value {currencyFormatter(position.market_value)}</span>
                <span>Qty {position.quantity.toFixed(6)}</span>
                <span className={position.unrealized_pl >= 0 ? "positive" : "negative"}>
                  {currencyFormatter(position.unrealized_pl)}
                </span>
              </div>
              <div className="micro-track" aria-label={`${position.symbol} move vs ±5% reference`}>
                <span
                  className={position.unrealized_pl >= 0 ? "micro-fill positive-fill" : "micro-fill negative-fill"}
                  style={{ width: `${trackWidth}%` }}
                />
              </div>
            </article>
          );
        })
      ) : (
        <div className="empty-state">No open positions to price yet.</div>
      )}
    </div>
  );
}

export function SymbolPerformanceChart({
  series,
}: {
  series: SymbolPerformanceSeries[];
}) {
  // Only symbols seen in two or more snapshots can draw a line.
  const drawable = series.filter((s) => s.points.length >= 2);

  if (drawable.length === 0) {
    return (
      <div className="chart-frame">
        <div className="empty-state">
          Per-symbol lines render once positions appear across two or more reconciliation snapshots.
        </div>
      </div>
    );
  }

  // Shared timeline across every series so lines align on one x-axis even
  // when a symbol was opened later than others.
  const timeline = Array.from(
    new Set(series.flatMap((s) => s.points.map((p) => p.timestamp))),
  ).sort();
  const xOf = (timestamp: string) =>
    timeline.length > 1 ? (timeline.indexOf(timestamp) / (timeline.length - 1)) * 100 : 50;

  // Shared y-scale (unrealized return %) so symbols are directly comparable.
  const allPct = drawable.flatMap((s) => s.points.map((p) => p.unrealized_pl_percent));
  const min = Math.min(0, ...allPct);
  const max = Math.max(0, ...allPct);
  const range = Math.max(0.0001, max - min);
  const yOf = (pct: number) => 44 - ((pct - min) / range) * 36;
  const zeroY = yOf(0);

  return (
    <div>
      <div className="chart-frame">
        <svg
          viewBox="0 0 100 48"
          preserveAspectRatio="none"
          role="img"
          aria-label="Per-symbol unrealized return curves"
        >
          <line
            x1="0"
            x2="100"
            y1={zeroY}
            y2={zeroY}
            stroke="rgba(255,255,255,0.18)"
            strokeWidth="0.3"
            strokeDasharray="1 1"
            vectorEffect="non-scaling-stroke"
          />
          {drawable.map((s, idx) => (
            <polyline
              key={s.symbol}
              points={s.points
                .map(
                  (p) =>
                    `${xOf(p.timestamp).toFixed(2)},${yOf(p.unrealized_pl_percent).toFixed(2)}`,
                )
                .join(" ")}
              fill="none"
              stroke={SYMBOL_LINE_COLORS[idx % SYMBOL_LINE_COLORS.length]}
              strokeWidth="1.4"
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      </div>
      <div
        style={{ display: "flex", flexWrap: "wrap", gap: "8px 16px", marginTop: 10 }}
      >
        {drawable.map((s, idx) => {
          const latest = s.points[s.points.length - 1]?.unrealized_pl_percent ?? 0;
          return (
            <span
              key={s.symbol}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}
            >
              <span
                aria-hidden
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  display: "inline-block",
                  backgroundColor: SYMBOL_LINE_COLORS[idx % SYMBOL_LINE_COLORS.length],
                }}
              />
              <strong className="symbol">{s.symbol}</strong>
              <span className={latest >= 0 ? "positive" : "negative"}>
                {percentFormatter(latest)}
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function StrategyFunnel({ strategies }: { strategies: StrategyUsageSummary[] }) {
  return (
    <div className="visual-grid">
      {strategies.length > 0 ? (
        strategies.map((strategy) => {
          const approvalRate = strategy.candidates > 0 ? strategy.approved / strategy.candidates : 0;
          const submitRate = strategy.candidates > 0 ? strategy.submitted / strategy.candidates : 0;
          return (
            <article className="mini-panel" key={strategy.strategy_id}>
              <div className="row-top">
                <strong>{strategy.strategy_id}</strong>
                <span className="state-pill">
                  {strategy.submitted}/{strategy.candidates}
                </span>
              </div>
              <div className="dual-bars">
                <span style={{ width: `${Math.max(3, approvalRate * 100)}%` }} />
                <span style={{ width: `${Math.max(3, submitRate * 100)}%` }} />
              </div>
              <p className="thesis">
                {percentFormatter(approvalRate)} approved - {percentFormatter(submitRate)} submitted
              </p>
            </article>
          );
        })
      ) : (
        <div className="empty-state">No strategy activity recorded for this session.</div>
      )}
    </div>
  );
}

const PROVIDER_PROFILES: Record<string, { label: string; subtitle: string }> = {
  anthropic: {
    label: "Anthropic Claude",
    subtitle: "Primary reasoning tier",
  },
  openai: {
    label: "OpenAI",
    subtitle: "Secondary model tier",
  },
  local: {
    label: "Deterministic local",
    subtitle: "Always-on fallback - capped 0.80",
  },
  "claude-3-5-sonnet-20241022": {
    label: "Anthropic Claude",
    subtitle: "Primary scorer - requires funded key",
  },
  "gpt-4o-mini": {
    label: "OpenAI GPT-4o mini",
    subtitle: "Secondary scorer - requires funded key",
  },
  "local-manual": {
    label: "Deterministic local",
    subtitle: "Always-on fallback - capped 0.80",
  },
  "local-manual-anthropic-fallback": {
    label: "Deterministic local",
    subtitle: "Engaged after Claude failure",
  },
  "local-manual-openai-fallback": {
    label: "Deterministic local",
    subtitle: "Engaged after OpenAI failure",
  },
  "local-manual-anthropic-openai-fallback": {
    label: "Deterministic local",
    subtitle: "Engaged after Claude + OpenAI failure",
  },
};

function describeProvider(provider: string) {
  if (PROVIDER_PROFILES[provider]) {
    return PROVIDER_PROFILES[provider];
  }
  if (provider.startsWith("local-manual")) {
    return { label: "Deterministic local", subtitle: provider };
  }
  if (provider.includes("claude") || provider.includes("anthropic")) {
    return { label: provider, subtitle: "Anthropic-flavored model" };
  }
  if (provider.includes("gpt") || provider.includes("openai")) {
    return { label: provider, subtitle: "OpenAI-flavored model" };
  }
  return { label: provider, subtitle: "External scorer" };
}

export function ProviderBars({ providers }: { providers: ProviderUsageSummary[] }) {
  const total = Math.max(1, providers.reduce((acc, p) => acc + p.count, 0));

  return (
    <div className="provider-list">
      {providers.length > 0 ? (
        providers.map((provider) => {
          const profile = describeProvider(provider.provider);
          const share = provider.count / total;
          const isLocal = provider.provider === "local" || provider.provider.startsWith("local-manual");
          return (
            <div className="provider-row" key={provider.provider}>
              <div className="provider-name">
                <strong>{profile.label}</strong>
                <span>{profile.subtitle}</span>
              </div>
              <div className="bar-track" style={{ width: 140 }}>
                <span
                  className={isLocal ? "bar-fill alt-fill" : "bar-fill"}
                  style={{ width: `${Math.max(4, share * 100)}%` }}
                />
              </div>
              <div className="provider-count">{provider.count}</div>
            </div>
          );
        })
      ) : (
        <div className="empty-state">No scorer usage recorded today.</div>
      )}
    </div>
  );
}

export function ProviderPosture({
  providers,
  fundedAnthropic,
  fundedOpenAi,
}: {
  providers: ProviderUsageSummary[];
  fundedAnthropic: boolean;
  fundedOpenAi: boolean;
}) {
  const localCount =
    providers
      .filter((p) => p.provider === "local" || p.provider.startsWith("local-manual"))
      .reduce((acc, p) => acc + p.count, 0);
  const claudeCount = providers
    .filter((p) => p.provider === "anthropic" || (p.provider.includes("claude") && !p.provider.startsWith("local-manual")))
    .reduce((acc, p) => acc + p.count, 0);
  const openaiCount = providers
    .filter((p) =>
      p.provider === "openai" ||
      ((p.provider.includes("gpt") || p.provider.includes("openai")) &&
        !p.provider.startsWith("local-manual"))
    )
    .reduce((acc, p) => acc + p.count, 0);

  const tiers = [
    {
      tier: "Tier 1",
      label: "Anthropic Claude",
      subtitle: fundedAnthropic ? "Key configured - primary" : "Key not configured",
      count: claudeCount,
      state: fundedAnthropic ? "state-healthy" : "state-blocked",
      stateLabel: fundedAnthropic ? "Active" : "Unfunded",
    },
    {
      tier: "Tier 2",
      label: "OpenAI",
      subtitle: fundedOpenAi ? "Key configured - secondary" : "Key not configured",
      count: openaiCount,
      state: fundedOpenAi ? "state-healthy" : "state-blocked",
      stateLabel: fundedOpenAi ? "Active" : "Unfunded",
    },
    {
      tier: "Tier 3",
      label: "Deterministic local",
      subtitle: "Always-on - capped 0.80 - no external context",
      count: localCount,
      state: "state-healthy",
      stateLabel: "Live fallback",
    },
  ];

  return (
    <div className="provider-list">
      {tiers.map((t) => (
        <div className="provider-row" key={t.tier}>
          <div className="provider-name">
            <strong>
              {t.tier} - {t.label}
            </strong>
            <span>{t.subtitle}</span>
          </div>
          <span className={`state-pill ${t.state}`}>{t.stateLabel}</span>
          <div className="provider-count">{t.count}</div>
        </div>
      ))}
    </div>
  );
}

const FALLBACK_WEIGHTS = [
  {
    label: "Strategy prior",
    weight: 0.27,
    description: "Historical win-rate prior per lane (opening range, VWAP, volume, pullback, micro breakout).",
  },
  {
    label: "Confidence hint",
    weight: 0.24,
    description: "Strategy-supplied confidence on the candidate before scoring.",
  },
  {
    label: "Trigger evidence",
    weight: 0.18,
    description: "Specificity and keyword quality of trigger evidence; penalizes 'unavailable / weak / stale'.",
  },
  {
    label: "Setup structure",
    weight: 0.11,
    description: "Aggressive small-win structure: opening range, VWAP, volume pressure, pullback recovery.",
  },
  {
    label: "Stop-risk",
    weight: 0.1,
    description: "Risk distance from entry to stop. ≤1.5% → 1.0, ≤3% → 0.75, ≤5% → 0.4, otherwise 0.1.",
  },
  {
    label: "Market context",
    weight: 0.1,
    description: "Spread, top-of-book depth, volatility, SPY/QQQ regime, and headline sentiment when available.",
  },
];

export function ScoreAnatomy() {
  return (
    <div className="score-anatomy">
      {FALLBACK_WEIGHTS.map((row) => (
        <div className="anatomy-row" key={row.label}>
          <div className="anatomy-label">
            <strong>{row.label}</strong>
            <span>{row.description}</span>
          </div>
          <div className="anatomy-weight">{(row.weight * 100).toFixed(0)}%</div>
          <div className="bar-track">
            <span className="bar-fill" style={{ width: `${row.weight * 100 / 0.3 * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProjectionLadder({
  currentValue,
  dailyTargets = [0.005, 0.01, 0.02],
}: {
  currentValue: number;
  dailyTargets?: number[];
}) {
  return (
    <div className="projection-grid">
      {dailyTargets.map((target) => {
        const fiveDay = currentValue * (1 + target) ** 5;
        const twentyDay = currentValue * (1 + target) ** 20;
        return (
          <article className="mini-panel" key={target}>
            <span className="muted">Daily target</span>
            <strong>{percentFormatter(target)}</strong>
            <p className="thesis">5 sessions: {currencyFormatter(fiveDay)}</p>
            <p className="thesis">20 sessions: {currencyFormatter(twentyDay)}</p>
          </article>
        );
      })}
    </div>
  );
}

const HORIZONS = [1, 5, 10, 20, 60, 120];

export function CompoundingMatrix({
  currentValue,
  dailyTargets = [0.005, 0.01, 0.02],
}: {
  currentValue: number;
  dailyTargets?: number[];
}) {
  return (
    <div className="matrix-frame" role="table" aria-label="Compounding scenario matrix">
      <div className="matrix-row" role="row">
        <div className="matrix-cell" role="columnheader">Daily ↓ / Sessions →</div>
        {HORIZONS.map((h) => (
          <div className="matrix-cell" role="columnheader" key={h}>
            {h}d
          </div>
        ))}
      </div>
      {dailyTargets.map((target) => (
        <div className="matrix-row" role="row" key={target}>
          <div className="matrix-cell is-target" role="rowheader">
            {percentFormatter(target)}/d
          </div>
          {HORIZONS.map((h) => {
            const value = currentValue * (1 + target) ** h;
            const aspirational = h >= 60 || target >= 0.02;
            const cellClass = aspirational ? "matrix-cell is-aspirational" : "matrix-cell is-realistic";
            return (
              <div className={cellClass} role="cell" key={h}>
                {currencyFormatter(value)}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

export function PdtMeter({ daytradeCount }: { daytradeCount?: number | null }) {
  // PDT rule eliminated 2026-06-04 (SEC/FINRA Rule 4210 amendment). Verified live
  // on the Alpaca account 2026-06-08 (pattern_day_trader=false, daytrade_count=0
  // despite recent day activity). The day-trade cap is retired: this meter is now
  // informational only — no ceiling, no same-day-exit block, no trapped-entry math.
  const offline = daytradeCount === null || daytradeCount === undefined;
  const used = daytradeCount ?? 0;

  return (
    <div>
      <div className="pdt-meter" aria-label="Day-trade activity (rule retired)">
        <div className="pdt-readout">
          <strong>{offline ? "—" : used}</strong>
          <span>day-trades · 5 BD window</span>
        </div>
        <span className="pdt-retired-badge">PDT RETIRED</span>
      </div>
      <p className="thesis" style={{ marginTop: 10 }}>
        The Pattern Day Trader cap was eliminated on <strong>2026-06-04</strong> and Alpaca now
        reports the account as non-PDT. Intraday rotation is unrestricted — the engine no longer
        rejects or downsizes entries on day-trade slots, and same-day exits are always honored.
        The count above is shown for awareness only; it is not a ceiling.
      </p>
    </div>
  );
}

export function PerformanceSparkline({ points }: { points: PerformancePoint[] }) {
  if (points.length < 2) {
    return (
      <div className="chart-frame">
        <div className="empty-state">Performance history will render after more reconciliation snapshots.</div>
      </div>
    );
  }

  const values = points.map((p) => p.portfolio_value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(0.01, max - min);

  const linePoints = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * 100;
      const y = 44 - ((p.portfolio_value - min) / range) * 36;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const areaPath = `M 0 44 L ${linePoints
    .split(" ")
    .map((pt) => pt.replace(",", " "))
    .join(" L ")} L 100 44 Z`;

  const ticks = [0.25, 0.5, 0.75].map((frac) => ({
    y: 8 + frac * 36,
    value: max - frac * range,
  }));

  return (
    <div className="chart-frame">
      <svg viewBox="0 0 100 48" preserveAspectRatio="none" role="img" aria-label="Portfolio equity curve">
        {ticks.map((t, i) => (
          <line
            key={i}
            x1="0"
            x2="100"
            y1={t.y}
            y2={t.y}
            stroke="rgba(255,255,255,0.04)"
            strokeWidth="0.2"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <path className="chart-area" d={areaPath} />
        <polyline className="chart-line" points={linePoints} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

export function SessionScorecard({ recap }: { recap: DailyTradeRecap | null }) {
  const approvalRate = recap && recap.candidate_count > 0 ? recap.approved_count / recap.candidate_count : 0;
  const actionableCandidates = recap
    ? Math.max(0, recap.candidate_count - recap.pdt_rejected_count)
    : 0;
  const actionableApprovalRate =
    recap && actionableCandidates > 0 ? recap.approved_count / actionableCandidates : 0;
  return (
    <div className="recap-metrics">
      <div>
        <span>Candidates</span>
        <strong>{recap?.candidate_count ?? 0}</strong>
      </div>
      <div>
        <span>Actionable approvals</span>
        <strong>{percentFormatter(actionableApprovalRate)}</strong>
      </div>
      <div>
        <span>Raw approvals</span>
        <strong>{percentFormatter(approvalRate)}</strong>
      </div>
      <div>
        <span>PDT blocks</span>
        <strong>{recap?.pdt_rejected_count ?? 0}</strong>
      </div>
      <div>
        <span>Day Δ</span>
        <strong>
          {recap?.portfolio_delta != null ? currencyFormatter(recap.portfolio_delta) : "-"}
        </strong>
      </div>
    </div>
  );
}
