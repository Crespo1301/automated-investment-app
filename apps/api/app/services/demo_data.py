"""Demo payloads used by the initial dashboard and documentation routes."""

from app.domain.models import (
    DashboardSnapshot,
    HandoffCatalog,
    HandoffRecord,
    MetricCard,
    PipelinePreview,
    PipelineStep,
    PositionSummary,
    StrategyStatus,
    SystemProfile,
)


def get_system_profile() -> SystemProfile:
    """Return the current design posture for the project."""

    return SystemProfile(
        mission=(
            "Run a personal autonomous trading system that can detect live "
            "patterns, score opportunities with AI, and execute under hard "
            "risk controls."
        ),
        posture="Autonomous execution with deterministic risk gates and full auditability.",
        primary_broker_target="Alpaca paper/live trading",
        ai_role=(
            "AI ranks and contextualizes trade candidates; deterministic logic "
            "still sizes, approves, and routes orders."
        ),
        non_negotiables=[
            "Every trade candidate must carry strategy and model provenance.",
            "Risk validation must run before live order creation.",
            "The same contracts should support both paper and live modes.",
            "Operator controls must include pause, exposure review, and kill switch paths.",
        ],
    )


def get_dashboard_snapshot() -> DashboardSnapshot:
    """Return representative data until persistence is wired in."""

    return DashboardSnapshot(
        metrics=[
            MetricCard(label="Net Liquidation", value="$102,480.22", change="+1.82% today"),
            MetricCard(label="Open Risk", value="1.4%", change="of deployable capital"),
            MetricCard(label="Active Strategies", value="2 live / 1 paper"),
            MetricCard(label="Signals Pending", value="3", change="awaiting risk review"),
        ],
        positions=[
            PositionSummary(
                symbol="NVDA",
                name="NVIDIA",
                allocation=0.18,
                unrealized_pnl_percent=12.3,
                thesis="Momentum leader tracked by intraday breakout strategy.",
            ),
            PositionSummary(
                symbol="SPY",
                name="SPDR S&P 500 ETF",
                allocation=0.34,
                unrealized_pnl_percent=4.8,
                thesis="Core benchmark exposure used for market regime comparisons.",
            ),
            PositionSummary(
                symbol="CASH",
                name="Deployable cash",
                allocation=0.21,
                unrealized_pnl_percent=0.0,
                thesis="Reserved for new signals and defensive drawdown controls.",
            ),
        ],
        strategies=[
            StrategyStatus(
                name="Intraday Breakout",
                mode="live",
                last_event="Entered NVDA after volume expansion confirmation.",
                risk_state="healthy",
            ),
            StrategyStatus(
                name="Mean Reversion",
                mode="paper",
                last_event="Watching oversold watchlist names after CPI drift.",
                risk_state="healthy",
            ),
            StrategyStatus(
                name="Overnight Swing",
                mode="disabled",
                last_event="Awaiting symbol universe and stop-loss policy.",
                risk_state="warning",
            ),
        ],
        alerts=[
            "Daily drawdown guardrail is configured but not yet persisted to a broker session.",
            "AI scoring is currently modeled as a contract only; live provider wiring still pending.",
            "Execution lane is scaffolded for paper/live parity but remains in demo mode.",
        ],
    )


def get_pipeline_preview() -> PipelinePreview:
    """Expose a readable pipeline map for the frontend and docs."""

    return PipelinePreview(
        pipeline_name="Live Pattern To Order Lifecycle",
        summary=(
            "Streaming market events become normalized features, then trade "
            "candidates, then risk-approved execution intents. Each step emits "
            "records that can be replayed and audited."
        ),
        steps=[
            PipelineStep(
                name="Market ingress",
                owner="market-data worker",
                input_contract="broker/websocket ticks, bars, and account events",
                output_contract="normalized market event",
                purpose="Convert provider-specific payloads into a common internal shape.",
            ),
            PipelineStep(
                name="Signal generation",
                owner="strategy engine",
                input_contract="normalized market event + strategy config",
                output_contract="trade candidate",
                purpose="Detect setup-specific conditions and emit a candidate with rationale.",
            ),
            PipelineStep(
                name="AI scoring",
                owner="ai scorer",
                input_contract="trade candidate + context window",
                output_contract="scored trade candidate",
                purpose="Rank confidence and add explanatory context without setting position size.",
            ),
            PipelineStep(
                name="Risk validation",
                owner="risk engine",
                input_contract="scored trade candidate + portfolio state",
                output_contract="execution intent or rejection",
                purpose="Apply limits for size, concentration, drawdown, cooldowns, and mode.",
            ),
            PipelineStep(
                name="Order execution",
                owner="broker adapter",
                input_contract="execution intent",
                output_contract="broker order receipt",
                purpose="Translate validated intents into broker-native orders and reconcile status.",
            ),
        ],
    )


def get_handoff_catalog() -> HandoffCatalog:
    """List the key service passthroughs we must preserve as the system grows."""

    return HandoffCatalog(
        items=[
            HandoffRecord(
                handoff_id="market-event-normalization",
                source="market ingress",
                target="feature and signal engine",
                payload="normalized market event",
                guarantees=[
                    "Provider-specific field names are removed before downstream processing.",
                    "Each event includes symbol, timestamp, source, and event kind.",
                    "Events remain replayable for debugging and backtests.",
                ],
                failure_modes=[
                    "Clock skew between sources",
                    "Missing bars or dropped websocket packets",
                    "Provider throttle or disconnect events",
                ],
            ),
            HandoffRecord(
                handoff_id="signal-to-risk",
                source="strategy engine",
                target="risk engine",
                payload="trade candidate",
                guarantees=[
                    "Candidate includes strategy id, trigger evidence, and intended direction.",
                    "Sizing is still advisory at this stage.",
                    "Every candidate has a unique correlation id for audit joins.",
                ],
                failure_modes=[
                    "Strategy emits duplicate candidates",
                    "Feature lag causes stale context",
                    "Misconfigured symbol universe",
                ],
            ),
            HandoffRecord(
                handoff_id="risk-to-execution",
                source="risk engine",
                target="broker adapter",
                payload="execution intent",
                guarantees=[
                    "Intent carries final size, order type, and approved risk budget.",
                    "Rejected candidates are logged with explicit reasons.",
                    "Live and paper modes share the same review structure.",
                ],
                failure_modes=[
                    "Broker rejects order parameters",
                    "Position cache lags actual account state",
                    "Circuit breaker blocks new orders during volatility or outages",
                ],
            ),
        ]
    )

