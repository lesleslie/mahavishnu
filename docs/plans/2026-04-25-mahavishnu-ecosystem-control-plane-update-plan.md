# Mahavishnu Ecosystem Control Plane Update Plan

**Date:** 2026-04-25
**Last reviewed:** 2026-04-24
**Status:** Proposed (reviewed; findings from 6-agent cross-review applied)
**Scope:** Mahavishnu health, readiness, capability discovery, routing observability, and TUI/dashboard integration across the Bodai ecosystem.

**Companion documents:**
- Master spec: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
- Implementation plan: [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)

**Phase registry (cross-plan reference):**

This document uses **CP Phases** (CP0-CP7). See companion docs for their own numbering.

| CP Phase | Focus | Maps to Impl Phase | Maps to Spec Phase |
|---------|-------|-------------------|-------------------|
| CP0 | Plan state reconciliation | I0 | S1 |
| CP1 | Status normalization | I0 | S1 |
| CP2 | Ecosystem status aggregator | I1 | — |
| CP3 | CLI and MCP exposure | I1 | — |
| CP4 | Live TUI wiring | — | S1-S2 |
| CP5 | Routing visibility | I2 | S2 |
| CP6 | Capability inventory | I2 | S2 |
| CP7 | Operator recommendations | I3 | S3 |

## 1. Objective

Turn Mahavishnu into the reliable operational control plane for the Bodai ecosystem without duplicating responsibilities already owned by Session-Buddy, Akosha, Dhara, Crackerjack, Prefect, Agno, LlamaIndex, or the TUI.

This plan builds on existing implementation rather than replacing it. Mahavishnu already has health checks, adapter health, MCP utility tools, monitoring dashboard data, contract tests, and a read-only Textual dashboard shell. The main work is to normalize contracts, wire the existing pieces together, and expose one canonical operator-facing view.

## 2. Current State Inventory

### 2.1 Existing Health and Readiness Surfaces

Mahavishnu already has a substantial health system:

- `mahavishnu/core/health.py`
  - `HealthStatus`
  - `DependencyStatus`
  - `HealthResponse`
  - `ReadyResponse`
  - `HealthChecker`
  - `DependencyWaiter`
  - `HealthEndpoint`
- `mahavishnu/core/health_schemas.py`
  - compatibility wrapper that re-exports health schemas from `core.health`
- `mahavishnu/_main_cli.py`
  - `mahavishnu health`
  - `mahavishnu health --json`
  - `mahavishnu mcp health`
  - `mahavishnu adapter health`
- `mahavishnu/mcp/tools/health_tools.py`
  - `health_check_service`
  - `health_check_all`
  - `wait_for_dependency`
  - `wait_for_all_dependencies`
  - `get_liveness`
  - `get_readiness`
  - `mcp_list_tools`
  - `mcp_test_connection`
  - `mcp_get_metrics`
- `mahavishnu/mcp/server_core.py`
  - HTTP `/health` and `/healthz` custom routes
  - MCP `get_health`
  - MCP `get_monitoring_dashboard`
  - MCP `get_active_alerts`
- `settings/mahavishnu.yaml`
  - configured dependencies for `session_buddy`, `akosha`, `dhara`, and `crackerjack`
  - `session_buddy` is required
  - `akosha`, `dhara`, and `crackerjack` are optional

Existing plan/docs coverage:

- `docs/plans/2026-02-27-health-check-system-design.md`
- `docs/plans/2026-02-27-health-check-implementation-plan.md`
- `docs/plans/initiatives/01-health-contract-and-command.md`
- `docs/plans/initiatives/04-mcp-utility-tools.md`
- `docs/plans/initiatives/05-ecosystem-contract-tests.md`

### 2.2 Existing Adapter and Capability Surfaces

Mahavishnu already has adapter discovery, adapter health, and capability routing primitives:

- `mahavishnu/core/adapter_registry.py`
  - `HybridAdapterRegistry`
  - entry-point discovery
  - Dhara MCP discovery configuration
  - persistence layer
  - resolution cache
  - `resolve()`
  - `find_by_capabilities()`
  - `list_adapters()`
  - `check_all_health()`
- `mahavishnu/core/health_integration.py`
  - `AdapterHealthMonitor`
  - adapter health state tracking
  - metrics
  - alerts
  - websocket health-change broadcast support
- `mahavishnu/mcp/tools/adapter_registry_tools.py`
  - `adapter_list`
  - `adapter_resolve`
  - `adapter_health`
  - `adapter_enable`
  - `adapter_metadata`
  - `adapter_cache_invalidate`
  - `adapter_discover`
- `mahavishnu/_main_cli.py`
  - `mahavishnu adapter list`
  - `mahavishnu adapter resolve`
  - `mahavishnu adapter health`

### 2.3 Existing Dashboard and TUI Surfaces

The old TUI design file is no longer canonical:

- `docs/superpowers/specs/2026-04-09-tui-design.md`
  - points to `docs/plans/2026-04-16-bodai-agent-platform-master-spec.md`

Current canonical TUI guidance:

- `docs/plans/2026-04-16-bodai-agent-platform-master-spec.md`
  - TUI must talk to Mahavishnu over MCP
  - TUI must not own memory, workflow state, skill persistence, or routing policy
  - TUI is presentation and command forwarding only
- `docs/plans/2026-04-16-bodai-master-implementation-plan.md`
  - keeps TUI read-only around stateful surfaces
  - prevents TUI from becoming a second control plane

Implemented TUI shell:

- `mahavishnu/tui/app.py`
  - `DashboardApp`
  - `OverviewScreen`
  - `SweepScreen`
  - `RoutingScreen`
  - `AlertsScreen`
  - read-only Textual UI
  - current data fetchers are placeholders/stubs
- `mahavishnu/_main_cli.py`
  - `mahavishnu dashboard`
- `tests/unit/test_tui_dashboard.py`
  - verifies app structure, screens, bindings, and placeholder data shapes

Plan status mismatch to resolve:

- `docs/plans/initiatives/13-dashboard-phase2-textual.md` says Textual dashboard phase 2 is complete.
- `docs/plans/2026-04-04-ecosystem-execution-board.md` still has Initiative 13 unchecked.
- `mahavishnu/tui/app.py` is implemented as a shell, but the planned live data requirement is not actually met because fetchers return placeholder data.

### 2.4 Existing Contract and Testing Surfaces

Mahavishnu already has ecosystem contract test coverage:

- `tests/integration/test_ecosystem_contracts.py`
  - MCP core tool inventory
  - health tool registration
  - tool version registry
  - adapter lifecycle contract
  - adapter metadata contract
- `tests/unit/core/test_health.py`
- `tests/unit/core/test_health_schemas.py`
- `tests/unit/test_health_integration.py`
- `tests/unit/test_adapter_registry.py`
- `tests/unit/test_tui_dashboard.py`

## 3. Main Gaps

### 3.1 Health Contract Drift

There are multiple health vocabularies in active use:

- `HealthStatus` uses `ok | degraded | unhealthy`
- adapter health uses values such as `healthy`, `degraded`, `unhealthy`, `error`, and `not_configured`
- MCP `get_health` returns `healthy | degraded | unhealthy`
- CLI `mahavishnu health` computes overall status from dependencies, but currently treats any unhealthy dependency as an overall failure even if the dependency is optional

The result is that different surfaces can disagree about the same underlying state.

### 3.2 Duplicate Operator Entry Points

Operators currently have several ways to ask similar questions:

- `mahavishnu health`
- `mahavishnu mcp health`
- `mahavishnu adapter health`
- MCP `get_health`
- MCP `get_liveness`
- MCP `get_readiness`
- MCP `health_check_all`
- MCP `adapter_health`
- MCP `get_monitoring_dashboard`
- TUI overview screen

These should remain available where useful, but one canonical aggregation model should feed them.

### 3.3 TUI Is Not Yet a Live Ecosystem Dashboard

The Textual app exists and is intentionally read-only, which matches the master spec. However, its fetchers are placeholders:

- overview status is hardcoded
- sweep history is empty
- routing stats are hardcoded
- active alerts are empty

The next TUI work should not add orchestration logic to the TUI. It should wire read-only fetchers to canonical MCP/backend APIs.

### 3.4 Capability Discovery Is Adapter-Centric, Not Ecosystem-Centric

Mahavishnu can discover and resolve adapters. It does not yet expose a single ecosystem capability inventory that answers:

- which services are reachable?
- which tools does each service expose?
- which capabilities are currently degraded?
- which workflow paths are routable right now?
- which dependencies are required vs optional?

### 3.5 Failure-Aware Routing Needs Better Operator Visibility

Routing and adapter health primitives exist, but the operator view should make routing decisions explainable:

- selected adapter
- required capabilities
- matched capabilities
- fallback path
- health status considered during selection
- cache hit/miss
- degraded dependency impact

### 3.6 Existing Plans Need Reconciliation

The repo contains overlapping and partially stale plan state:

- health initiative is marked complete, but contract drift remains
- TUI initiative is marked complete in the initiative file, but the dashboard uses stub data
- the execution board still marks Initiative 13 incomplete
- the master TUI spec says TUI talks over MCP, but current fetchers do not yet use MCP/backend APIs

## 4. Target Architecture

### 4.1 Canonical Data Model

Introduce one canonical ecosystem status model in Mahavishnu core:

- `EcosystemStatusReport`
- `ServiceStatus`
- `AdapterStatus`
- `CapabilityStatus`
- `RoutingReadiness`
- `OperationalRecommendation`

This model should normalize all subsystem-specific statuses into a common vocabulary:

- `ok`
- `degraded`
- `unhealthy`
- `unknown`
- `disabled`

**Severity ordering for aggregation:** `disabled < unknown < degraded < unhealthy` (where `ok` is baseline). See Decision 3 in Section 8 for full aggregation rules.

**Status transition rules:** Components follow valid transitions only. Invalid transitions (e.g., `unhealthy -> ok` without passing through `degraded`) are logged as suspicious. See Decision 7 in Section 8.

Subsystem-native values can remain internally, but every external operator surface should emit the canonical vocabulary.

**Canonical model definitions** (this is the single authoritative shape — Phase 2's candidate model is removed; reference this section):

```python
class CanonicalStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DISABLED = "disabled"

class DegradationTrend(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"

class RejectionReason(str, Enum):
    HEALTH_FAILED = "health_failed"
    CAPABILITY_MISSING = "capability_missing"
    COST_EXCEEDED = "cost_exceeded"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"

class SectionError(BaseModel):
    section: str
    message: str  # human-readable summary
    original_exception: str | None = None  # raw exception for debugging

class FallbackCandidate(BaseModel):
    adapter_name: str
    status: CanonicalStatus
    estimated_latency_ms: float | None = None
    match_score: float | None = None

class CandidateEvaluation(BaseModel):
    adapter_name: str
    score: float
    match_rate: float
    estimated_latency_ms: float | None = None
    cost_estimate_usd: float | None = None

class RejectedAdapter(BaseModel):
    adapter_name: str
    reason: RejectionReason
    detail: str | None = None

class RoutingDecision(BaseModel):
    decision_id: str
    task_id: str
    task_class: str
    required_capabilities: list[str]
    selected_adapter: str
    candidate_adapters: list[CandidateEvaluation]
    rejected_adapters: list[RejectedAdapter]
    fallback_used: bool
    fallback_chain: list[str]
    health_at_decision: dict[str, CanonicalStatus]
    cache_hit: bool
    confidence: float = Field(ge=0.0, le=1.0)
    decision_latency_ms: float
    routing_strategy: str
    timestamp: datetime

class CapabilityStatus(BaseModel):
    status: CanonicalStatus
    provided_by: list[str]
    category: str  # orchestration, retrieval, session, storage, quality, monitoring, messaging, worker/pool
    last_verified: datetime | None = None

class WorkflowSummary(BaseModel):
    active_count: int
    failed_count: int
    recent_count: int
    last_completed_at: datetime | None = None

class AlertRef(BaseModel):
    severity: str
    source: str
    message: str
    created_at: datetime

class AlertSummary(BaseModel):
    total_active: int
    by_severity: dict[str, int]
    top_alerts: list[AlertRef]

class OperationalRecommendation(BaseModel):
    severity: CanonicalStatus
    component: str
    message: str
    suggested_command: str | None = None
    runbook_url: str | None = None

class ServiceStatus(BaseModel):
    status: CanonicalStatus
    liveness: CanonicalStatus
    readiness: CanonicalStatus
    last_check: datetime | None = None
    last_updated_at: datetime | None = None  # None = never updated
    capacity_pct: float | None = None
    required: bool
    degradation_mode: str | None = None
    latency_ms: float | None = None  # parity with existing DependencyStatus
    error: str | None = None

class AdapterStatus(BaseModel):
    status: CanonicalStatus
    last_check: datetime | None = None
    last_updated_at: datetime | None = None
    capabilities: dict[str, CanonicalStatus]
    task_classes: list[str]  # validated against TaskType enum
    degradation_trend: DegradationTrend | None = None
    preference_score: float | None = None  # from existing AdapterState

class EcosystemStatusReport(BaseModel):
    schema_version: str = "1.0"
    status: CanonicalStatus
    generated_at: datetime
    duration_ms: float
    request_id: str | None = None
    services: dict[str, ServiceStatus]
    adapters: dict[str, AdapterStatus]
    capabilities: dict[str, CapabilityStatus]
    workflows: WorkflowSummary
    alerts: AlertSummary
    recommendations: list[OperationalRecommendation]
    errors: list[SectionError]

class RoutingReadiness(BaseModel):
    task_class: str
    primary_adapter: str | None
    primary_status: CanonicalStatus
    fallback_chain: list[FallbackCandidate]
    circuit_breakers_open: list[str]
    routing_strategy: str
    last_decision: RoutingDecision | None  # summary only, not full object
```

**Status normalization mapping** (adapter-native -> canonical):

| Adapter-native | Canonical | Notes |
|---------------|----------|-------|
| `healthy` | `ok` | Most common positive state |
| `degraded` | `degraded` | Direct mapping |
| `unhealthy` | `unhealthy` | Direct mapping |
| `error` | `unhealthy` | Error is a form of unhealthy |
| `not_configured` | `disabled` | Not configured means intentionally off |

**`HealthStatus` enum expansion:** Add `UNKNOWN` and `DISABLED` to the existing `HealthStatus` in `mahavishnu/core/health.py`. Update `HealthChecker._record_metrics()`: UNKNOWN maps to 0.25, DISABLED skips metric recording. This prevents conflating "we don't know" with "definitely broken" in Prometheus.

**`CanonicalStatus` vs `HealthStatus` relationship:** `HealthStatus` is the existing internal enum in `core/health.py` used by `HealthChecker`, dependency probes, and adapter health. `CanonicalStatus` is the new external-facing enum used in `EcosystemStatusReport` and all operator surfaces. The relationship: `HealthStatus` values are mapped to `CanonicalStatus` via the normalization table above. Internally, subsystems may continue using `HealthStatus`; externally, all public APIs emit `CanonicalStatus`. The mapping is one-to-many (e.g., both `healthy` and `ok` map to `CanonicalStatus.OK`). `CanonicalStatus` is the authority for cross-system communication; `HealthStatus` is a legacy internal detail.

**`RoutingDecision` naming:** The existing `task_requirements.py` has a `RoutingDecision` dataclass. Rename it to `AdapterResolutionResult` to avoid collision with the new canonical observability model.

**Timestamp glossary:** `last_check` = time of last health probe. `last_updated_at` = time of last status mutation (None = never updated). `generated_at` = time of report generation. `timestamp` = time of a specific event.

**`MahavishnuError.to_dict()` alignment:** Create a `McpErrorEnvelope(BaseModel)` that wraps `MahavishnuError` and adds MCP-specific fields (`error: bool`, `retryable: bool`, `retry_after_seconds: int | None`). This separates transport-layer envelope from domain error. Extend `ErrorCode` enum with MHV-500 range for ecosystem proxy errors (MHV-500 through MHV-503). Verify no conflicts with existing error codes in `mahavishnu/core/errors.py` before assigning.

**`capacity_pct` information note:** The `ServiceStatus.capacity_pct` field exposes resource utilization data. In multi-tenant or exposed API scenarios, this could leak infrastructure sizing information. The `ecosystem_status` MCP tool must respect tool-profile scoping: the `standard` profile includes `capacity_pct` for operator use only; the `minimal` profile omits it. Document this in the tool profile configuration.

**Ring buffer privacy note:** The routing decision ring buffer (Phase 5) stores task-level metadata (`task_class`, `task_id`, `selected_adapter`). In environments where task content may contain sensitive information, the ring buffer must not store task prompts, user inputs, or response content — only structural routing metadata. Add a data classification comment to the ring buffer implementation.

### 4.2 Canonical Aggregator

Add a read-only aggregation service:

- proposed module: `mahavishnu/core/ecosystem_status.py`
- purpose: collect health, readiness, adapter, routing, monitoring, workflow, and dependency signals
- no persistence authority
- no orchestration side effects
- safe timeout behavior (configurable per-section)
- deterministic JSON output
- **concurrent collection** using `asyncio.gather` with per-section timeouts (not sequential — sequential collection against N services with a 5s timeout means worst-case N*5s latency)
- staleness detection: flag sections whose `last_check` exceeds a configurable threshold as `unknown`

The aggregator should call existing components:

- `HealthEndpoint`
- `HealthChecker`
- `HybridAdapterRegistry`
- `AdapterHealthMonitor` where available
- `MonitoringService`
- workflow state manager
- MCP tool inventory helpers

### 4.3 Canonical Operator Surfaces

Expose the same report through:

- CLI: `mahavishnu ecosystem status`
- CLI: `mahavishnu ecosystem status --json`
- CLI: `mahavishnu ecosystem capabilities`
- CLI: `mahavishnu ecosystem capabilities --json`
- MCP: `ecosystem_status` (with optional `sections`, `include_details`, `timeout_per_section_ms` params)
- MCP: `ecosystem_capabilities` (with optional `capability` filter param for querying)
- MCP: `ecosystem_routing_readiness` (answers "given a task class, which adapters are healthy enough right now?")
- TUI: overview/routing/alerts screens

Keep existing commands for compatibility, but have them delegate to or embed the canonical report where practical.

**`ecosystem_routing_readiness` schema:**
```python
class RoutingReadiness(BaseModel):
    task_class: str
    primary_adapter: str | None
    primary_status: CanonicalStatus
    fallback_chain: list[FallbackCandidate]
    circuit_breakers_open: list[str]
    routing_strategy: str
    last_decision: RoutingDecision | None
```

### 4.4 TUI Boundary

The TUI remains read-only:

- displays canonical status data
- displays routing/capability state
- displays alerts and recent workflow summaries
- may forward commands later, but does not mutate state directly
- does not own health, workflow, session, memory, skill, or routing state

## 5. Implementation Phases

### Phase 0: Reconcile Plan State

Goal: make existing docs reflect actual implementation state and reduce tool surface redundancy.

Tasks:

- Update `docs/plans/initiatives/13-dashboard-phase2-textual.md` to distinguish "TUI shell complete" from "live data dashboard complete".
- Update `docs/plans/2026-04-04-ecosystem-execution-board.md` Initiative 13 status or add a note explaining the mismatch.
- Add this plan to `docs/plans/PLAN_INDEX.md` if that index is still maintained.
- **Tool consolidation audit (new):** Audit the MCP tool surface for redundancy. Specific targets:
  - Health tools: `health_check`, `health_check_service`, `health_check_all`, `get_health`, `get_liveness`, `get_readiness` — 6 tools for health queries. The canonical `ecosystem_status` tool should subsume most of these. Deprecate redundant tools with a `deprecated_replaced_by` field and a 90-day removal timeline.
  - Coordination tools: `list_issues`/`coord_list_issues`, `create_todo`/`coord_create_todo` — duplicate naming. Consolidate to single canonical names.
  - Document the default tool profile as `standard` (not `full`) for production deployments. `full` profile requires explicit opt-in.

Acceptance criteria:

- Plan status no longer claims live TUI data is complete when fetchers are placeholders.
- Future TUI work is explicitly scoped as read-only backend/MCP wiring.
- Redundant health tools are marked deprecated with replacement references.
- No more than one tool per conceptual operation in the `standard` profile.

Validation:

```bash
uv run pytest tests/unit/test_tui_dashboard.py
```

### Phase 1: Canonical Status Normalization

Goal: eliminate contract drift without removing compatibility entry points.

Tasks:

- Add status normalization helpers in `mahavishnu/core/ecosystem_status.py` or `mahavishnu/core/status.py`.
- Map adapter-native statuses into canonical status values.
- Map MCP `get_health` style statuses into canonical status values.
- Fix `mahavishnu health` overall status calculation so optional unhealthy dependencies do not make Mahavishnu globally unhealthy unless readiness says they should.
- Implement status severity ordering and aggregation rules (Decision 3 in Section 8).
- Implement status transition validation (Decision 7 in Section 8).
- Add per-capability health to `AdapterStatus` (pulled forward from Phase 6 per Decision 9).
- Add staleness detection: flag services whose `last_check` exceeds a configurable threshold as `unknown`.
- Add `liveness` vs `readiness` separation to `ServiceStatus`.
- Add optional `capacity_pct` to `ServiceStatus` for saturation awareness.
- Add unit tests for required vs optional dependency aggregation.
- Add unit tests for status transition validation.
- Add unit tests for staleness detection.

Candidate files:

- `mahavishnu/core/ecosystem_status.py`
- `mahavishnu/core/health.py`
- `mahavishnu/_main_cli.py`
- `tests/unit/test_ecosystem_status.py` (new — must be created as part of this phase)
- `tests/unit/test_main_cli.py`
- `tests/unit/core/test_health.py`

Note: `tests/unit/test_ecosystem_status.py` does not exist yet. It must be created during Phase 1 alongside `ecosystem_status.py` itself. The validation commands below reference it as a target, not a prerequisite.

Acceptance criteria:

- every public report uses `ok | degraded | unhealthy | unknown | disabled`
- optional unhealthy dependencies degrade or annotate the report but do not automatically fail readiness
- existing health schema tests still pass
- `AdapterStatus` includes per-capability health
- staleness detection flags stale service checks as `unknown`
- invalid status transitions are logged

Validation:

```bash
uv run pytest tests/unit/core/test_health.py tests/unit/core/test_health_schemas.py tests/unit/test_main_cli.py tests/unit/test_ecosystem_status.py
```

### Phase 2: Ecosystem Status Aggregator

Goal: create a single source for read-only ecosystem diagnostics.

Tasks:

- Implement `EcosystemStatusService` in `mahavishnu/core/ecosystem_status.py`.
- Collect local Mahavishnu liveness/readiness.
- Collect configured dependency health from `settings.health.dependencies`.
- Collect adapter inventory and health (including per-capability health).
- Collect monitoring dashboard summary if initialized.
- Collect active alert count and top alert summaries if initialized.
- Collect workflow summary: active, failed, recent count.
- Return a deterministic `EcosystemStatusReport`.
- Include `generated_at`, `duration_ms`, `schema_version`, `request_id`, and per-section errors instead of failing the whole report.
- Use `asyncio.gather` with per-section timeouts for concurrent collection (not sequential).
- Add staleness detection: compare each section's `last_updated_at` against configurable thresholds.
- Add `capacity_pct` collection where available.
- Define per-dependency degradation modes: what Mahavishnu does when each dependency is down.
- Reconcile `monitoring.metrics` and `mahavishnu/core/routing_metrics.py` into a single metrics module.
- Pull `experiment_id` cardinality fix from CP Phase 5 to CP0 as a blocking prerequisite for all metrics-dependent phases (see Phase 5 task list for the fix description).

The canonical report model is defined in Section 4.1 above — implement against that shape, not a minimal subset.

Note: `tests/unit/test_ecosystem_status.py` is created in Phase 1. Phase 2 extends it with aggregator-specific tests. If Phase 2 runs before Phase 1 is complete, create the file with stub tests.

Acceptance criteria:

- a failed subsection produces an `unknown` or `unhealthy` subsection with an `SectionError`, not an exception
- report output is structurally valid against the Section 4.1 Pydantic model; no `dict[str, Any]` in public report fields
- no state mutation happens during report generation

Validation:

```bash
uv run pytest tests/unit/test_ecosystem_status.py tests/integration/test_ecosystem_contracts.py
```

### Phase 3: CLI and MCP Exposure

Goal: make the canonical report available to humans and agents.

Tasks:

- Add CLI subcommands:
  - `mahavishnu ecosystem status`
  - `mahavishnu ecosystem status --json`
  - `mahavishnu ecosystem capabilities`
  - `mahavishnu ecosystem capabilities --json`
- Add MCP tools:
  - `ecosystem_status` (with optional `sections`, `include_details`, `timeout_per_section_ms` params)
  - `ecosystem_capabilities` (with optional `capability` filter param)
  - `ecosystem_routing_readiness` (accepts `task_class` param, returns adapter availability and fallback chain)
- Define the MCP error envelope for tool responses:
  ```
  { "error": true, "error_code": "MHV-XXX", "message": "...",
    "recovery": [...], "retryable": bool, "retry_after_seconds": int | None }
  ```
- Define error wrapping rules for remote service errors (preserve original service name and error code in `details`; use Mahavishnu error code MHV-306 or new MHV-500 range for ecosystem proxy errors).
- **Error code conflict check:** Before assigning MHV-500 through MHV-503, verify these ranges do not conflict with existing `ErrorCode` values in `mahavishnu/core/errors.py`. If they do, select the next available range and update this plan accordingly.
- Register tool versions in `mahavishnu/mcp/tool_versions.py`.
- Add `deprecated` and `deprecated_replaced_by` fields to tool metadata for redundant tools identified in Phase 0.
- Update contract tests to include the new canonical ecosystem tools.
- Add Pydantic schema validation tests for all MCP tool responses.
- Keep legacy tools available.

Candidate files:

- `mahavishnu/_main_cli.py`
- `mahavishnu/ecosystem_cli.py`
- `mahavishnu/mcp/tools/health_tools.py` or new `mahavishnu/mcp/tools/ecosystem_tools.py`
- `mahavishnu/mcp/server_core.py`
- `mahavishnu/mcp/tool_versions.py`
- `tests/integration/test_ecosystem_contracts.py`
- `tests/unit/test_ecosystem_cli.py`
- `tests/unit/test_mcp_server_core.py`

Acceptance criteria:

- CLI and MCP return the same canonical report shape
- new MCP tools are listed by `mcp_list_tools`
- contract tests cover registration and version metadata

Validation:

```bash
uv run pytest tests/unit/test_ecosystem_cli.py tests/unit/test_mcp_server_core.py tests/integration/test_ecosystem_contracts.py
```

### Phase 4: Live TUI Wiring

Goal: convert the existing Textual dashboard from placeholder data to live read-only data.

Tasks:

- Replace TUI placeholder fetchers with a read-only client that calls canonical Mahavishnu APIs.
- Prefer MCP/client boundary per the master spec. In local CLI mode, in-process calls are allowed (Decision 5 in Section 8).
- Add fallback only to explicit unavailable/error state, not stale fabricated data.
- Update Overview screen from `ecosystem_status`.
- Update Routing screen from `ecosystem_capabilities` and `ecosystem_routing_readiness`.
- Update Alerts screen from canonical alert summary.
- Update Sweep screen from workflow summary or recent workflow history.
- Keep all screen actions read-only.
- **UX requirements (from cross-review):**
  - Add a connection status indicator in the TUI status bar (shows MCP/backend reachability).
  - Add a refresh strategy: configurable polling interval + manual refresh keybinding (`r`).
  - Add a staleness indicator when displayed data exceeds freshness threshold.
  - Add keyboard-driven alert filtering by severity on the Alerts screen.
  - Add drill-down capability: selecting a service/adapter shows health check history, recent routing decisions, and recommendations.
  - Unavailable backend must render as "backend unavailable" with `unknown` status — never silently show stale data.
  - Add `/help` and `/health` slash commands as first-class TUI commands.

Candidate files:

- `mahavishnu/tui/app.py`
- optional new `mahavishnu/tui/client.py`
- `tests/unit/test_tui_dashboard.py`

Acceptance criteria:

- no hardcoded health values remain in fetchers
- unavailable backend renders as unavailable/unknown, not healthy
- TUI still has no direct persistence or orchestration authority
- tests verify fetcher shapes using mocked backend responses
- connection status indicator shows MCP/backend reachability in the TUI status bar (verified by test)
- staleness indicator renders when displayed data exceeds freshness threshold (verified by test)
- keyboard-driven alert filtering by severity works on the Alerts screen (verified by test)
- drill-down from service/adapter selection shows health check history, recent routing decisions, and recommendations (verified by test)
- `/help` and `/health` slash commands are registered and functional (verified by test)
- manual refresh keybinding (`r`) triggers a data fetch (verified by test)

Validation:

```bash
uv run pytest tests/unit/test_tui_dashboard.py
```

### Phase 5: Failure-Aware Routing Visibility

Goal: make routing decisions explainable and operationally useful.

Tasks:

- Implement the `RoutingDecision` schema per the canonical definition in Section 4.1 (do not re-define — Section 4.1 is the single authoritative shape). Key fields: `decision_id`, `task_id`, `task_class`, `required_capabilities`, `selected_adapter`, `candidate_adapters` (typed `CandidateEvaluation`), `rejected_adapters` (typed `RejectedAdapter` with enum reason), `fallback_used`, `fallback_chain`, `health_at_decision` (typed `dict[str, CanonicalStatus]`), `cache_hit`, `confidence` (float 0.0-1.0), `decision_latency_ms`, `routing_strategy`, `timestamp`.
- Rejection reasons must use the `RejectionReason` enum from Section 4.1: `health_failed`, `capability_missing`, `cost_exceeded`, `timeout`, `rate_limited`, `disabled` (not free-text — prevents unbounded Prometheus label cardinality).
- Store recent decisions in a bounded ring buffer (last 1000 per task class), not an unbounded log.
- Emit per-decision structured events for the ring buffer (operator debugging) and per-decision Prometheus counters for aggregation (alerting). Do NOT use `task_id` or `workflow_id` as Prometheus labels (high cardinality).
- Add routing confidence score: if the first-choice adapter has high success rate, confidence is high; if degraded recently, confidence is low.
- Expose recent routing decisions in the ecosystem report.
- Show routing readiness in CLI/MCP/TUI via `ecosystem_routing_readiness`.
- Ensure degraded adapters are visible even when not selected.
- Fix `experiment_id` cardinality risk in `routing_metrics.py`: replace unbounded `experiment_id` label with bounded `experiment_group` or move to structured event log only.

Candidate files:

- `mahavishnu/core/adapter_registry.py`
- `mahavishnu/core/task_router.py`
- `mahavishnu/core/routing_metrics.py`
- `mahavishnu/mcp/tools/adapter_registry_tools.py`
- `mahavishnu/tui/app.py`
- `tests/unit/test_routing.py`
- `tests/unit/test_adapter_registry.py`

Acceptance criteria:

- operator can answer "why did Mahavishnu choose this adapter?"
- degraded dependencies visibly affect routing readiness
- routing telemetry does not use unbounded labels or raw user input as metric labels

Validation:

```bash
uv run pytest tests/unit/test_routing.py tests/unit/test_adapter_registry.py tests/unit/test_routing_metrics.py
```

### Phase 6: Ecosystem Capability Inventory

Goal: expose a unified view of services, tools, adapters, and routable workflows.

Tasks:

- Aggregate local MCP tool inventory from `mcp_list_tools`.
- Aggregate adapter metadata from `HybridAdapterRegistry`.
- Include configured dependency criticality from `settings.health.dependencies`.
- Add optional remote service capability probes where each service exposes a compatible endpoint/tool.
- Report unavailable remote inventories explicitly as `unknown`.
- Add capability categories:
  - orchestration
  - retrieval
  - session
  - storage
  - quality
  - monitoring
  - messaging
  - worker/pool

Acceptance criteria:

- one command can answer "what can the ecosystem do right now?"
- local capabilities are available without network calls
- remote capabilities are timeout-bound and never block the whole report

Validation:

```bash
uv run pytest tests/unit/test_ecosystem_status.py tests/integration/test_ecosystem_contracts.py
```

### Phase 7: Operator Recommendations and Runbook Links

Goal: turn status into action without hiding raw signals.

Tasks:

- Add deterministic recommendations to `EcosystemStatusReport`.
- Examples:
  - required service down: start/check that service
  - optional service down: degraded feature warning
  - adapter unhealthy: inspect adapter health and recent failures
  - high alert count: inspect monitoring dashboard
  - no adapters registered: run adapter discovery
- Link recommendations to existing commands.
- Avoid auto-remediation in this phase.

Acceptance criteria:

- every unhealthy required component has at least one recommended next action
- recommendations are deterministic and testable
- no recommendation fabricates a diagnosis when only availability is known

Validation:

```bash
uv run pytest tests/unit/test_ecosystem_status.py
```

## 6. Suggested Execution Order

1. Phase 0: reconcile plan state.
2. Phase 1: normalize status vocabulary and optional dependency semantics.
3. Phase 2: implement `EcosystemStatusService`.
4. Phase 3: expose CLI/MCP canonical status tools.
5. Phase 4: wire TUI to canonical read-only data.
6. Phase 5: improve routing decision explainability.
7. Phase 6: add ecosystem capability inventory.
8. Phase 7: add deterministic operator recommendations.

## 7. Non-Goals

- Do not make the TUI a state owner.
- Do not replace Prefect, Agno, LlamaIndex, Session-Buddy, Akosha, Dhara, or Crackerjack.
- Do not introduce heartbeat-based service discovery.
- Do not add silent filesystem fallbacks for health. Unreachable means unavailable or unknown.
- Do not hard-code local machine paths, ports, or secrets outside configuration.
- Do not add GitHub Actions as a quality gate for this repo.
- Do not define cross-service authentication in this plan (see Impl Plan non-goals; that is a separate security architecture document).
- Do not expose sensitive operational information (secrets, credential references, internal network topology beyond service names) in `ecosystem_status`.

## 7.1 Observability Prerequisites

Before alerting thresholds are meaningful, the following SLIs/SLOs should be defined (either in this plan or a companion observability document):

| SLI | Target | Phase |
|-----|--------|-------|
| Mahavishnu liveness | 99.9% | CP0 |
| Routing decision latency (p99) | < 100ms | CP5 |
| First-choice routing rate | > 95% | CP5 |
| Adapter success rate | > 95% | CP5 |
| Health check aggregation (p99) | < 2s | CP2 |
| `ecosystem status` CLI response | < 5s | CP3 |

## 7.2 Testing Prerequisites

Before shipping each phase, add these test categories:

- **Schema validation tests:** Call MCP tools, parse responses, validate against Pydantic models.
- **Resilience tests:** Mock slow/unreachable dependencies; verify the report still returns with `unknown` status for the unreachable dependency.
- **Cross-service contract tests:** Verify each dependency exposes expected MCP tools (at startup or on-demand).
- **TUI-backend data contract tests:** Verify backend response shapes match what TUI fetchers expect.

## 8. Resolved Decisions

All open decisions from the initial draft have been resolved based on 6-agent cross-review consensus (architecture, delivery, UX, observability, security, API design).

### Decision 1: Canonical CLI naming

**Resolved:** Keep `mahavishnu health` as a backward-compatible dependency-health summary. Add `mahavishnu ecosystem status` as the full canonical ecosystem report. Do not merge them — they answer different questions ("are my dependencies reachable?" vs "what can the ecosystem do right now?").

**Rationale:** Merging conflates two operator intents. `health` is for quick dependency checks. `ecosystem status` is for operational awareness. Both are useful. (Architecture Council + Delivery Lead consensus.)

### Decision 2: MCP `get_health` compatibility

**Resolved:** Keep `get_health` output format unchanged for backward compatibility. Introduce `ecosystem_status` as the new canonical tool. `get_health` remains available but is classified as a legacy compatibility tool.

**Rationale:** Changing `get_health` output breaks existing MCP consumers. Adding a new tool is additive and non-breaking. (Architecture Council + API Designer consensus.)

### Decision 3: Optional dependency failure semantics

**Resolved:** Optional unhealthy dependencies produce overall `degraded`, not `ok` with warnings. An operator who glances at top-level status needs to see that something is wrong. Buried warnings are invisible warnings.

**Severity ordering for aggregation:**
```
disabled < unknown < degraded < unhealthy
```
(where `ok` is baseline). Rules:
- `disabled` component: intentionally off; does not affect overall status
- `unknown` component (timeout): treated as `degraded` for required, ignored for optional
- Single `degraded` optional component: overall `degraded`
- Single `unhealthy` required component: overall `unhealthy`
- Multiple degradations: overall status is the worst non-disabled status

(Delivery Lead + Observability Lead consensus.)

### Decision 4: Remote capability discovery scope

**Resolved:** Implement for Mahavishnu-managed services first (local adapter inventory, local MCP tool inventory). Generalize to Akosha, Session-Buddy, Dhara, and Crackerjack only after the local path is proven. Remote capability probes use HTTP (not MCP) for lower latency and simpler integration.

**Rationale:** Generalizing before one working implementation exists is premature. HTTP probes are simpler for inter-service capability checks; MCP is reserved for TUI-facing surfaces. (Architecture Council + API Designer consensus.)

### Decision 5: TUI data path

**Resolved:** In local CLI mode, the TUI may call an in-process read-only `EcosystemStatusService` directly. In remote/daemon mode, the TUI must use the MCP client. The data model (`EcosystemStatusReport`) is identical in both paths.

**Rationale:** Forcing an MCP round-trip when TUI and server are in the same process adds unnecessary latency. The model being identical ensures no behavioral divergence. (Architecture Council + API Designer consensus.)

### Decision 6 (new): Tool consolidation

**Resolved:** The control plane plan's Phase 0 is expanded to include a tool consolidation audit. The current MCP surface has redundant health tools (`health_check`, `health_check_service`, `health_check_all`, `get_health`, `get_liveness`, `get_readiness`) and duplicate coordination tools (`list_issues`/`coord_list_issues`, `create_todo`/`coord_create_todo`). The canonical `ecosystem_status` tool should subsume most health-related redundancy. Remaining duplicates get a deprecation timeline.

**Rationale:** 174 tools across 14 groups is at the upper limit of manageable. Redundancy confuses tool selection for both human operators and AI agents. (API Designer + Delivery Lead consensus.)

### Decision 7 (new): Status vocabulary transitions

**Resolved:** The canonical status vocabulary supports the following valid transitions:
- `unknown -> ok | degraded | unhealthy` (on first successful health check)
- `ok -> degraded` (on partial failure)
- `ok -> unhealthy` (on complete failure)
- `degraded -> ok` (on recovery)
- `degraded -> unhealthy` (on further degradation)
- `unhealthy -> degraded` (on partial recovery)
- `any -> disabled` (operator action)
- `disabled -> unknown` (on re-enable, pending first health check)

Note: `unhealthy -> ok` directly is allowed but should be logged as a notable recovery event (not suspicious). `unhealthy -> degraded -> ok` is the expected recovery path. Direct `unhealthy -> ok` typically means the underlying issue resolved without a grace period — worth investigating but not an error.

### Decision 8 (new): Per-section staleness in EcosystemStatusReport

**Resolved:** Each section of `EcosystemStatusReport` includes a `last_updated_at` timestamp (not just the global `generated_at`). The aggregator flags sections whose `last_updated_at` exceeds a configurable staleness threshold as `unknown`. The report includes an optional `capacity_pct` field on `ServiceStatus` for saturation awareness.

**Rationale:** A point-in-time snapshot without freshness indicators is useless during incidents. Staleness detection prevents operators from trusting stale health data. (Observability Lead consensus.)

### Decision 9 (new): Adapter per-capability health

**Resolved:** Adapter health is pulled forward from CP Phase 6 to CP Phase 1. `AdapterStatus` supports per-capability health (e.g., Prefect scheduler is `ok` for `WORKFLOW` but `unhealthy` for `BATCH_TASK` because the work pool is full). Monolithic adapter health remains as a computed aggregate.

**Rationale:** An adapter healthy for one task class but not another creates routing blind spots. Per-capability health enables more accurate routing decisions. (Observability Lead consensus.)

## 9. Definition of Done

This update is done when:

- one canonical ecosystem report exists
- CLI, MCP, and TUI consume the same report model
- optional dependency semantics are consistent (degraded, not ok-with-warnings)
- adapter health and dependency health use normalized external statuses
- adapter health includes per-capability breakdown
- health checks distinguish liveness from readiness
- staleness detection flags stale service data as unknown
- TUI screens display live read-only data with connection status and staleness indicators
- TUI has no hardcoded health values in fetchers
- contract tests cover the canonical ecosystem tools
- schema validation tests cover all MCP tool response shapes
- resilience tests cover slow/unreachable dependency scenarios
- redundant MCP tools are deprecated with replacement references
- metrics fragmentation between `monitoring.metrics` and `routing_metrics.py` is resolved
- `experiment_id` cardinality risk in Prometheus metrics is fixed
- each dependency has a documented degradation mode
- operators can answer:
  - what is down?
  - what is degraded?
  - what can the ecosystem do right now?
  - what routing paths are currently viable?
  - why did Mahavishnu choose this adapter for my task?
  - what should I check next?

