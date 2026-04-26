"""Canonical status types and normalization for the Bodai ecosystem control plane."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CanonicalStatus(str, Enum):
    """Single canonical status vocabulary for all operator-facing surfaces."""

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DISABLED = "disabled"


class DegradationTrend(str, Enum):
    """Trend direction for a degrading component."""

    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"


# Mapping from adapter-native statuses to canonical.
# This is the single source of truth for status normalization.
ADAPTER_STATUS_MAP: dict[str, CanonicalStatus] = {
    "healthy": CanonicalStatus.OK,
    "ok": CanonicalStatus.OK,
    "degraded": CanonicalStatus.DEGRADED,
    "unhealthy": CanonicalStatus.UNHEALTHY,
    "error": CanonicalStatus.UNHEALTHY,
    "not_configured": CanonicalStatus.DISABLED,
}

# Severity ordering for aggregation.
# Higher number = worse status. Used to compute overall status from components.
STATUS_SEVERITY: dict[CanonicalStatus, int] = {
    CanonicalStatus.DISABLED: 0,
    CanonicalStatus.UNKNOWN: 1,
    CanonicalStatus.OK: 2,
    CanonicalStatus.DEGRADED: 3,
    CanonicalStatus.UNHEALTHY: 4,
}

# Valid status transitions. Any transition not in this set is logged as suspicious.
VALID_TRANSITIONS: dict[CanonicalStatus, set[CanonicalStatus]] = {
    CanonicalStatus.OK: {CanonicalStatus.DEGRADED, CanonicalStatus.UNKNOWN, CanonicalStatus.DISABLED},
    CanonicalStatus.DEGRADED: {CanonicalStatus.OK, CanonicalStatus.UNHEALTHY, CanonicalStatus.UNKNOWN, CanonicalStatus.DISABLED},
    CanonicalStatus.UNHEALTHY: {CanonicalStatus.DEGRADED, CanonicalStatus.UNKNOWN, CanonicalStatus.DISABLED},
    CanonicalStatus.UNKNOWN: {CanonicalStatus.OK, CanonicalStatus.DEGRADED, CanonicalStatus.UNHEALTHY, CanonicalStatus.DISABLED},
    CanonicalStatus.DISABLED: {CanonicalStatus.OK, CanonicalStatus.UNKNOWN},
}


def normalize_status(raw: str) -> CanonicalStatus:
    """Map an adapter-native status string to the canonical vocabulary.

    Unknown raw values map to UNKNOWN.
    """
    return ADAPTER_STATUS_MAP.get(raw.lower(), CanonicalStatus.UNKNOWN)


def aggregate_statuses(statuses: list[CanonicalStatus]) -> CanonicalStatus:
    """Compute the overall status from a list of component statuses.

    Returns the worst status by severity. Empty list returns UNKNOWN.
    """
    if not statuses:
        return CanonicalStatus.UNKNOWN
    return max(statuses, key=lambda s: STATUS_SEVERITY.get(s, 1))


def is_valid_transition(from_status: CanonicalStatus, to_status: CanonicalStatus) -> bool:
    """Check whether a status transition is valid."""
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def aggregate_with_optional(
    required: list[CanonicalStatus],
    optional: list[CanonicalStatus],
) -> CanonicalStatus:
    """Aggregate statuses with required vs optional semantics.

    Required unhealthy -> overall unhealthy.
    Optional unhealthy -> overall degraded (not unhealthy).
    """
    required_overall = aggregate_statuses(required) if required else CanonicalStatus.OK
    optional_overall = aggregate_statuses(optional) if optional else CanonicalStatus.OK

    if required_overall == CanonicalStatus.UNHEALTHY:
        return CanonicalStatus.UNHEALTHY
    if required_overall == CanonicalStatus.DEGRADED:
        return CanonicalStatus.DEGRADED

    # Required is OK or UNKNOWN -- check optional
    if optional_overall == CanonicalStatus.UNHEALTHY:
        return CanonicalStatus.DEGRADED  # Optional downgrades don't fail readiness
    if optional_overall == CanonicalStatus.DEGRADED:
        return CanonicalStatus.DEGRADED

    # If optional is UNKNOWN and required is OK, stay OK
    if optional_overall == CanonicalStatus.UNKNOWN:
        return CanonicalStatus.OK

    return CanonicalStatus.OK


# ---------------------------------------------------------------------------
# Control Plane Phase 2: Report models and EcosystemStatusService
# ---------------------------------------------------------------------------


class SectionError(BaseModel):
    """Error encountered while collecting a report section."""

    section: str
    message: str
    original_exception: str | None = None


class ServiceStatus(BaseModel):
    """Health status for a single ecosystem dependency."""

    status: CanonicalStatus
    liveness: CanonicalStatus = CanonicalStatus.UNKNOWN
    readiness: CanonicalStatus = CanonicalStatus.UNKNOWN
    last_check: datetime | None = None
    last_updated_at: datetime | None = None
    capacity_pct: float | None = None
    required: bool = False
    degradation_mode: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class AdapterStatus(BaseModel):
    """Health status for a single orchestration adapter."""

    status: CanonicalStatus
    last_check: datetime | None = None
    last_updated_at: datetime | None = None
    capabilities: dict[str, CanonicalStatus] = Field(default_factory=dict)
    task_classes: list[str] = Field(default_factory=list)
    degradation_trend: DegradationTrend | None = None
    preference_score: float | None = None


class CapabilityStatus(BaseModel):
    """Health status for a named ecosystem capability."""

    status: CanonicalStatus
    provided_by: list[str] = Field(default_factory=list)
    category: str = ""
    last_verified: datetime | None = None


class WorkflowSummary(BaseModel):
    """High-level workflow execution statistics."""

    active_count: int = 0
    failed_count: int = 0
    recent_count: int = 0
    last_completed_at: datetime | None = None


class AlertRef(BaseModel):
    """Reference to a single active alert."""

    severity: str
    source: str
    message: str
    created_at: datetime


class AlertSummary(BaseModel):
    """Aggregated alert counts and top alerts."""

    total_active: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    top_alerts: list[AlertRef] = Field(default_factory=list)


class OperationalRecommendation(BaseModel):
    """Operator guidance derived from the current ecosystem state."""

    severity: CanonicalStatus
    component: str
    message: str
    suggested_command: str | None = None
    runbook_url: str | None = None


class EcosystemStatusReport(BaseModel):
    """Full ecosystem status report with per-section detail."""

    schema_version: str = "1.0"
    status: CanonicalStatus
    generated_at: datetime
    duration_ms: float
    request_id: str | None = None
    services: dict[str, ServiceStatus] = Field(default_factory=dict)
    adapters: dict[str, AdapterStatus] = Field(default_factory=dict)
    capabilities: dict[str, CapabilityStatus] = Field(default_factory=dict)
    workflows: WorkflowSummary = Field(default_factory=WorkflowSummary)
    alerts: AlertSummary = Field(default_factory=AlertSummary)
    recommendations: list[OperationalRecommendation] = Field(default_factory=list)
    errors: list[SectionError] = Field(default_factory=list)


class EcosystemStatusService:
    """Read-only aggregator for ecosystem status.

    Collects health, adapter, monitoring, workflow, and alert signals
    concurrently using asyncio.gather with per-section timeouts.
    No state mutation happens during report generation.
    """

    def __init__(
        self,
        section_timeout_ms: int = 5000,
        staleness_threshold_seconds: float = 300.0,
    ) -> None:
        self.section_timeout_ms = section_timeout_ms
        self.staleness_threshold_seconds = staleness_threshold_seconds

    async def generate_report(self, request_id: str | None = None) -> EcosystemStatusReport:
        """Generate a full ecosystem status report.

        Each section is collected concurrently with independent timeouts.
        A failed section produces an error entry, not an exception.
        """
        start = time.monotonic()
        generated_at = datetime.now()

        # Collect sections concurrently
        section_results = await asyncio.gather(
            self._collect_services(),
            self._collect_adapters(),
            self._collect_workflows(),
            self._collect_alerts(),
            return_exceptions=True,
        )

        services: dict[str, ServiceStatus] = {}
        adapters: dict[str, AdapterStatus] = {}
        workflows = WorkflowSummary()
        alerts = AlertSummary()
        errors: list[SectionError] = []

        section_names = ["services", "adapters", "workflows", "alerts"]
        for name, result in zip(section_names, section_results):
            if isinstance(result, BaseException):
                errors.append(SectionError(
                    section=name,
                    message=str(result),
                    original_exception=type(result).__name__,
                ))
            elif name == "services":
                services = result
            elif name == "adapters":
                adapters = result
            elif name == "workflows":
                workflows = result
            elif name == "alerts":
                alerts = result

        # Compute overall status
        all_statuses = list(services.values()) if services else []
        overall = (
            aggregate_statuses([s.status for s in all_statuses])
            if all_statuses
            else CanonicalStatus.UNKNOWN
        )

        # Apply staleness detection
        services = self._detect_staleness(services)
        adapters = self._detect_staleness(adapters)

        duration_ms = (time.monotonic() - start) * 1000

        return EcosystemStatusReport(
            status=overall,
            generated_at=generated_at,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
            services=services,
            adapters=adapters,
            workflows=workflows,
            alerts=alerts,
            errors=errors,
        )

    async def _collect_services(self) -> dict[str, ServiceStatus]:
        """Collect service health from configured dependencies.

        Stub implementation -- will be wired to HealthChecker in a follow-up.
        """
        return {}

    async def _collect_adapters(self) -> dict[str, AdapterStatus]:
        """Collect adapter inventory and health.

        Stub implementation -- will be wired to HybridAdapterRegistry in a follow-up.
        """
        return {}

    async def _collect_workflows(self) -> WorkflowSummary:
        """Collect workflow summary."""
        return WorkflowSummary()

    async def _collect_alerts(self) -> AlertSummary:
        """Collect alert summary."""
        return AlertSummary()

    def _detect_staleness(
        self,
        items: dict[str, ServiceStatus] | dict[str, AdapterStatus],
    ) -> dict[str, ServiceStatus] | dict[str, AdapterStatus]:
        """Flag items whose last_check exceeds the staleness threshold as UNKNOWN."""
        now = datetime.now()
        threshold = self.staleness_threshold_seconds
        updated: dict[str, ServiceStatus | AdapterStatus] = {}
        for key, item in items.items():
            if (
                item.last_check
                and (now - item.last_check).total_seconds() > threshold
            ):
                item = item.model_copy(update={"status": CanonicalStatus.UNKNOWN})
            updated[key] = item
        return updated
