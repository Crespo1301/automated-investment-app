"""Pydantic models for the first documented service contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class MetricCard(BaseModel):
    """Single dashboard metric for high-level operator visibility."""

    label: str
    value: str
    change: str | None = None


class PositionSummary(BaseModel):
    """Condensed holding row used by the web shell."""

    symbol: str
    name: str
    allocation: float = Field(..., description="Fraction of total equity.")
    unrealized_pnl_percent: float
    thesis: str


class StrategyStatus(BaseModel):
    """Execution toggle and recent state for a strategy lane."""

    name: str
    mode: Literal["paper", "live", "disabled"]
    last_event: str
    risk_state: Literal["healthy", "warning", "blocked"]


class DashboardSnapshot(BaseModel):
    """Operator dashboard payload.

    This contract is intentionally compact so the web layer can start with a
    stable shape while backend storage is still evolving.
    """

    metrics: list[MetricCard]
    positions: list[PositionSummary]
    strategies: list[StrategyStatus]
    alerts: list[str]


class PipelineStep(BaseModel):
    """One step in the trade candidate lifecycle."""

    name: str
    owner: str
    input_contract: str
    output_contract: str
    purpose: str


class PipelinePreview(BaseModel):
    """Friendly representation of the autonomous trading pipeline."""

    pipeline_name: str
    summary: str
    steps: list[PipelineStep]


class HandoffRecord(BaseModel):
    """Documents one passthrough between internal services."""

    handoff_id: str
    source: str
    target: str
    payload: str
    guarantees: list[str]
    failure_modes: list[str]


class HandoffCatalog(BaseModel):
    """List of internal handoffs that future contributors must preserve."""

    items: list[HandoffRecord]


class SystemProfile(BaseModel):
    """Describes the system's intended role and operating posture."""

    mission: str
    posture: str
    primary_broker_target: str
    ai_role: str
    non_negotiables: list[str]

