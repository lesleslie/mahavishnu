# Ecosystem Metrics Standardization Plan

**Date:** 2026-04-03
**Status:** Ready for implementation

## Goal

Move the Bodai ecosystem to one consistent metrics model:

- main service port `/metrics`
- no permanent separate exporter ports
- one verification and promotion workflow

## Current State

### Aligned

- Mahavishnu serves Prometheus text at `8680/metrics`

### Misaligned

- Session-Buddy appears to rely on a separate exporter on `9090`
- Dhara has a standalone metrics server implementation
- Akosha documents multiple possible metrics ports
- Crackerjack does not currently expose a working `/metrics` endpoint on `8676`

## Workstreams

### 1. Lock the Standard

Repository:

- `mahavishnu`

Tasks:

- publish the cross-repo spec
- update monitoring inventory to treat separate exporters as deprecated
- keep Prometheus scraping only verified canonical targets

Acceptance:

- spec checked in
- inventory notes explicit about deprecation
- Prometheus config remains canonical-only

### 2. Session-Buddy Migration

Repository:

- `session-buddy`

Tasks:

- expose `/metrics` on the main HTTP or MCP service port `8678`
- wire existing Prometheus metric families into that route
- mark `9090` exporter as deprecated
- remove exporter startup from scripts and docs after cutover

Acceptance:

- `http://localhost:8678/metrics` returns Prometheus text
- `9090` no longer needed
- repo smoke tests cover `/metrics`

### 3. Akosha Port Consolidation

Repository:

- `akosha`

Tasks:

- decide one canonical primary service port for HTTP metrics
- expose `/metrics` on that port
- remove conflicting docs and configs referencing alternate ports for the same contract
- update Kubernetes and local docs to the chosen canonical path

Acceptance:

- one documented canonical service port
- `GET /metrics` works there
- old alternatives removed or explicitly deprecated

### 4. Dhara Exporter Removal

Repository:

- `dhara`

Tasks:

- move metrics serving onto the main service port `8683`
- keep the standalone metrics server only during transition if necessary
- delete standalone metrics server wiring after cutover

Acceptance:

- `http://localhost:8683/metrics` returns Prometheus text
- standalone exporter path removed from active startup flows

### 5. Crackerjack First-Class Metrics

Repository:

- `crackerjack`

Tasks:

- add `/metrics` to the main service on `8676`
- expose basic service, test, lint, and execution metrics
- do not add a separate exporter process

Acceptance:

- `http://localhost:8676/metrics` returns Prometheus text
- metrics route included in repo tests

### 6. Promotion Workflow

Repository:

- `mahavishnu`

Tasks:

- keep `monitoring/ecosystem_metrics_inventory.yml` as source of truth
- use `scripts/verify_ecosystem_metrics.py` to probe live endpoints
- refresh `monitoring/file_sd/verified_metrics_targets.yml`
- promote only services that pass live verification

Acceptance:

- verification output clearly shows pass/fail per service
- Prometheus scrapes only verified targets

## Recommended Implementation Order

1. Mahavishnu policy and docs finalization
1. Session-Buddy migration
1. Dhara migration
1. Akosha port consolidation
1. Crackerjack metrics route
1. final ecosystem promotion sweep

## Concrete PR Sequence

### PR 1: Standard and Deprecation Policy

Repo:

- `mahavishnu`

Changes:

- add spec and plan
- mark separate exporters deprecated in inventory and docs

### PR 2: Session-Buddy Canonical `/metrics`

Repo:

- `session-buddy`

Changes:

- main-port `/metrics`
- deprecate `9090`

### PR 3: Dhara Canonical `/metrics`

Repo:

- `dhara`

Changes:

- main-port `/metrics`
- remove standalone exporter from active paths

### PR 4: Akosha Canonical Port Decision

Repo:

- `akosha`

Changes:

- choose one primary port
- align `/metrics`, docs, and deployment configs

### PR 5: Crackerjack `/metrics`

Repo:

- `crackerjack`

Changes:

- add `/metrics`
- add minimal alert-worthy metrics

### PR 6: Ecosystem Promotion

Repo:

- `mahavishnu`

Changes:

- rerun verification
- refresh verified targets
- enable new services in dashboards and alerts as needed

## Definition of Done

- all active ecosystem services expose `/metrics` on the main service port
- separate exporter ports are removed or unused
- Prometheus inventory contains canonical endpoints only
- verification script passes for all promoted services
- docs no longer describe exporter-port metrics as the steady state
