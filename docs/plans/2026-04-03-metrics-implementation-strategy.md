---
status: draft
role: historical
date: 2026-04-03
last_reviewed: 2026-07-16
superseded_by: null
topic: observability
---

# Metrics Implementation Strategy

Date: 2026-04-03
Status: Proposed <!-- legacy status: Proposed — see YAML frontmatter -->
Owner: Mahavishnu
Scope: Mahavishnu runtime metrics, Bodai ecosystem metrics interoperability, collector and scrape topology, dashboard and alert readiness

## Purpose

This document defines the implementation strategy to move Mahavishnu and the broader Bodai ecosystem from fragmented, partially wired metrics to a coherent, reliable, and operationally useful observability system.

This is an execution plan, not a brainstorming note. It is intended to drive a sequence of small, reviewable PRs with clear acceptance criteria.

## Executive Summary

Mahavishnu now exposes a valid Prometheus `/metrics` endpoint, but the overall metrics architecture is still split across multiple incompatible or partially wired systems:

- app-local Prometheus exposition via `monitoring/metrics.py`
- a separate routing metrics HTTP server in `mahavishnu/core/routing_metrics.py`
- a narrow OTEL metrics set in `mahavishnu/core/observability.py`
- scrape configs that assume more than the services currently guarantee
- a Session-Buddy bridge that likely does not start due to config drift

The core strategic decision is:

1. Use OpenTelemetry as the canonical instrumentation model.
1. Use one Mahavishnu metrics surface for scrape exposure.
1. Treat separate ad hoc metric servers as transitional and remove them once consolidated.
1. Standardize a small ecosystem metric contract before expanding dashboards and alerts.

## Current State

## What is now working

- Mahavishnu `/metrics` returns real Prometheus exposition text through `mahavishnu/health.py`.
- Active Dhara naming has been cleaned up in runtime code, health config, inventory config, and touched tests.
- The dev environment now resolves `dhara` as an installed package.

## What is still fragmented

### 1. Multiple runtime metric surfaces

- `mahavishnu/health.py` exposes `/metrics`
- `mahavishnu/core/routing_metrics.py` can start a dedicated metrics server on its own port
- `monitoring/metrics.py` defines a broad shared registry but is only partially adopted

Result:

- there is no single trustworthy answer to "where all Mahavishnu metrics live"

### 2. OTEL is present but too narrow

`mahavishnu/core/observability.py` emits only a small set of workflow-centric metrics.

Result:

- key orchestrator behavior is still invisible:
  - queue depth
  - retry and timeout rates
  - dependency latency and failures
  - MCP tool execution latency and error rates
  - worker/pool saturation

### 3. Scrape topology is optimistic

- `monitoring/prometheus.yml` assumes a broad set of services expose `/metrics`
- `config/otel-collector-config.yaml` scrapes only a very limited subset

Result:

- config implies ecosystem observability that is not yet verified in runtime

### 4. Session-Buddy metrics bridge is likely broken

`mahavishnu/integrations/session_buddy_poller.py` reads flattened config fields such as:

- `session_buddy_polling_enabled`
- `session_buddy_polling_endpoint`

But current settings use nested configuration structures.

Result:

- one of the intended cross-service telemetry bridges probably does not start correctly

### 5. Dashboards and alerts are ahead of the data

Dashboard queries and scrape config were written for an intended final architecture, not the current live contract.

Result:

- dashboards may render, but they are not yet a trustworthy operational surface

## Strategic Goals

1. Make Mahavishnu metrics trustworthy and complete enough for daily operation.
1. Establish one canonical metrics path for Mahavishnu.
1. Make OTEL the authoritative instrumentation model.
1. Define a minimal ecosystem metrics contract that other Bodai services can implement consistently.
1. Ensure dashboards and alerts only depend on verified metrics.
1. Build validation into CI and local smoke testing so regressions are caught early.

## Non-Goals

- This plan does not attempt to redesign tracing or logging architecture beyond what is required to align metrics.
- This plan does not require every ecosystem service to adopt OTEL immediately.
- This plan does not require replacing all Prometheus-native metrics at once if transitional compatibility is useful.

## Architectural Decision

## Canonical Model

### Instrumentation

Use OpenTelemetry semantic-style instrumentation for new metrics in Mahavishnu.

### Exposure

Expose one Mahavishnu scrape endpoint at `/metrics`.

### Collection

Use the OTEL collector as the central collection and normalization layer for ecosystem telemetry.

### Query

Prometheus and Grafana should query the collector-exported metrics and the single Mahavishnu app surface, not multiple unrelated ports for the same service.

## Transitional Rule

During migration:

- existing Prometheus-native metrics may remain temporarily
- duplicate concept coverage is acceptable only when documented
- dedicated routing metrics server must be considered transitional and removed after equivalent main-surface coverage exists

## Target State

## Mahavishnu

Mahavishnu should have:

- one `/metrics` endpoint
- one coherent registry
- OTEL-backed instrumentation for core orchestrator lifecycle
- Prometheus-compatible exposition for scrape
- consistent metric naming and labels

## Ecosystem

Each Bodai service should eventually expose:

- `/health`
- `/ready` where applicable
- `/metrics` in Prometheus exposition format

Each service should identify itself consistently via:

- `service.name`
- `service.namespace`
- `deployment.environment`
- `service.instance.id`

## Metric Domains

## Domain 1: Orchestrator Lifecycle

Required:

- workflow accepted total
- workflow started total
- workflow completed total
- workflow failed total
- workflow cancelled total
- workflow retried total
- workflow timed out total
- workflow duration histogram
- workflow repos processed total
- workflow errors total

Suggested attributes:

- `adapter`
- `task_type`
- `status`
- `workflow_kind`

## Domain 2: Queue and Concurrency

Required:

- queue depth gauge
- queue oldest age gauge
- active workflows gauge
- concurrency limit saturation gauge
- tasks waiting total
- enqueue to start latency histogram

Required for worker/pool systems:

- active workers gauge
- idle workers gauge
- worker spawn duration histogram
- task pickup latency histogram
- task duration histogram
- worker failures total

## Domain 3: Routing and Cost

Required:

- routing decision total
- routing latency histogram
- selected adapter total
- fallback total
- fallback chain length histogram
- adapter execution duration histogram
- adapter execution success/failure total
- estimated cost total
- current budget consumption gauge
- budget alerts total
- A/B exposure total
- A/B outcome total

## Domain 4: Dependency Reliability

For:

- Session-Buddy
- Akosha
- Dhara
- Crackerjack
- Oneiric

Required:

- dependency requests total
- dependency request duration histogram
- dependency failures total
- dependency timeouts total
- dependency health status gauge
- circuit breaker state gauge

Suggested attributes:

- `dependency`
- `operation`
- `status`
- `error_type`

## Domain 5: MCP Tool Execution

Required:

- tool calls total
- tool duration histogram
- tool errors total
- tool timeouts total
- tool payload size histogram

Suggested attributes:

- `tool_name`
- `status`
- `calling_service`

## Domain 6: Search, Embeddings, and Persistence

Required:

- embedding requests total
- embedding duration histogram
- embedding failures total
- vector query duration histogram
- vector query empty result total
- persistence query duration histogram
- persistence failures total
- persistence pool usage gauge

## Domain 7: Transport

Required:

- websocket connections gauge
- websocket subscriptions gauge
- websocket broadcast duration histogram
- websocket broadcast dropped total
- websocket errors total

## Domain 8: Ecosystem Bridge Metrics

Required:

- bridge poll total
- bridge poll duration histogram
- bridge poll failures total
- bridge freshness gauge
- bridge ingested metrics total

Applies initially to:

- Session-Buddy poller
- future Akosha and Dhara federation paths if added

## Naming and Label Standards

## Principles

- Prefer stable names over highly detailed names.
- Keep labels low-cardinality.
- Do not put IDs, prompts, file paths, branch names, or free-form error text into labels.
- Put high-cardinality diagnostic detail into logs or traces, not metric labels.

## Label Guidance

Allowed labels:

- service
- dependency
- adapter
- task_type
- worker_type
- pool_type
- status
- operation
- budget_type
- severity

Avoid:

- `workflow_id`
- `repo_path`
- raw exception messages
- user input
- full branch names

## Implementation Workstreams

## Workstream A: Consolidate Mahavishnu Metrics Surface

Objective:

- one app-level `/metrics`
- one authoritative registry

Tasks:

1. Inventory all metrics sources in Mahavishnu:
   - `monitoring/metrics.py`
   - `core/routing_metrics.py`
   - `core/task_metrics.py`
   - `websocket/metrics.py`
   - `core/observability.py`
1. Classify each source as:
   - keep and integrate
   - rewrite into shared registry
   - deprecate
1. Stop treating the separate routing metrics port as a first-class endpoint.
1. Move routing metrics onto the main metrics surface.
1. Ensure all retained Prometheus-native metrics use the same default registry.

Acceptance criteria:

- Mahavishnu exposes one supported scrape endpoint.
- Routing metrics are visible on the same endpoint.
- No dashboard or scrape config depends on a dedicated routing-only port.

## Workstream B: Expand OTEL Coverage for Core Operations

Objective:

- make OTEL the primary instrumentation path for real orchestrator behavior

Tasks:

1. Add workflow lifecycle counters and duration histograms.
1. Add queue depth, wait time, and concurrency metrics.
1. Add dependency request and failure metrics around external service calls.
1. Add MCP tool call and latency metrics.
1. Add worker and pool execution metrics.

Acceptance criteria:

- the core user-visible orchestration path is fully measurable
- each major action has:
  - count
  - latency
  - failure signal

## Workstream C: Repair the Session-Buddy Bridge

Objective:

- make the Session-Buddy poller start reliably and produce metrics

Tasks:

1. Align poller config with the real settings model.
1. Add startup-time validation that logs effective poller config.
1. Instrument poll cycles:
   - poll count
   - poll latency
   - failures
   - freshness
1. Add tests for:
   - config parsing
   - enabled/disabled startup behavior
   - failure and circuit breaker behavior

Acceptance criteria:

- poller starts when enabled
- poller reports useful self-health metrics
- stale or broken configuration is visible immediately

## Workstream D: Make Scrape Topology Honest

Objective:

- ensure Prometheus and OTEL collector configs represent actual runtime availability

Tasks:

1. Audit each service in `monitoring/prometheus.yml`.
1. Mark each target as:
   - verified metrics endpoint
   - planned but not yet implemented
   - remove from default scrape config
1. Narrow default scrape config to verified targets only.
1. Add optional profiles or commented blocks for planned services.
1. Align OTEL collector scrape config with the same truth set.

Acceptance criteria:

- default scrape config contains only endpoints that actually work
- collector config and Prometheus config do not disagree materially

## Workstream E: Dashboard and Alert Hardening

Objective:

- dashboards and alerts should only depend on verified metrics

Tasks:

1. Audit all Grafana dashboards against actual emitted metric names.
1. Remove references to deprecated metric surfaces and ports.
1. Define first operational alert set for Mahavishnu:
   - metrics endpoint down
   - workflow failure rate spike
   - queue age too high
   - dependency error rate too high
   - websocket error rate spike
   - poller stale
1. Add runbook notes for each alert.

Acceptance criteria:

- dashboards load meaningful data from live metrics
- alerts map to actionable operator decisions

## Workstream F: Validation and CI Guardrails

Objective:

- catch metric regressions before release

Tasks:

1. Add unit tests for metrics registration and export.
1. Add smoke tests for `/metrics` content and key metric presence.
1. Add contract tests for naming and label expectations.
1. Add a local validation command for operators:
   - scrape endpoint check
   - metric presence check
   - collector config consistency check
1. Optionally add snapshot-style tests for exported exposition text for critical metrics.

Acceptance criteria:

- a broken `/metrics` endpoint is caught in CI
- missing critical metrics are caught before merge

## PR Sequencing

## PR 1: Dhara Cleanup

Status:

- completed in active code/config paths

## PR 2: Fix `/metrics` Contract

Status:

- completed

Changes:

- `/metrics` now serves Prometheus exposition
- health endpoint tests updated accordingly

## PR 3: Consolidate Routing Metrics onto Main Surface

Changes:

- remove dedicated routing metrics server startup from app bootstrap
- expose routing metrics via main registry and `/metrics`
- update scrape and dashboard references

Primary files:

- `mahavishnu/core/app.py`
- `mahavishnu/core/routing_metrics.py`
- `monitoring/prometheus.yml`
- dashboard docs and tests

## PR 4: Add Core Workflow and Queue Metrics

Changes:

- instrument workflow lifecycle
- instrument queue depth and wait time
- instrument worker saturation

Primary files:

- `mahavishnu/core/app.py`
- worker and pool modules
- tests

## PR 5: Instrument Dependency Reliability

Changes:

- add metrics around health checks and external calls
- add dependency failure and timeout metrics

Primary files:

- `mahavishnu/core/health.py`
- `mahavishnu/core/health_integration.py`
- adapters and external client modules

## PR 6: Repair and Instrument Session-Buddy Poller

Changes:

- fix config drift
- add poller self-health metrics
- add bridge freshness metrics

Primary files:

- `mahavishnu/integrations/session_buddy_poller.py`
- config models and settings
- tests

## PR 7: Dashboard and Alert Alignment

Changes:

- update Grafana dashboards
- update alert rules
- remove stale references to deprecated metrics sources

## Delivery Phases

## Phase 1: Make Metrics Trustworthy

Includes:

- PR 2
- PR 3

Exit criteria:

- one supported `/metrics` endpoint
- routing metrics available on that endpoint

## Phase 2: Make Metrics Operationally Useful

Includes:

- PR 4
- PR 5
- PR 6

Exit criteria:

- workflow, queue, dependency, and poller behavior are measurable

## Phase 3: Make Metrics Actionable

Includes:

- PR 7
- CI validation additions

Exit criteria:

- dashboards and alerts are trustworthy
- regressions are blocked early

## Test Strategy

## Unit Tests

Add or update tests for:

- metrics export contract
- registry initialization
- no duplicate registration failures
- routing metrics on main registry
- dependency metrics emitted on success and failure
- poller config parsing

## Integration Tests

Add or update tests for:

- `/metrics` endpoint contains expected families
- workflow execution increments counters
- failed dependency call increments failure metrics
- websocket traffic increments transport metrics
- collector scrape config matches supported endpoints

## Operator Smoke Tests

Provide documented commands to verify:

1. Mahavishnu `/metrics` reachable
1. key metric families present
1. Prometheus target healthy
1. Grafana panel queries returning data

## Success Criteria

The metrics system is considered in good shape when all of the following are true:

1. Mahavishnu has one supported metrics endpoint.
1. Routing metrics are no longer split onto a separate metrics port.
1. Workflow lifecycle, queue, dependency, MCP tool, and transport metrics are emitted.
1. Session-Buddy poller configuration is correct and measurable.
1. Prometheus default scrape config contains only verified targets.
1. Dashboards query live, verified metrics.
1. Health and metrics contract tests pass in CI.

## Risks

## Risk 1: Duplicate instrumentation during migration

Impact:

- confusing dashboards
- double-counting

Mitigation:

- document transitional duplicates explicitly
- remove duplicate concepts as soon as consolidated metrics are verified

## Risk 2: High-cardinality labels

Impact:

- Prometheus memory growth
- slow queries

Mitigation:

- central review of label design
- no IDs or free-form strings in labels

## Risk 3: Scrape configs drifting from runtime truth

Impact:

- dashboards and alerts silently lie

Mitigation:

- maintain one verified target inventory
- audit scrape configs as part of release checklist

## Risk 4: Test instability in existing websocket and metrics suites

Impact:

- noisy validation during rollout

Mitigation:

- keep rollout PRs narrow
- add `--no-cov` smoke tests for focused validation where needed
- separate pre-existing failures from rollout regressions in PR notes

## Review

This strategy is sound for the current repository state.

Strengths:

- it prioritizes correctness before breadth
- it reduces architectural ambiguity before adding more metrics
- it explicitly separates transitional compatibility from final design
- it sequences work so dashboards and alerts are updated after runtime truth exists

Gaps to watch:

- if OTEL adoption across the ecosystem moves slower than expected, Prometheus-native transitional metrics may live longer than planned
- routing metrics consolidation needs care to avoid breaking existing dashboards during the cutover window
- the Session-Buddy poller should not be treated as an observability dependency until its config model is fixed and tested

Recommendation:

- start with PR 3 next: consolidate routing metrics onto the main metrics surface
- do not add many new metric families until the surface and scrape topology are stable
