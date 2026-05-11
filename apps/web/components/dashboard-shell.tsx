import Link from "next/link";
import type { ReactNode } from "react";
import type {
  BrokerAccountStatus,
  MarketClockStatus,
  ProviderUsageSummary,
} from "@/lib/contracts";
import { currencyFormatter } from "@/lib/format";
import { AutoRefresh } from "@/components/auto-refresh";

type ScoringTierPosture = {
  label: string;
  detail: string;
  variant: "healthy" | "warning" | "neutral";
};

// At-a-glance scoring-tier posture, derived from today's provider_usage
// counts. The dashboard already renders ProviderBars deep inside the
// Strategies tab; this surfaces the headline so the operator knows from
// every page whether Claude/OpenAI carried scoring today or whether the
// deterministic fallback is the only thing in the loop.
function summarizeScoringTier(providers: ProviderUsageSummary[]): ScoringTierPosture | null {
  if (!providers.length) return null;

  let local = 0;
  let anthropic = 0;
  let openai = 0;
  for (const row of providers) {
    const key = row.provider.toLowerCase();
    if (key === "local" || key.startsWith("local-manual")) local += row.count;
    else if (key === "anthropic" || key.includes("claude") || key.includes("anthropic")) anthropic += row.count;
    else if (key === "openai" || key.includes("gpt") || key.includes("openai")) openai += row.count;
  }
  const total = local + anthropic + openai;
  if (total === 0) return null;

  if (anthropic === total) {
    return { label: "Scoring: Claude", detail: `${total}/${total} today`, variant: "healthy" };
  }
  if (openai === total) {
    return { label: "Scoring: OpenAI", detail: `${total}/${total} today`, variant: "healthy" };
  }
  if (local === total) {
    return {
      label: "Scoring: local fallback",
      detail: `${total}/${total} today`,
      variant: "warning",
    };
  }
  // Mixed: model carried some, fallback carried the rest. Lean warning
  // when fallback is the majority so the operator notices model gaps.
  const modelCount = anthropic + openai;
  if (local > modelCount) {
    return {
      label: "Scoring: mostly local",
      detail: `${local}/${total} fallback today`,
      variant: "warning",
    };
  }
  return {
    label: "Scoring: mixed",
    detail: `${modelCount}/${total} via model`,
    variant: "neutral",
  };
}

const navItems = [
  { label: "Overview", href: "/" },
  { label: "Portfolio", href: "/portfolio" },
  { label: "Strategies", href: "/strategies" },
  { label: "Risk", href: "/risk" },
  { label: "Orders", href: "/orders" },
  { label: "Settings", href: "/settings" },
];

type TickerProps = {
  account?: BrokerAccountStatus | null;
  marketClock?: MarketClockStatus | null;
  killSwitchEnabled: boolean;
  portfolioDelta?: number | null;
  openPositions: number;
};

function Ticker({ account, marketClock, killSwitchEnabled, portfolioDelta, openPositions }: TickerProps) {
  const portfolio = account ? currencyFormatter(account.portfolio_value) : "OFFLINE";
  const cash = account ? currencyFormatter(account.cash) : "-";
  const buying = account ? currencyFormatter(account.buying_power) : "-";
  const dt = account?.daytrade_count;
  const pdt = dt === null || dt === undefined ? "N/A" : `${dt}/3`;
  const deltaClass =
    portfolioDelta == null
      ? ""
      : portfolioDelta >= 0
        ? "is-positive"
        : "is-negative";
  const deltaLabel =
    portfolioDelta == null
      ? "-"
      : `${portfolioDelta >= 0 ? "+" : ""}${currencyFormatter(portfolioDelta)}`;
  const sessionLabel = marketClock?.is_open ? "OPEN" : "CLOSED";
  const sessionClass = marketClock?.is_open ? "is-positive" : "";
  const safetyLabel = killSwitchEnabled ? "KILL SWITCH" : "ARMED";
  const safetyClass = killSwitchEnabled ? "is-negative" : "is-positive";

  return (
    <div className="ticker-bar" role="status" aria-label="Account ticker">
      <div className="ticker-cell">
        <span className="ticker-label">Portfolio</span>
        <span className="ticker-value">{portfolio}</span>
        <span className={`ticker-meta ${deltaClass}`}>{deltaLabel} today</span>
      </div>
      <div className="ticker-cell">
        <span className="ticker-label">Cash</span>
        <span className="ticker-value">{cash}</span>
        <span className="ticker-meta">{account?.currency ?? "USD"}</span>
      </div>
      <div className="ticker-cell">
        <span className="ticker-label">Buying power</span>
        <span className="ticker-value">{buying}</span>
        <span className="ticker-meta">{openPositions} open</span>
      </div>
      <div className="ticker-cell">
        <span className="ticker-label">PDT window</span>
        <span className="ticker-value">{pdt}</span>
        <span className="ticker-meta">rolling 5 BD</span>
      </div>
      <div className="ticker-cell">
        <span className="ticker-label">Session</span>
        <span className={`ticker-value ${sessionClass}`}>{sessionLabel}</span>
        <span className="ticker-meta">
          {marketClock?.next_open || marketClock?.next_close
            ? marketClock.is_open
              ? `closes ${marketClock?.next_close ?? "?"}`
              : `opens ${marketClock?.next_open ?? "?"}`
            : "clock offline"}
        </span>
      </div>
      <div className="ticker-cell">
        <span className="ticker-label">Safety</span>
        <span className={`ticker-value ${safetyClass}`}>{safetyLabel}</span>
        <span className="ticker-meta">{account ? `${account.account_mode}` : "no broker"}</span>
      </div>
    </div>
  );
}

type DashboardShellProps = {
  active: string;
  account?: BrokerAccountStatus | null;
  accountMode?: string | null;
  children: ReactNode;
  killSwitchEnabled?: boolean;
  marketOpen?: boolean;
  marketClock?: MarketClockStatus | null;
  portfolioDelta?: number | null;
  openPositions?: number;
  providerUsage?: ProviderUsageSummary[] | null;
  subtitle?: string;
  title: string;
};

export function DashboardShell({
  active,
  account,
  accountMode,
  children,
  killSwitchEnabled = false,
  marketOpen = false,
  marketClock,
  portfolioDelta,
  openPositions = 0,
  providerUsage,
  subtitle = "Automated Investment App",
  title,
}: DashboardShellProps) {
  const mode = account?.account_mode ?? accountMode;
  const scoringTier = summarizeScoringTier(providerUsage ?? []);
  const scoringTierClass = scoringTier
    ? scoringTier.variant === "healthy"
      ? "state-pill state-healthy"
      : scoringTier.variant === "warning"
        ? "state-pill state-warning"
        : "state-pill"
    : "state-pill";

  return (
    <main className="app-frame">
      <AutoRefresh intervalMs={30000} />
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
            <Link
              className={item.label === active ? "nav-item active" : "nav-item"}
              href={item.href}
              key={item.label}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className={killSwitchEnabled ? "status-dot danger-dot" : "status-dot"} />
          {killSwitchEnabled ? "Kill switch on" : mode ? `${mode} broker` : "API offline"}
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{subtitle}</p>
            <h1>{title}</h1>
          </div>
          <div className="topbar-actions">
            <span className="environment-badge">{mode ? `Alpaca ${mode}` : "API offline"}</span>
            <span className={(marketClock?.is_open ?? marketOpen) ? "state-pill state-healthy" : "state-pill state-warning"}>
              {(marketClock?.is_open ?? marketOpen) ? "Market open" : "Market closed"}
            </span>
            <span className={killSwitchEnabled ? "state-pill state-blocked" : "state-pill state-healthy"}>
              {killSwitchEnabled ? "Kill switch" : "Armed"}
            </span>
            {scoringTier ? (
              <span
                className={scoringTierClass}
                title={`${scoringTier.label} - ${scoringTier.detail}`}
              >
                {scoringTier.label}
              </span>
            ) : null}
          </div>
        </header>

        <Ticker
          account={account}
          marketClock={marketClock ?? (marketOpen ? { is_open: true } : null)}
          killSwitchEnabled={killSwitchEnabled}
          portfolioDelta={portfolioDelta}
          openPositions={openPositions}
        />

        {children}
      </section>
    </main>
  );
}
