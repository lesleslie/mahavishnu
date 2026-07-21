---
status: complete
role: historical
topic: observability
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Health Schema Spec v1

## Purpose

Define the canonical health contract for Mahavishnu and the ecosystem services it coordinates.

## Liveness Contract

`GET /health` returns:

- `status`: `ok | degraded | unhealthy`
- `service`: service name
- `version`: service version string
- `uptime_seconds`: float seconds since startup
- `timestamp`: ISO timestamp

## Readiness Contract

`GET /ready` returns:

- `ready`: boolean
- `service`: service name
- `dependencies`: map of dependency name to dependency status
- `checks`: map of internal check name to `ok | unhealthy | degraded`

## Dependency Status Contract

Each dependency entry returns:

- `status`: `ok | degraded | unhealthy`
- `latency_ms`: optional float
- `error`: optional string
- `last_check`: optional timestamp

## Versioning Rules

- Schema version is `v1`.
- Additive fields are allowed.
- Breaking changes require a new spec file and explicit migration notes.

## Operational Expectations

- CLI and MCP health surfaces should reflect the same contract as the HTTP endpoint.
- JSON output should remain machine-readable and stable.
- Timeouts and connection failures should report `unhealthy` and preserve the error message.
