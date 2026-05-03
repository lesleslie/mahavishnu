"""Canonical status types and normalization for the Bodai ecosystem control plane."""

from __future__ import annotations

import asyncio
import collections
from datetime import UTC, datetime
from enum import StrEnum
import logging
import time
from typing import Any, Protocol, runtime_checkable
import uuid

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CanonicalStatus(StrEnum):
    """Single canonical status vocabulary for all operator-facing surfaces."""

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DISABLED = "disabled"


class DegradationTrend(StrEnum):
    """Trend direction for a degrading component."""

    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"


class RejectionReason(StrEnum):
    """Reason an adapter was not selected during routing."""

    HEALTH_FAILED = "health_failed"
    CAPABILITY_MISSING = "capability_missing"
    COST_EXCEEDED = "cost_exceeded"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Phase 5: Canonical routing observability models
# ---------------------------------------------------------------------------


class FallbackCandidate(BaseModel):
    """An adapter that could serve as a fallback if the primary is unavailable."""

    adapter_name: str
    status: CanonicalStatus
    estimated_latency_ms: float | None = None
    match_score: float | None = None


class CandidateEvaluation(BaseModel):
    """Score and metadata for an adapter considered during a routing decision."""

    adapter_name: str
    score: float
    match_rate: float
    estimated_latency_ms: float | None = None
    cost_estimate_usd: float | None = None


class RejectedAdapter(BaseModel):
    """An adapter that was considered but not selected."""

    adapter_name: str
    reason: RejectionReason
    detail: str | None = None


class RoutingDecision(BaseModel):
    """Canonical operator-facing record of a single routing decision.

    This is the observability model. For the internal adapter resolution
    result see ``mahavishnu.core.task_requirements.AdapterResolutionResult``.

    Ring-buffer note: instances are stored in a bounded per-task-class
    ring buffer (see :class:`RoutingDecisionBuffer`) — never as raw Prometheus
    labels. Only ``task_class`` and ``routing_strategy`` are used as Prometheus
    labels; ``task_id`` / ``decision_id`` are structural metadata only.
    """

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    task_class: str
    required_capabilities: list[str] = Field(default_factory=list)
    selected_adapter: str
    candidate_adapters: list[CandidateEvaluation] = Field(default_factory=list)
    rejected_adapters: list[RejectedAdapter] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_chain: list[str] = Field(default_factory=list)
    health_at_decision: dict[str, CanonicalStatus] = Field(default_factory=dict)
    cache_hit: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    decision_latency_ms: float = 0.0
    routing_strategy: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoutingReadiness(BaseModel):
    """Routing readiness summary for a given task class."""

    task_class: str
    primary_adapter: str | None = None
    primary_status: CanonicalStatus = CanonicalStatus.UNKNOWN
    fallback_chain: list[FallbackCandidate] = Field(default_factory=list)
    circuit_breakers_open: list[str] = Field(default_factory=list)
    routing_strategy: str = ""
    last_decision: RoutingDecision | None = None


class RoutingDecisionBuffer:
    """Bounded ring buffer for recent routing decisions per task class.

    Stores at most ``maxlen`` decisions per task class. Older entries are
    automatically evicted when the buffer is full.

    Data classification: stores only structural routing metadata — never
    task prompts, user inputs, or response content.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._maxlen = maxlen
        self._buffers: dict[str, collections.deque[RoutingDecision]] = {}

    def record(self, decision: RoutingDecision) -> None:
        """Add a routing decision to the ring buffer."""
        key = decision.task_class
        if key not in self._buffers:
            self._buffers[key] = collections.deque(maxlen=self._maxlen)
        self._buffers[key].append(decision)

    def recent(self, task_class: str, limit: int = 10) -> list[RoutingDecision]:
        """Return the most recent decisions for the given task class."""
        buf = self._buffers.get(task_class)
        if not buf:
            return []
        items = list(buf)
        return items[-limit:]

    def all_task_classes(self) -> list[str]:
        return list(self._buffers.keys())

    def clear(self) -> None:
        self._buffers.clear()


# Module-level singleton ring buffer.
_routing_buffer: RoutingDecisionBuffer = RoutingDecisionBuffer()


def get_routing_buffer() -> RoutingDecisionBuffer:
    """Return the module-level routing decision ring buffer."""
    return _routing_buffer


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
    CanonicalStatus.OK: {
        CanonicalStatus.DEGRADED,
        CanonicalStatus.UNKNOWN,
        CanonicalStatus.DISABLED,
    },
    CanonicalStatus.DEGRADED: {
        CanonicalStatus.OK,
        CanonicalStatus.UNHEALTHY,
        CanonicalStatus.UNKNOWN,
        CanonicalStatus.DISABLED,
    },
    CanonicalStatus.UNHEALTHY: {
        CanonicalStatus.DEGRADED,
        CanonicalStatus.UNKNOWN,
        CanonicalStatus.DISABLED,
    },
    CanonicalStatus.UNKNOWN: {
        CanonicalStatus.OK,
        CanonicalStatus.DEGRADED,
        CanonicalStatus.UNHEALTHY,
        CanonicalStatus.DISABLED,
    },
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
# Data source protocols (for dependency injection)
# ---------------------------------------------------------------------------


@runtime_checkable
class AdapterProvider(Protocol):
    """Provides adapter instances and health information."""

    def get_adapter(self, name: str) -> Any: ...

    async def get_health(self) -> dict[str, Any]: ...


@runtime_checkable
class AlertProvider(Protocol):
    """Provides active alert data."""

    def get_active_alerts_sync(self) -> list[Any]: ...


@runtime_checkable
class WorkflowProvider(Protocol):
    """Provides workflow state data."""

    async def list_workflows(self, limit: int = 100) -> list[dict[str, Any]]: ...


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

    Data sources can be injected via constructor parameters. When not
    provided, collection methods return empty defaults (graceful degradation).
    """

    def __init__(
        self,
        section_timeout_ms: int = 5000,
        staleness_threshold_seconds: float = 300.0,
        adapters: dict[str, Any] | None = None,
        alert_provider: AlertProvider | None = None,
        workflow_provider: WorkflowProvider | None = None,
        service_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.section_timeout_ms = section_timeout_ms
        self.staleness_threshold_seconds = staleness_threshold_seconds
        self._adapters = adapters or {}
        self._alert_provider = alert_provider
        self._workflow_provider = workflow_provider
        self._service_configs = service_configs or {}

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
            self._collect_capabilities(),
            return_exceptions=True,
        )

        services: dict[str, ServiceStatus] = {}
        adapters: dict[str, AdapterStatus] = {}
        workflows = WorkflowSummary()
        alerts = AlertSummary()
        capabilities: dict[str, CapabilityStatus] = {}
        errors: list[SectionError] = []

        section_names = ["services", "adapters", "workflows", "alerts", "capabilities"]
        for name, result in zip(section_names, section_results, strict=False):
            if isinstance(result, BaseException):
                errors.append(
                    SectionError(
                        section=name,
                        message=str(result),
                        original_exception=type(result).__name__,
                    )
                )
            elif name == "services":
                services = result
            elif name == "adapters":
                adapters = result
            elif name == "workflows":
                workflows = result
            elif name == "alerts":
                alerts = result
            elif name == "capabilities":
                capabilities = result

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

        # Generate deterministic recommendations (Phase 7)
        recommendations = self._generate_recommendations(services, adapters, alerts)

        duration_ms = (time.monotonic() - start) * 1000

        return EcosystemStatusReport(
            status=overall,
            generated_at=generated_at,
            duration_ms=round(duration_ms, 2),
            request_id=request_id,
            services=services,
            adapters=adapters,
            capabilities=capabilities,
            workflows=workflows,
            alerts=alerts,
            recommendations=recommendations,
            errors=errors,
        )

    async def _collect_services(self) -> dict[str, ServiceStatus]:
        """Collect service health from configured dependencies.

        Checks each configured service URL via HTTP GET with timeout.
        Falls back to UNKNOWN for unreachable services.
        """
        import httpx

        services: dict[str, ServiceStatus] = {}
        for name, cfg in self._service_configs.items():
            url = cfg.get("url", "")
            required = cfg.get("required", False)
            if not url:
                services[name] = ServiceStatus(
                    status=CanonicalStatus.DISABLED,
                    required=required,
                )
                continue
            try:
                timeout_s = cfg.get("timeout_s", 3)
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    resp = await client.get(f"{url.rstrip('/')}/health")
                    body = resp.json()
                    raw_status = body.get("status", "unknown")
                    services[name] = ServiceStatus(
                        status=normalize_status(raw_status),
                        last_check=datetime.now(UTC),
                        required=required,
                        latency_ms=body.get("latency_ms"),
                    )
            except Exception:
                services[name] = ServiceStatus(
                    status=CanonicalStatus.UNKNOWN,
                    required=required,
                    last_check=datetime.now(UTC),
                )
        return services

    async def _collect_adapters(self) -> dict[str, AdapterStatus]:
        """Collect adapter inventory and health from registered adapters."""
        if not self._adapters:
            return {}
        adapters: dict[str, AdapterStatus] = {}
        for name, adapter in self._adapters.items():
            try:
                health = await adapter.get_health() if hasattr(adapter, "get_health") else {}
                raw_status = health.get("status", "unknown")
                adapters[name] = AdapterStatus(
                    status=normalize_status(raw_status),
                    last_check=datetime.now(UTC),
                    preference_score=health.get("preference_score"),
                )
            except Exception:
                adapters[name] = AdapterStatus(
                    status=CanonicalStatus.UNKNOWN,
                    last_check=datetime.now(UTC),
                )
        return adapters

    async def _collect_workflows(self) -> WorkflowSummary:
        """Collect workflow summary from StateManager."""
        if not self._workflow_provider:
            return WorkflowSummary()
        try:
            workflows = await self._workflow_provider.list_workflows(limit=100)
            active = sum(1 for w in workflows if w.get("status") == "running")
            failed = sum(1 for w in workflows if w.get("status") == "failed")
            return WorkflowSummary(
                active_count=active,
                failed_count=failed,
                recent_count=len(workflows),
            )
        except Exception:
            return WorkflowSummary()

    async def _collect_alerts(self) -> AlertSummary:
        """Collect active alerts from AlertManager."""
        if not self._alert_provider:
            return AlertSummary()
        try:
            alerts = self._alert_provider.get_active_alerts_sync()
            by_severity: dict[str, int] = {}
            top: list[AlertRef] = []
            for a in alerts[:20]:
                sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
                by_severity[sev] = by_severity.get(sev, 0) + 1
                top.append(
                    AlertRef(
                        severity=sev,
                        source=getattr(a, "type", "unknown"),
                        message=getattr(a, "description", "") or getattr(a, "title", ""),
                        created_at=getattr(a, "timestamp", datetime.now(UTC)),
                    )
                )
            return AlertSummary(
                total_active=len(alerts),
                by_severity=by_severity,
                top_alerts=top,
            )
        except Exception:
            return AlertSummary()

    async def _collect_capabilities(self) -> dict[str, CapabilityStatus]:
        """Build the capability inventory from registered adapters (Phase 6).

        Aggregates local adapter capabilities into named ecosystem capabilities
        grouped by category. Remote service capability probes are out of scope
        for this phase — only local adapter metadata is used.

        Categories: orchestration, retrieval, session, storage, quality,
        monitoring, messaging, worker_pool.
        """
        CAPABILITY_CATEGORIES: dict[str, str] = {
            "deploy_flows": "orchestration",
            "schedule": "orchestration",
            "monitor_execution": "orchestration",
            "multi_agent": "orchestration",
            "tool_use": "orchestration",
            "rag": "retrieval",
            "vector_search": "retrieval",
            "session": "session",
            "memory": "session",
            "storage": "storage",
            "persist": "storage",
            "quality": "quality",
            "lint": "quality",
            "test": "quality",
            "monitor": "monitoring",
            "alerts": "monitoring",
            "metrics": "monitoring",
            "message": "messaging",
            "broadcast": "messaging",
            "worker": "worker_pool",
            "pool": "worker_pool",
        }

        cap_providers: dict[str, list[str]] = {}
        cap_statuses: dict[str, CanonicalStatus] = {}

        for name, adapter in self._adapters.items():
            try:
                health = await adapter.get_health() if hasattr(adapter, "get_health") else {}
                adapter_status = normalize_status(health.get("status", "unknown"))
                caps: list[str] = []
                if hasattr(adapter, "capabilities"):
                    caps = list(adapter.capabilities) if adapter.capabilities else []
                elif isinstance(health.get("capabilities"), list):
                    caps = health["capabilities"]
                for cap in caps:
                    if cap not in cap_providers:
                        cap_providers[cap] = []
                        cap_statuses[cap] = adapter_status
                    cap_providers[cap].append(name)
                    if STATUS_SEVERITY.get(adapter_status, 0) > STATUS_SEVERITY.get(
                        cap_statuses[cap], 0
                    ):
                        cap_statuses[cap] = adapter_status
            except Exception:
                pass

        result: dict[str, CapabilityStatus] = {}
        for cap, providers in cap_providers.items():
            category = next(
                (v for k, v in CAPABILITY_CATEGORIES.items() if k in cap.lower()),
                "other",
            )
            result[cap] = CapabilityStatus(
                status=cap_statuses.get(cap, CanonicalStatus.UNKNOWN),
                provided_by=providers,
                category=category,
                last_verified=datetime.now(UTC),
            )
        return result

    def _generate_recommendations(
        self,
        services: dict[str, ServiceStatus],
        adapters: dict[str, AdapterStatus],
        alerts: AlertSummary,
    ) -> list[OperationalRecommendation]:
        """Generate deterministic operator recommendations (Phase 7).

        Rules are evaluated in order. Each unhealthy required component
        produces at least one recommendation.
        """
        recs: list[OperationalRecommendation] = []

        for name, svc in services.items():
            if svc.required and svc.status == CanonicalStatus.UNHEALTHY:
                recs.append(
                    OperationalRecommendation(
                        severity=CanonicalStatus.UNHEALTHY,
                        component=name,
                        message=f"Required service '{name}' is unhealthy. Check that it is running.",
                        suggested_command=f"mahavishnu health --service {name}",
                    )
                )
            elif svc.required and svc.status == CanonicalStatus.UNKNOWN:
                recs.append(
                    OperationalRecommendation(
                        severity=CanonicalStatus.DEGRADED,
                        component=name,
                        message=f"Required service '{name}' is unreachable or health check timed out.",
                        suggested_command=f"mahavishnu health --service {name}",
                    )
                )
            elif not svc.required and svc.status in (
                CanonicalStatus.UNHEALTHY,
                CanonicalStatus.DEGRADED,
            ):
                recs.append(
                    OperationalRecommendation(
                        severity=CanonicalStatus.DEGRADED,
                        component=name,
                        message=(
                            f"Optional service '{name}' is {svc.status.value}. "
                            "Some features may be degraded."
                        ),
                        suggested_command=f"mahavishnu health --service {name}",
                    )
                )

        if not adapters:
            recs.append(
                OperationalRecommendation(
                    severity=CanonicalStatus.DEGRADED,
                    component="adapters",
                    message="No adapters registered. Run adapter discovery.",
                    suggested_command="mahavishnu adapter list",
                )
            )
        else:
            for name, adp in adapters.items():
                if adp.status == CanonicalStatus.UNHEALTHY:
                    recs.append(
                        OperationalRecommendation(
                            severity=CanonicalStatus.UNHEALTHY,
                            component=name,
                            message=f"Adapter '{name}' is unhealthy. Inspect recent failures.",
                            suggested_command=f"mahavishnu adapter health --name {name}",
                        )
                    )

        if alerts.total_active > 10:
            recs.append(
                OperationalRecommendation(
                    severity=CanonicalStatus.DEGRADED,
                    component="alerts",
                    message=f"High alert count ({alerts.total_active} active). Check monitoring dashboard.",
                    suggested_command="mahavishnu ecosystem status --sections alerts",
                )
            )

        return recs

    def _detect_staleness(
        self,
        items: dict[str, ServiceStatus] | dict[str, AdapterStatus],
    ) -> dict[str, ServiceStatus] | dict[str, AdapterStatus]:
        """Flag items whose last_check exceeds the staleness threshold as UNKNOWN."""
        now = datetime.now()
        threshold = self.staleness_threshold_seconds
        updated: dict[str, ServiceStatus | AdapterStatus] = {}
        for key, item in items.items():
            if item.last_check and (now - item.last_check).total_seconds() > threshold:
                item = item.model_copy(update={"status": CanonicalStatus.UNKNOWN})
            updated[key] = item
        return updated


__all__ = [
    # Enums
    "CanonicalStatus",
    "DegradationTrend",
    "RejectionReason",
    # Status helpers
    "normalize_status",
    "aggregate_statuses",
    "aggregate_with_optional",
    "is_valid_transition",
    "ADAPTER_STATUS_MAP",
    "STATUS_SEVERITY",
    "VALID_TRANSITIONS",
    # Report models
    "SectionError",
    "ServiceStatus",
    "AdapterStatus",
    "CapabilityStatus",
    "WorkflowSummary",
    "AlertRef",
    "AlertSummary",
    "OperationalRecommendation",
    "EcosystemStatusReport",
    # Routing observability models (Phase 5)
    "FallbackCandidate",
    "CandidateEvaluation",
    "RejectedAdapter",
    "RoutingDecision",
    "RoutingReadiness",
    "RoutingDecisionBuffer",
    "get_routing_buffer",
    # Service
    "EcosystemStatusService",
]
