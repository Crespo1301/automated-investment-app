"""Morning readiness checks for the local trading operator."""

from app.core.config import settings
from app.domain.trading import MarketClockStatus
from app.services.audit_store import get_autopilot_state, get_safety_state
from app.services.broker_adapter import get_active_alpaca_broker
from app.services.local_worker import get_risk_limits


def get_morning_readiness() -> dict[str, object]:
    """Return a compact checklist for starting the trading day."""

    broker = get_active_alpaca_broker()
    account = broker.get_account_status()
    clock = broker.get_market_clock()
    safety = get_safety_state()
    autopilot = get_autopilot_state()
    limits = get_risk_limits()
    blockers = _find_blockers(clock)

    return {
        "ready_for_watch_mode": not safety.kill_switch_enabled and autopilot.enabled,
        "ready_for_autonomous_entries": not blockers,
        "blockers": blockers,
        "account": account.model_dump(mode="json"),
        "market_clock": clock.model_dump(mode="json"),
        "safety_state": safety.model_dump(mode="json"),
        "autopilot_state": autopilot.model_dump(mode="json"),
        "risk_limits": limits.model_dump(mode="json"),
        "notes": [
            "Watch mode means the dashboard and manual ticks are ready.",
            "Autonomous entries require the separate autopilot loop process to be running.",
            "This check cannot see whether your terminal process is running dev:autopilot.",
        ],
    }


def _find_blockers(clock: MarketClockStatus) -> list[str]:
    blockers: list[str] = []
    safety = get_safety_state()
    autopilot = get_autopilot_state()

    if safety.kill_switch_enabled:
        blockers.append("Kill switch is enabled.")
    if not autopilot.enabled:
        blockers.append("Autopilot is not armed.")
    if settings.trading_mode != "live":
        blockers.append("Trading mode is not live.")
    if not settings.allow_live_trading:
        blockers.append("Live trading permission is disabled.")
    if settings.alpaca_paper:
        blockers.append("Alpaca is still in paper mode.")
    if autopilot.market_open_only and not clock.is_open:
        blockers.append("Regular market is currently closed.")
    if not settings.autopilot_allow_entries:
        blockers.append("Autopilot entry execution is locked.")
    if not settings.autopilot_allow_exits:
        blockers.append("Autopilot exit execution is locked.")
    if settings.autopilot_allow_entries:
        broker = get_active_alpaca_broker()
        has_data, reason = broker.has_market_data_access(get_risk_limits().allowed_symbols)
        if not has_data:
            blockers.append(
                "Autonomous entries cannot fetch Alpaca market data."
                + (f" {reason}" if reason else "")
            )

    return blockers
