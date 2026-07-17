# Metrics Remediation Plan

---
status: draft
role: historical
date: 2026-04-03
last_reviewed: 2026-07-16
superseded_by: null
topic: observability
---

Date: 2026-04-03
Status: Proposed  <!-- legacy status: Proposed — see YAML frontmatter -->
Scope: Mahavishnu observability cleanup, Bodai ecosystem metrics rollout, active Dhara naming cleanup

## Goals

1. Establish one clear metrics architecture for Mahavishnu and the Bodai ecosystem.
1. Eliminate stale legacy naming where the current system and package are `Dhara`.
1. Ensure metrics that are defined are actually emitted, scraped, and queryable.
1. Add the missing operational metrics required to run orchestration safely.
1. Provide a phased rollout with low-risk validation at each step.

## Current State Summary

### What is working

- Mahavishnu emits a small OTEL metric set from `mahavishnu/core/observability.py`.
- Mahavishnu emits routing metrics through `mahavishnu/core/routing_metrics.py` on a dedicated Prometheus port.
- The collector config in `config/otel-collector-config.yaml` can receive OTLP and scrape Mahavishnu.
- The health dependency model already treats `dhara` as the active service name in some places.

### What is broken or inconsistent

- `monitoring/metrics.py` defines a broad shared metric inventory, but live code does not import it for runtime collection.
- `mahavishnu/health.py` exposes `/metrics` as JSON-shaped data, not Prometheus text, and references a missing `get_prometheus_metrics`.
- Mahavishnu currently runs multiple observability patterns in parallel:
  - OTEL metric export
  - direct `prometheus_client` servers
  - health endpoint pseudo-metrics
  - offline repo-quality reporting
- `scripts/collect_metrics.py` is empty, but `mahavishnu/metrics_cli.py` depends on it.
- `SessionBuddyPoller` reads flattened config names that do not match the nested settings model.
- Active code still uses legacy naming for Dhara clients, URLs, comments, and fallback logic.

## Active Stale Reference Findings

These are active references in non-archive code or current config and should be cleaned up first.

### P0: code/config names that should be renamed

- `mahavishnu/core/app.py`
  - `self.dhara_url`
  - `_resolve_dhara_url()`
  - `set_dhara_client_base_url(...)`
- `mahavishnu/core/oneiric_client.py`
  - `_dhara_clients`
  - `_default_dhara_base_url`
  - `get_dhara_client()`
  - `set_dhara_client_base_url()`
  - docstrings say "legacy MCP client"
- `settings/mahavishnu.yaml`
  - `health.dependencies.dhara`
  - env var comments still use `...__DHARA__...`
- `mahavishnu/core/workflow_models.py`
  - fallback import uses `from dhara import ...`
  - comments say "Try the Dhara service directly"
- `mahavishnu/core/adapter_registry.py`
  - module and class docs describe "Dhara persistence"
- `mahavishnu/core/health_integration.py`
  - docs and method comments still say "Dhara/SQLite"
  - code uses `get_dhara_client()`

### P1: tests and operational scripts

- WebSocket integration tests still refer to mixed legacy and `dhara` service names and channels.
- WebSocket health/deploy scripts still refer to the legacy service name.
- some migration scripts and metrics schema docstrings still use legacy naming.

### P2: docs

- `docs/DHARA_WIRING.md` is the canonical wiring doc for Dhara integration.
- multiple planning and architecture docs still use legacy naming for current Dhara functionality.
- archive and `.bak` content can be updated last or left as historical material if explicitly marked.

## Target Architecture

### Primary rule

Use OpenTelemetry as the canonical instrumentation layer.

### Operational rule

Expose Prometheus-compatible metrics from the OTEL collector or a single application metrics surface, but do not maintain multiple unrelated metric registries for the same concepts.

### Non-goals

- Do not keep both OTEL-first and ad hoc `prometheus_client`-first instrumentation as co-equal patterns.
- Do not treat offline repo-quality reports as runtime telemetry.

## Recommended Architecture

### Layer 1: Instrumentation

- Mahavishnu code emits OTEL metrics and traces.
- Shared metric naming follows one ecosystem convention.
- Service-level resource attributes identify `service.name`, `service.namespace`, `deployment.environment`, and `service.instance.id`.

### Layer 2: Collection

- OTEL collector receives OTLP from services.
- Collector scrapes only endpoints that are still needed during migration.
- Collector exports metrics to Prometheus remote write and traces to trace backend.

### Layer 3: Query

- Prometheus/Grafana queries come from collector-exported metrics, not from mixed app-local ports with incompatible schemas.

### Layer 4: Historical quality reporting

- Repo coverage and quality snapshots remain a separate subsystem.
- They should be renamed from "metrics" in CLI/help text where ambiguity causes confusion.

## Metric Taxonomy

### A. Orchestrator lifecycle

- `mahavishnu.workflow.started`
- `mahavishnu.workflow.completed`
- `mahavishnu.workflow.failed`
- `mahavishnu.workflow.cancelled`
- `mahavishnu.workflow.duration`
- `mahavishnu.workflow.repos_total`
- `mahavishnu.workflow.errors_total`

Attributes:

- `adapter`
- `task_type`
- `status`
- `repo_count_bucket`

### B. Queue and concurrency

- `mahavishnu.queue.depth`
- `mahavishnu.queue.oldest_age`
- `mahavishnu.worker.active`
- `mahavishnu.worker.idle`
- `mahavishnu.worker.spawn.duration`
- `mahavishnu.worker.task_pickup.duration`
- `mahavishnu.worker.task.duration`
- `mahavishnu.worker.failures`

Attributes:

- `worker_type`
- `pool_type`
- `status`

### C. Routing and cost

Preserve current routing metrics, but migrate them toward OTEL instruments or clearly isolate them as transitional Prometheus-only metrics.

Required concepts:

- routing decisions
- selected adapter
- fallback count
- routing latency
- adapter execution latency
- estimated cost
- budget alert count
- A/B test exposure and outcome

### D. Dependency reliability

For Session-Buddy, Akosha, Dhara, Crackerjack, Oneiric:

- `mahavishnu.dependency.request.total`
- `mahavishnu.dependency.request.duration`
- `mahavishnu.dependency.errors`
- `mahavishnu.dependency.timeout.total`
- `mahavishnu.dependency.circuit_breaker.state`
- `mahavishnu.dependency.health.status`

Attributes:

- `dependency`
- `operation`
- `status_code_class`
- `error_type`

### E. MCP tool execution

- `mahavishnu.mcp.tool.calls`
- `mahavishnu.mcp.tool.duration`
- `mahavishnu.mcp.tool.errors`
- `mahavishnu.mcp.tool.timeouts`
- `mahavishnu.mcp.tool.payload_bytes`

Attributes:

- `tool_name`
- `status`
- `service`

### F. Search, embeddings, and storage

- `mahavishnu.embedding.requests`
- `mahavishnu.embedding.duration`
- `mahavishnu.embedding.errors`
- `mahavishnu.vector.query.duration`
- `mahavishnu.vector.query.empty_results`
- `mahavishnu.persistence.query.duration`
- `mahavishnu.persistence.errors`
- `mahavishnu.persistence.pool.usage`

Attributes:

- `provider`
- `model`
- `backend`
- `operation`

### G. Transport

- `mahavishnu.websocket.connections`
- `mahavishnu.websocket.subscriptions`
- `mahavishnu.websocket.broadcast.duration`
- `mahavishnu.websocket.broadcast.dropped`
- `mahavishnu.websocket.errors`

### H. Ecosystem bridge metrics

For polled or federated metrics:

- `bodai.bridge.poll.total`
- `bodai.bridge.poll.duration`
- `bodai.bridge.poll.errors`
- `bodai.bridge.freshness.seconds`
- `bodai.bridge.metric_ingest.total`

Attributes:

- `source_service`
- `source_tool`
- `status`

## Remediation Workstreams

## Workstream 1: Naming Cleanup

Objective: remove active legacy references where the live component is `Dhara`.

Tasks:

- Rename active config keys and comments to use the canonical `dhara` naming.
- Rename legacy URL-style variables and helper methods to `dhara_url`.
- Rename `get_dhara_client()` and related internal caches to the canonical names.
- Update non-archive docs and tests to use `dhara`.
- Add temporary compatibility shims only where required to avoid breaking callers.

Compatibility rule:

- Keep old helper names only as deprecated wrappers for one release if external call sites may exist.

Acceptance criteria:

- No legacy references remain in active code paths, current config, or non-archive docs except for explicit historical notes.

## Workstream 2: Metrics Surface Consolidation

Objective: choose one runtime metrics path.

Recommendation:

- Keep OTEL as the primary instrumentation path.
- Keep `routing_metrics.py` as transitional Prometheus output until equivalent OTEL coverage exists.
- Remove or quarantine unused shared instrumentation in `monitoring/metrics.py` unless it is wired into live services.

Tasks:

- Decide which of these becomes canonical:
  - OTEL-only instrumentation with collector export
  - OTEL instrumentation plus a single Prometheus exposition endpoint
- Mark other metric modules as deprecated or migrate them.
- Replace `mahavishnu/health.py` `/metrics` behavior with actual Prometheus text or remove that endpoint from that module.

Acceptance criteria:

- Every advertised `/metrics` endpoint returns Prometheus text.
- No endpoint claims metrics support while returning JSON wrappers.

## Workstream 3: Runtime Wiring Fixes

Objective: make collection actually happen.

Tasks:

- Fix `SessionBuddyPoller` to read nested settings from `config.session_buddy_polling.*`.
- Verify `ObservabilityManager` initializes from real settings and flushes cleanly on shutdown.
- Audit startup paths for goal-team, websocket, and task metrics so each metric module is either wired or removed.
- Ensure `HealthEndpoint` and app startup expose one coherent health/readiness/metrics interface.

Acceptance criteria:

- Turning on a config flag causes metrics to appear in collector output within one scrape interval.
- Poller metrics appear when Session-Buddy polling is enabled.

## Workstream 4: Ecosystem Scrape Topology

Objective: align scrape config with real services.

Tasks:

- Inventory which services actually expose `/metrics` today:
  - Mahavishnu
  - Session-Buddy
  - Akosha
  - Crackerjack
  - Dhara
  - Oneiric
- Remove scrape targets that do not exist yet.
- Add service discovery metadata and standard labels.
- Separate "configured target" from "verified target" in docs.

Acceptance criteria:

- `monitoring/prometheus.yml` contains only verified live endpoints or clearly marked planned targets.
- OTEL collector scrape config matches the production topology.

## Workstream 5: Runtime Metric Expansion

Objective: add the missing operational metrics.

Priority order:

1. workflow lifecycle
1. dependency reliability
1. queue and worker saturation
1. MCP tool execution
1. persistence and vector search
1. websocket transport
1. cost and token economics

Acceptance criteria:

- Grafana can answer:
  - What is failing right now?
  - Where is latency concentrated?
  - Which dependency is degraded?
  - Are workers saturated?
  - Are retries and fallbacks growing?
  - What is the cost trend by adapter/model?

## Workstream 6: Repo-Quality Reporting Separation

Objective: stop mixing static repo reports with runtime telemetry.

Tasks:

- Restore or replace `scripts/collect_metrics.py`.
- Rename CLI/help text from generic "metrics" to "quality metrics" or "repo metrics" where appropriate.
- Keep snapshot storage in a dedicated historical reporting subsystem.

Acceptance criteria:

- `mahavishnu metrics ...` either works end-to-end or is replaced by a clearer command.
- Runtime observability and repo-quality reporting are documented as separate systems.

## Phased Rollout

### Phase 0: Inventory and freeze

Duration: 1 day

Tasks:

- Freeze new metric additions unless they use the target architecture.
- Inventory live endpoints and dashboards.
- Inventory current queries and alerts.

Deliverables:

- verified target matrix
- stale reference list
- dashboard query map

### Phase 1: Naming and endpoint correctness

Duration: 1 to 2 days

Tasks:

- Rename active legacy references to `Dhara`.
- Fix `/metrics` endpoint behavior.
- Fix Session-Buddy poller config access.

Deliverables:

- naming cleanup PR
- endpoint correctness PR

### Phase 2: Canonical instrumentation path

Duration: 2 to 3 days

Tasks:

- Decide OTEL-first implementation details.
- Migrate or deprecate duplicate metric modules.
- Document approved metric naming conventions.

Deliverables:

- instrumentation ADR
- code cleanup PR

### Phase 3: Add missing Mahavishnu operational metrics

Duration: 3 to 5 days

Tasks:

- Add dependency, queue, worker, tool, and persistence metrics.
- Validate in local collector + Prometheus + Grafana.

Deliverables:

- orchestration metrics PR
- dashboards update PR

### Phase 4: Ecosystem rollout

Duration: 1 to 2 weeks across services

Tasks:

- Add/verify instrumentation in Session-Buddy, Akosha, Crackerjack, Dhara, Oneiric.
- Standardize resource attributes and metric names.
- Add bridge freshness metrics where direct instrumentation is not available.

Deliverables:

- per-service rollout checklist
- verified scrape config

## Validation Plan

### Unit validation

- metric instruments initialize once
- duplicate registration does not occur
- config flags enable and disable instrumentation correctly
- poller reads nested config correctly

### Integration validation

- service startup exports metrics to collector
- collector receives OTLP metrics
- Prometheus can query each required metric
- Grafana dashboard panels return non-empty results

### Operational validation

- inject dependency failure and confirm:
  - error counter increments
  - latency rises
  - circuit breaker state changes
  - alert fires if configured
- saturate worker pool and confirm queue depth and worker saturation metrics move
- run a failed workflow and confirm lifecycle, error, and dependency metrics all correlate

## Review Checklist

- No metric is defined without a confirmed emitter.
- No endpoint is documented as `/metrics` unless it returns Prometheus text.
- No dashboard query depends on a metric that is only present in docs/examples.
- No active code path refers to Dhara by the old name.
- Repo-quality reporting is clearly separated from runtime telemetry.
- All new metrics include bounded-cardinality attributes.

## Risks

- Metric cardinality explosion from per-repo or per-workflow labels.
- Temporary dual-publish period causing duplicate dashboards or alert noise.
- Existing tests may assume old names.
- External systems may still import old helper names.

## Mitigations

- Prohibit unbounded labels like full repo path, workflow ID, raw error text, or user input.
- Use compatibility wrappers during rename phase.
- Update dashboards and alerts in the same phase as metric renames.
- Add a short deprecation window for renamed helpers.
- Package-level imports should move to `dhara` as part of the cleanup.

## Recommended Execution Order

1. Fix naming drift in active code and config.
1. Fix endpoint correctness and poller config drift.
1. Standardize on OTEL-first instrumentation.
1. Add missing Mahavishnu operational metrics.
1. Roll out verified ecosystem collection service by service.
1. Restore or rename the offline repo-quality reporting CLI.

## Immediate Next PRs

### PR 1

Title: `refactor(observability): rename active legacy references to dhara`

Scope:

- app config helpers
- oneiric client naming
- active docs/comments/tests

### PR 2

Title: `fix(metrics): make metrics endpoints and poller wiring truthful`

Scope:

- fix `/metrics` implementation
- fix Session-Buddy poller config field access
- remove or mark dead metrics paths

### PR 3

Title: `feat(observability): add orchestrator dependency and queue metrics`

Scope:

- dependency request metrics
- queue depth and worker saturation
- MCP tool execution metrics
