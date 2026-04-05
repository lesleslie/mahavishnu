# Ecosystem Metrics Standardization Spec

**Date:** 2026-04-03  
**Status:** Proposed standard  
**Scope:** Mahavishnu, Session-Buddy, Akosha, Dhara, Crackerjack, and future Bodai services

## Purpose

Standardize metrics exposure across the Bodai ecosystem so every service presents the same operational contract to Prometheus, Grafana, operators, and automated verification.

This replaces the current mixed model of:

- main service port `/metrics`
- separate Prometheus exporter ports
- undocumented or conflicting metrics routes

## Standard Contract

Every Bodai service must expose these HTTP endpoints on its primary service port:

- `/health`
- `/ready`
- `/metrics`

### Required Behavior

- `/health` returns JSON liveness data.
- `/ready` returns JSON readiness data.
- `/metrics` returns Prometheus text exposition.
- `/metrics` must not return JSON.
- `/metrics` must be served by the same long-running service process that handles the service’s main traffic.
- Prometheus must scrape the primary service port, not a dedicated exporter port.

## Canonical Endpoint Shape

For a service on port `PORT`, the canonical endpoints are:

- `http://localhost:PORT/health`
- `http://localhost:PORT/ready`
- `http://localhost:PORT/metrics`

Examples:

- Mahavishnu: `8680`
- Session-Buddy: `8678`
- Akosha: canonical service port to be fixed as part of migration
- Dhara: `8683`
- Crackerjack: `8676`

## Anti-Patterns

The following are now deprecated:

- separate Prometheus exporter processes or ports for HTTP services
- scraping a metrics-only sidecar when the main service already has an HTTP server
- documenting multiple competing metrics ports for the same service
- exposing metrics on MCP transport paths like `/mcp/metrics`

These patterns are allowed only as short-lived migration aids and must be removed after the service exposes `/metrics` on its main port.

## Metric Naming Guidance

Metric names should remain service-specific, but follow a consistent structure:

- `<service>_<domain>_<metric>_<unit>`
- counters end with `_total`
- histograms end with `_seconds`, `_bytes`, or other unit suffixes
- gauges avoid `_total`

Examples:

- `mahavishnu_workflows_total`
- `session_buddy_search_duration_seconds`
- `akosha_ingestion_records_total`
- `dhara_adapter_resolution_duration_seconds`
- `crackerjack_test_runs_total`

Shared cross-service families are allowed where the semantics are truly identical:

- `mcp_tool_calls_total`
- `mcp_tool_duration_seconds`

## Verification Standard

A service is considered metrics-ready only if all of the following are true:

1. `GET /metrics` returns `200 OK`
2. content type is Prometheus-compatible text
3. body contains recognizable Prometheus markers such as `# HELP` and `# TYPE`
4. the route is served from the primary service process
5. the route is covered by a repo-local smoke test

## Deployment Standard

- Prometheus scrapes verified services from their primary service port.
- Scrape targets are promoted only after probe verification passes.
- Legacy exporter ports must not be listed as first-class monitoring targets after migration.

## Migration Policy

### Phase 1: Dual Exposure Allowed

During migration, a service may temporarily expose:

- canonical main-port `/metrics`
- legacy exporter `/metrics`

But:

- the main-port route is authoritative
- docs must mark the legacy exporter as deprecated
- Prometheus should prefer the main-port route

### Phase 2: Exporter Removal

After main-port `/metrics` is stable:

- remove the standalone exporter process or server
- remove exporter-port docs
- remove exporter-port scrape jobs
- remove exporter-port health checks

## Service-Specific Migration Targets

### Mahavishnu

- already aligned on `8680/metrics`
- maintain as reference implementation

### Session-Buddy

- migrate from separate `9090` exporter to `8678/metrics`
- remove exporter startup paths after cutover

### Akosha

- choose one canonical service port for `/metrics`
- remove conflicting `8000`, `3002`, and `8682` documentation drift
- expose metrics on the chosen primary port only

### Dhara

- migrate from standalone metrics server to `8683/metrics`
- remove separate exporter server once stable

### Crackerjack

- add first-class `/metrics` on primary service port `8676`
- no separate exporter should be introduced

## CI Expectations

Each repo should add:

- one unit or integration test for `/metrics`
- one startup smoke test proving the canonical endpoints exist
- one grep or docs check preventing new exporter-port drift

## Exit Criteria

The ecosystem is standardized when:

- every active Bodai service exposes `/metrics` on its primary service port
- no active service requires a separate exporter port
- Prometheus scrapes only canonical service endpoints
- docs and dashboards reference only canonical endpoints
- verification passes through the shared inventory workflow
