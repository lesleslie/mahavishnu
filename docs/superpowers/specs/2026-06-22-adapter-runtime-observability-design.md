# Adapter Runtime Observability v1.0 — Design

**Status:** Draft (brainstormed 2026-06-22)
**Phase:** 3 (Adjacent)
**Pivot:** This spec supersedes the original `cross-machine-session-continuity` design. The git-as-state-store pattern was solving the wrong problem (Claude Code transcript sync) for the wrong deployment model (stateful multi-machine). The actual need is operational telemetry for adapters deployed on stateless serverless infrastructure.

**Source:** Synthesis of the original article analysis (git-as-state-store) inverted for cloud-native constraints. The spec maintains the article's *immutable history* and *join-by-id* principles, applies them to adapter settings + lifecycle + metrics, and stores them in Dhara rather than git.

---

## Overview

This spec defines the **operational telemetry substrate** for adapters deployed on Mahavishnu. Every adapter has:

- An **append-only settings history** — every config change creates a new immutable version; "current active" is the row with no `deactivated_at`. Activation is atomic (Dhara ACID transaction).
- A **lifecycle event log** — `start`, `stop`, `restart`, `settings_activated`, `settings_deactivated`. Each event references the active settings version at the time, via foreign key.
- A **performance metrics stream** — periodic samples (latency, error rate, throughput, etc.). Each metric is tied to the settings version that was active when the metric was recorded.
- A **forensic query API** — given an adapter and a time range, return its settings history, lifecycle events, and metrics joined into one view.

**Cloud Run / serverless constraint:** MCP server instances are stateless and ephemeral. Every read goes to Dhara over HTTP; every write goes to Dhara over HTTP; the local process holds no state.

**Akkosha consumes** the metrics stream for anomaly detection. Session-Buddy is not involved (these aren't human-memory events).

---

## Goals

- **G1.** Forensic visibility: "What config was adapter X running with when it failed last Tuesday?" — answered by joining lifecycle events with settings versions.
- **G2.** Performance A/B comparison: "Which version of adapter X's config produced lower p99 latency?" — answered by grouping metrics by `settings_version_id`.
- **G3.** Lifecycle observability: when did each adapter start, stop, restart, and on what settings version.
- **G4.** Serverless-native: stateless MCP server, state in Dhara, no local filesystem.
- **G5.** Atomic settings activation: at most one active settings version per adapter at any time.

## Non-Goals

- **N1.** Auto-suggesting the next settings version based on A/B results. Future spec.
- **N2.** Hot-reloading settings without restart. v1.0 assumes restart; v1.1 may add hot-reload annotations.
- **N3.** Per-tenant settings scoping. v1.0 single deployment; v2.0 may extend.
- **N4.** Per-request metric sampling. v1.0 per-instance periodic (60s); v1.1 may add per-request samples.

---

## Architecture & Data Flow

```
Cloud Run MCP server instance (ephemeral, stateless):
  ┌──────────────────────────────────────────────────────────────┐
  │  Init (cold start):                                            │
  │    for adapter in managed_adapters:                            │
  │      GET Dhara /adapters/<id>/active-settings-version           │
  │        → apply settings to adapter                             │
  │      POST Dhara /adapters/<id>/lifecycle-events                 │
  │        { event_type=start, settings_version_id=<id> }          │
  │                                                                │
  │  Steady state (every 60s per adapter):                          │
  │    POST Dhara /adapters/<id>/metrics                           │
  │      { metric_name=p99_latency_ms, metric_value=… }            │
  │                                                                │
  │  On shutdown (SIGTERM):                                         │
  │    POST Dhara /adapters/<id>/lifecycle-events                   │
  │      { event_type=stop, reason=sigterm }                        │
  └──────────────────────────────────────────────────────────────┘

Dhara (persistent, ACID):
  ┌──────────────────────────────────────────────────────────────┐
  │  Tables:                                                       │
  │    adapter_settings_versions (append-only; partial unique idx) │
  │    adapter_lifecycle_events    (append-only)                    │
  │    adapter_performance_metrics (append-only)                   │
  └──────────────────────────────────────────────────────────────┘

Operator forensic query (rare, on-demand):
  GET Dhara /adapters/<id>/history?time_from=...&time_to=...
    → {settings_versions, lifecycle_events, performance_metrics, joined}

Akkosha consumer (continuous):
  Subscribes to metrics table; flags anomalies (latency drift, error-rate spikes).
```

---

## Storage Schema (Dhara)

### `adapter_settings_versions`

```sql
CREATE TABLE adapter_settings_versions (
    version_id TEXT PRIMARY KEY,          -- uuid
    adapter_id TEXT NOT NULL,            -- e.g. "prefect", "llamaindex", "agno"
    version_number INTEGER NOT NULL,     -- monotonic per adapter
    config TEXT NOT NULL,                -- JSON config blob
    activated_at TEXT NOT NULL,          -- ISO 8601 UTC
    deactivated_at TEXT,                -- NULL = currently active
    activated_by TEXT NOT NULL,          -- user_id or "system:deploy"
    notes TEXT NOT NULL DEFAULT ''
);

-- At most one active version per adapter. Enforced at the DB level.
CREATE UNIQUE INDEX idx_settings_versions_one_active
    ON adapter_settings_versions (adapter_id)
    WHERE deactivated_at IS NULL;

-- Forensic queries: history of a single adapter's versions.
CREATE INDEX idx_settings_versions_adapter_time
    ON adapter_settings_versions (adapter_id, activated_at DESC);
```

**Activation semantics:** "Activate version V" is a single transaction:
1. `UPDATE adapter_settings_versions SET deactivated_at = now() WHERE adapter_id = ? AND deactivated_at IS NULL`
2. `INSERT INTO adapter_settings_versions (version_id, adapter_id, version_number, config, activated_at, deactivated_at, activated_by, notes) VALUES (...)` with `deactivated_at = NULL`

Dhara's ACID + partial unique index guarantees no two active versions exist concurrently.

### `adapter_lifecycle_events`

```sql
CREATE TABLE adapter_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    adapter_id TEXT NOT NULL,
    settings_version_id TEXT NOT NULL,   -- FK to adapter_settings_versions
    event_type TEXT NOT NULL,            -- start | stop | restart | settings_activated | settings_deactivated
    timestamp TEXT NOT NULL,             -- ISO 8601 UTC
    reason TEXT NOT NULL DEFAULT '',     -- e.g. "sigterm", "settings_change", "error_recovery"
    host_id TEXT NOT NULL DEFAULT '',    -- Cloud Run revision, hostname, etc.
    metadata TEXT NOT NULL DEFAULT '{}'  -- JSON blob for event-specific data
);

CREATE INDEX idx_lifecycle_events_adapter_time
    ON adapter_lifecycle_events (adapter_id, timestamp DESC);
CREATE INDEX idx_lifecycle_events_settings_version
    ON adapter_lifecycle_events (settings_version_id);
```

### `adapter_performance_metrics`

```sql
CREATE TABLE adapter_performance_metrics (
    metric_id TEXT PRIMARY KEY,
    adapter_id TEXT NOT NULL,
    settings_version_id TEXT NOT NULL,  -- FK
    metric_name TEXT NOT NULL,           -- "p50_latency_ms", "p99_latency_ms", "error_rate", "throughput", custom
    metric_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX idx_metrics_adapter_name_time
    ON adapter_performance_metrics (adapter_id, metric_name, recorded_at DESC);
CREATE INDEX idx_metrics_settings_version
    ON adapter_performance_metrics (settings_version_id, metric_name);
```

---

## Python API (`mahavishnu/core/adapter_runtime.py`)

```python
import uuid
from datetime import UTC, datetime
from typing import Any
import os

import httpx


DharaClient = httpx.AsyncClient(
    base_url=os.environ["MAHAVISHNU_DHARA_URL"],
    timeout=httpx.Timeout(5.0),
)


async def get_active_settings_version(adapter_id: str) -> dict | None:
    """Return the currently-active settings version, or None if none active."""
    resp = await DharaClient.get(f"/adapters/{adapter_id}/active-settings-version")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def activate_settings_version(
    adapter_id: str,
    config: dict,
    *,
    activated_by: str,
    notes: str = "",
) -> dict:
    """Atomically: deactivate current + insert new active version. Returns new version row."""
    resp = await DharaClient.post(
        f"/adapters/{adapter_id}/settings-versions",
        json={"config": config, "activated_by": activated_by, "notes": notes},
    )
    resp.raise_for_status()
    return resp.json()


async def record_lifecycle_event(
    adapter_id: str,
    event_type: str,
    settings_version_id: str,
    *,
    reason: str = "",
    host_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict:
    return (await DharaClient.post(
        f"/adapters/{adapter_id}/lifecycle-events",
        json={
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "settings_version_id": settings_version_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "reason": reason,
            "host_id": host_id,
            "metadata": metadata or {},
        },
    )).json()


async def record_performance_metric(
    adapter_id: str,
    metric_name: str,
    metric_value: float,
    settings_version_id: str,
) -> None:
    await DharaClient.post(
        f"/adapters/{adapter_id}/metrics",
        json={
            "metric_id": str(uuid.uuid4()),
            "metric_name": metric_name,
            "metric_value": metric_value,
            "settings_version_id": settings_version_id,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
    )
```

---

## Cold-Start Sequence

```python
# mahavishnu/mcp/server.py — startup hook

import asyncio
import os


async def on_server_init() -> None:
    """Cloud Run startup: load active settings, emit start event, start metrics emitter."""
    for adapter_id in managed_adapters():
        version = await get_active_settings_version(adapter_id)
        if version is None:
            logger.warning(f"no active settings for {adapter_id}; adapter will not start")
            continue
        apply_settings_to_adapter(adapter_id, version["config"])
        await record_lifecycle_event(
            adapter_id=adapter_id,
            event_type="start",
            settings_version_id=version["version_id"],
            host_id=os.environ.get("K_REVISION", "local"),
            reason="server_init",
        )
        start_metrics_emitter(adapter_id, version["version_id"])


async def start_metrics_emitter(adapter_id: str, settings_version_id: str) -> None:
    """Background task: emit metrics every 60s."""
    while True:
        await asyncio.sleep(60)
        samples = collect_adapter_metrics(adapter_id)
        for name, value in samples.items():
            await record_performance_metric(adapter_id, name, value, settings_version_id)
```

---

## MCP Tools

```python
@mcp_tool
async def get_adapter_settings_version(
    adapter_id: str, version_id: str | None = None
) -> dict:
    """Get current (version_id=None) or specified settings version for an adapter."""


@mcp_tool
async def activate_settings_version(
    adapter_id: str, config: dict, *, notes: str = ""
) -> dict:
    """Create new settings version and atomically activate it."""


@mcp_tool
async def record_lifecycle_event(
    adapter_id: str, event_type: str, *, reason: str = "", host_id: str = ""
) -> dict:
    """Record a lifecycle event for an adapter."""


@mcp_tool
async def record_performance_metric(
    adapter_id: str, metric_name: str, metric_value: float
) -> None:
    """Record a single performance metric for an adapter."""


@mcp_tool
async def query_adapter_history(
    adapter_id: str, *, time_from: str | None = None, time_to: str | None = None
) -> dict:
    """Forensic query: settings versions + lifecycle events + metrics."""
```

---

## Adoption & Migration

| Version | Adoption policy |
|---|---|
| **v1.0** | Dhara tables created; MCP server init hook loads active settings + emits start event; metrics emitter runs every 60s (configurable). Cold start is the default flow. |
| **v1.1** | Metrics emit at higher frequency (10s) during active investigations; back to 60s idle. `query_adapter_history` MCP tool ships. |
| **v2.0** | A/B comparison API; auto-suggestion of next settings version based on A/B results. |

**Migration from original spec:** The original `cross-machine-session-continuity` design is superseded by this spec. The git-as-state-store mechanism is **not** retained — serverless constraints rule it out. If cross-machine Claude transcript sync becomes a separate need, it can be a future spec using a different mechanism (Dhara-backed, not git).

---

## Storage & Retrieval

**Dhara tables** — append-only. Settings versions form an immutable history; deactivation is a new row, not a mutation.

**MCP tools** for query. Operators use `query_adapter_history` for forensics. Akkosha consumes metrics for anomaly detection.

**No local state.** Cloud Run instances are stateless; all state lives in Dhara.

---

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| Dhara HTTP timeout | `httpx.TimeoutException` | Retry once; on second failure, abort cold-start with logged error. Cloud Run will retry the instance. |
| Partial unique index violation on activate | `409 Conflict` from Dhara | Concurrent activate calls; retry once with exponential backoff. |
| Settings version referenced by lifecycle event missing | `query_adapter_history` returns event with `settings_version_id` but no matching version | Forensic tool flags orphaned events; operator investigates. |
| Metrics emit fails (network blip) | `httpx` exception | Logged; metrics emit skipped for this tick; next tick retries. |
| Cold start finds no active settings | `get_active_settings_version` returns None | Adapter skipped at startup; operator must activate settings manually. |

---

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | Settings activation: insert v1, activate v2 (atomic). Both versions exist; v1 deactivated; v2 active. |
| **L1 (file isolation)** | Active settings query returns the active row only. Inactive rows not returned. |
| **L2 (service isolation)** | Mocked Dhara client: `record_lifecycle_event` writes correct payload. `record_performance_metric` writes correct payload. |
| **L3 (sandbox)** | Real Dhara: full lifecycle. Cold start → apply settings → emit start event → emit metrics → query history returns full joined view. |
| **L4 (integration)** | Cloud Run simulation: instance cold starts, applies settings, emits start, runs 5 minutes of metrics, "shuts down" (emits stop). Query history returns the full timeline. |

**Coverage target:** `tests/unit/test_adapter_runtime.py` ≥ 95% line coverage.

---

## Implementation Module Paths

| Component | Path |
|---|---|
| Python API | `mahavishnu/core/adapter_runtime.py` |
| Dhara migrations | `mahavishnu/core/dhara_migrations/adapter_runtime.sql` |
| MCP tools | `mahavishnu/mcp/tools/adapter_runtime_tools.py` |
| Cold-start hook | `mahavishnu/mcp/server.py` (modify startup) |
| Metrics emitter | `mahavishnu/background/metrics_emitter.py` |
| L0/L1 tests | `tests/unit/test_adapter_runtime.py` |
| L2 tests | `tests/unit/test_adapter_runtime_api.py` |
| L3 tests | `tests/integration/test_adapter_runtime_dhara.py` |
| L4 tests | `tests/integration/test_adapter_runtime_cold_start.py` |

---

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| Dhara as state store | ACID transactions; partial unique index enforces single-active-version; HTTP API works for serverless | Local filesystem — lost on cold start; cloud-native DB without ACID — partial unique index harder; git — wrong for runtime state |
| Append-only history (deactivation = new row) | Forensic queries always have full state history; metrics tie to specific versions | Mutable `is_active` flag — loses history; can't A/B compare superseded versions |
| Cold-start initialization, not background sync | Stateless Cloud Run model; no local state to sync | Cross-instance sync — adds complexity; runs into cloud-run constraint |
| Atomic activate-new-version via Dhara transaction | No race between deactivate and insert | Two-step with eventual consistency — possible gap with no active version |
| Metrics emit every 60s (not per-request) | Cost-effective; Cloud Run HTTP egress is non-trivial | Per-request metrics — burns HTTP calls; expensive at scale |
| Settings_version_id as the join key | Single FK ties lifecycle, metrics, and forensics together | Composite keys — more complex queries; harder to reason about |
| HTTP API to Dhara from Cloud Run instance | Stateless instance; no local DB connection needed | Persistent local DB connection — incompatible with Cloud Run lifecycle |

---

## Open Questions / Future Work

- **OQ1.** Metrics granularity: per-adapter vs per-adapter-instance vs per-request. v1.0 per-adapter-instance (60s cadence). v1.1 may add per-request samples.
- **OQ2.** Retention: how long to keep metrics and lifecycle events. v1.0 never expires; v1.1 may add retention policy.
- **OQ3.** Hot-reload: can some settings hot-reload, or do all changes require restart? v1.0 assumes restart; v1.1 may add hot-reload annotations per setting.
- **OQ4.** Multi-tenancy: per-tenant adapter settings. v1.0 single deployment; v2.0 may extend.
- **OQ5.** Original `cross-machine-session-continuity` was about Claude transcript sync. If that need resurfaces (e.g. operators want to resume Claude sessions across machines), it's a future spec using Dhara-backed state, not git.

---

## Success Criteria

- **SC1.** Dhara tables (`adapter_settings_versions`, `adapter_lifecycle_events`, `adapter_performance_metrics`) created and migration-applied.
- **SC2.** Partial unique index enforces single-active-version per adapter at the DB level.
- **SC3.** Cold-start sequence loads active settings + emits start event + starts metrics emitter.
- **SC4.** Activate-version is atomic: at no point are two versions active for one adapter.
- **SC5.** MCP tools (`get_adapter_settings_version`, `activate_settings_version`, `record_lifecycle_event`, `record_performance_metric`, `query_adapter_history`) shipped.
- **SC6.** Forensic query answers "what config was X running with at time T?" in one call.
- **SC7.** A/B comparison: metrics grouped by `settings_version_id` surface in `query_adapter_history` output.
- **SC8.** L0–L3 tests green; ≥ 95% line coverage on new modules.
