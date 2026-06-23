# Mahavishnu Monitoring Guide

This document covers the health surfaces of all running services in the Mahavishnu / Bodai ecosystem, including newly adopted Tier 2 services.

**Last updated:** 2026-06-23
**Maintained by:** Mahavishnu

## Why this doc exists

The existing `mcp__mahavishnu__get_health` tool does NOT currently cover:

- OpenObserve (Tier 2 spike candidate)
- PageIndex MCP (Tier 2 spike candidate)
- Maxun (Tier 2 spike candidate)
- Emdash bridge (Tier 2 spike candidate)

This doc fills the gap: when those services are added, operators know which endpoint to monitor, what "healthy" looks like, and what cross-service dependencies exist.

## Service inventory

### Bodai core services (existing)

| Service | Port | Health endpoint | Owner |
|---|---|---|---|
| Mahavishnu | 8680 | `/health` (via `mcp__mahavishnu__get_health`) | Mahavishnu |
| Akosha | 8682 | `/health` (via `mcp__akosha__get_liveness`) | Akosha |
| Dhara | 8683 | `/health` (via `mcp__dhara__get_liveness`) | Dhara |
| Session-Buddy | 8678 | `/health` (via `mcp__session-buddy__get_liveness`) | Session-Buddy |
| Crackerjack | 8676 | `/health` (via `mcp__crackerjack__get_liveness`) | Crackerjack |
| Bodai Crow (HTTP MCP) | 8675 | `/health` (planned; not yet live) | Mahavishnu |
| Oneiric | N/A | N/A (foundation library, no service) | Oneiric |

### WebSocket servers (existing)

| Server | Port | Purpose |
|---|---|---|
| Mahavishnu WS | 8690 | Workflow events broadcast |
| Pool WS | 8691 | Pool status broadcast |
| Session-Buddy WS | 8765 | Session events broadcast |
| Akosha WS | 8692 | Pattern detection broadcast |
| Crackerjack WS | 8686 | Test execution broadcast |

### Tier 2 candidate services (post-spike)

| Service | Port | Health endpoint | Notes |
|---|---|---|---|
| OpenObserve | 127.0.0.1:5080 (bind localhost only) | `/api/v1/healthz` | Container; bind to `127.0.0.1` per security guidance |
| PageIndex MCP | TBD | TBD per spike | Pin to commit SHA if no SemVer tags |
| Maxun | TBD | TBD per spike | Only if pre-check (Playwright dep) passes |
| Emdash bridge | N/A (subprocess) | Exit code 0 = healthy | Stateless CLI invocation |

## Cross-service health checks

### Cross-service dependencies

```
Mahavishnu (8680) → Akosha (8682)   [pattern detection queries]
                → Dhara (8683)     [persistent state writes]
                → Session-Buddy (8678)  [memory writes]
                → Crackerjack (8676)   [quality gate checks]

Dhara (8683) → Postgres / Redis   [via storage adapters]
            → S3 / MinIO          [object storage for adapters]

Akosha (8682) → Dhara (8683)      [reads time-series]
              → Session-Buddy (8678)  [reads memory]

OpenObserve (5080) ← OTel exporter  [from all Bodai services]
                 → S3 / MinIO       [Parquet retention]
```

### Cascade failure scenarios

- **Dhara down**: Mahavishnu writes fail → workflows can't persist state → Akosha reads fail → pattern detection stalls. Critical-path service.
- **Session-Buddy down**: Memory writes fail → distillation can't accumulate evidence → `distilled_skills` and `distilled_workflows` tables empty.
- **Akosha down**: Pattern detection stalls but other services continue. Read-only dependency for most flows.

## Per-service health check recipes

### Mahavishnu / Akosha / Dhara / Session-Buddy / Crackerjack / Bodai Crow

```bash
# Liveness probe
curl -fsS http://localhost:8680/health
curl -fsS http://localhost:8682/health
curl -fsS http://localhost:8683/health
curl -fsS http://localhost:8678/health
curl -fsS http://localhost:8676/health
curl -fsS http://localhost:8675/health  # Bodai Crow (when live)

# Via MCP tool
mcp__mahavishnu__get_health
mcp__akosha__get_liveness
mcp__dhara__get_liveness
mcp__session-buddy__get_liveness
mcp__crackerjack__get_liveness
```

### OpenObserve

```bash
# Health endpoint (must bind to 127.0.0.1:5080, NOT 0.0.0.0)
curl -fsS http://127.0.0.1:5080/api/v1/healthz

# Container status
docker ps --filter name=o2 --format '{{.Names}}: {{.Status}}'

# Resource footprint (target ≤ 4 GB RAM, ≤ 2 CPU cores at 1k spans/sec)
docker stats o2 --no-stream
```

### PageIndex MCP

(Per spike outcome — endpoint TBD after spike.)

### Emdash bridge

```bash
# Subprocess exit code
mahavishnu-emdash-bridge --ping && echo "healthy"
```

## Health dashboard integration

### Grafana datasource configuration

When OpenObserve ships to production, register it as a Prometheus datasource in Grafana:

- **Type**: Prometheus
- **URL**: `http://openobserve:5080/api/default/prometheus`
- **Scrape interval**: 30s (matches OpenObserve's collection cadence)

### Alerting rules

| Alert | Condition | Severity |
|---|---|---|
| `BodaiServiceDown` | Any of {8680, 8682, 8683, 8678, 8676} `/health` returns non-200 for >2 minutes | Critical |
| `DharaWriteBacklog` | `dhara_dirty_oids` table > 10,000 rows | High |
| `OpenObserveDiskUsage` | `/data` partition > 80% full | Medium |
| `SessionBuddyMemoryGrowth` | `conversations_v2` row count > 10M | Medium |
| `PoolWorkerQueue` | Any pool's worker queue > 50% of max_workers | Medium |

## Operational runbooks

(Each service should have a runbook at `docs/runbooks/<service>.md`. Currently the Mahavishnu repo has `docs/runbooks/crow-mcp-server.md` and a planned `docs/runbooks/bodai-crow-server.md`. Other services need runbooks when they reach the production-promotion phase.)

## How to update

When adding a new service or health surface:

1. Add a row to the **Service inventory** table.
2. Add cross-service dependency arrows if the service is on the critical path.
3. Add a **Per-service health check recipes** entry with concrete commands.
4. Add an **Alerting rules** entry with severity and condition.
5. Commit with PR title `docs(monitoring): add <service>`.

## Cross-references

- `THIRD_PARTY_NOTICES.md` — adopted projects with license + posture
- `docs/superpowers/eval/2026-06-22-bodai-ecosystem-candidates.md` — source evaluation
- `.claude/plans/update-the-report-with-rippling-matsumoto.md` — implementation plans
- `mahavishnu/engines/prefect_adapter_impl.py` — workflow observability hooks
- `mahavishnu/websocket/server.py` — workflow event broadcasting