# Adapter Runtime Observability v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship operational telemetry substrate for adapters on serverless infrastructure — settings versioning, lifecycle events, performance metrics, and forensic query API. Storage is Dhara (HTTP API). Cloud Run instances are stateless; every read and write goes to Dhara.

**Architecture:** `mahavishnu/core/adapter_runtime.py` exposes async functions for get_active_settings_version, activate_settings_version, record_lifecycle_event, record_performance_metric. Cold-start hook loads active settings on init. Background metrics emitter samples every 60s. MCP tools expose query and write surfaces. Partial unique index on `adapter_settings_versions.adapter_id WHERE deactivated_at IS NULL` enforces single-active-version per adapter.

**Tech Stack:** Python 3.13, `httpx` async, Dhara (existing HTTP API), pytest with `asyncio_mode = "auto"`.

______________________________________________________________________

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **Partial unique index** enforces single-active-version per adapter.
- **Atomic activate** = deactivate current + insert new in one Dhara transaction.
- **Metrics cadence**: 60s default; configurable.
- **No local state** in Cloud Run instances.

______________________________________________________________________

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/dhara_migrations/adapter_runtime.sql` | DDL for 3 tables + partial unique index. |
| `mahavishnu/core/adapter_runtime.py` | Async API: get/activate settings + record lifecycle/metrics. |
| `mahavishnu/mcp/tools/adapter_runtime_tools.py` | MCP tools for query and write. |
| `mahavishnu/background/metrics_emitter.py` | Background task: emit metrics every 60s. |
| `tests/unit/test_adapter_runtime.py` | L0/L1 tests for API surface. |
| `tests/integration/test_adapter_runtime_dhara.py` | L3 tests with real Dhara. |
| `tests/integration/test_adapter_runtime_cold_start.py` | L4 tests for cloud-run-like cold-start flow. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/mcp/server.py` | Add `on_server_init()` hook that loads active settings + emits start event. |
| `mahavishnu/background/__init__.py` | Register metrics_emitter. |
| `mahavishnu/mcp/tools/__init__.py` | Register adapter_runtime_tools. |
| `mahavishnu/mcp/tools/profiles.py` | Add adapter_runtime_tools to `full` profile. |

______________________________________________________________________

## Task 1: Dhara migrations

**Files:**

- Create: `mahavishnu/core/dhara_migrations/adapter_runtime.sql`

- [ ] **Step 1: Write the DDL**

Create `mahavishnu/core/dhara_migrations/adapter_runtime.sql`:

```sql
CREATE TABLE IF NOT EXISTS adapter_settings_versions (
    version_id TEXT PRIMARY KEY,
    adapter_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    config TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    deactivated_at TEXT,
    activated_by TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_settings_versions_one_active
    ON adapter_settings_versions (adapter_id)
    WHERE deactivated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_settings_versions_adapter_time
    ON adapter_settings_versions (adapter_id, activated_at DESC);

CREATE TABLE IF NOT EXISTS adapter_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    adapter_id TEXT NOT NULL,
    settings_version_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    host_id TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_events_adapter_time
    ON adapter_lifecycle_events (adapter_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_lifecycle_events_settings_version
    ON adapter_lifecycle_events (settings_version_id);

CREATE TABLE IF NOT EXISTS adapter_performance_metrics (
    metric_id TEXT PRIMARY KEY,
    adapter_id TEXT NOT NULL,
    settings_version_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_adapter_name_time
    ON adapter_performance_metrics (adapter_id, metric_name, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_metrics_settings_version
    ON adapter_performance_metrics (settings_version_id, metric_name);
```

- [ ] **Step 2: Apply the migration**

Apply via the project's Dhara migration runner, or via `execute()`:

```python
from mahavishnu.core.dhara_client import execute
with open("mahavishnu/core/dhara_migrations/adapter_runtime.sql") as f:
    execute(f.read())
```

Expected: 3 tables + 5 indexes created.

- [ ] **Step 3: Verify schema**

Query Dhara: `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'adapter_%'`
Expected: 3 tables.

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/dhara_migrations/adapter_runtime.sql
git commit -m "feat(adapter-runtime): add Dhara migration for settings/lifecycle/metrics tables"
```

______________________________________________________________________

## Task 2: Async Python API

**Files:**

- Create: `mahavishnu/core/adapter_runtime.py`

- Test: `tests/unit/test_adapter_runtime.py`

- [ ] **Step 1: Write the failing tests (with mocked HTTP client)**

Create `tests/unit/test_adapter_runtime.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapter_runtime import (
    activate_settings_version,
    get_active_settings_version,
    record_lifecycle_event,
    record_performance_metric,
)


@pytest.fixture
def mock_dhara(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    client = AsyncMock()
    monkeypatch.setattr("mahavishnu.core.adapter_runtime.DharaClient", client)
    return client


@pytest.mark.asyncio
async def test_get_active_returns_none_on_404(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(status_code=404)
    result = await get_active_settings_version("prefect")
    assert result is None


@pytest.mark.asyncio
async def test_get_active_returns_data_on_200(mock_dhara: AsyncMock):
    mock_dhara.get.return_value = MagicMock(
        status_code=200, json=lambda: {"version_id": "v1", "config": {}}
    )
    result = await get_active_settings_version("prefect")
    assert result == {"version_id": "v1", "config": {}}


@pytest.mark.asyncio
async def test_activate_posts_config(mock_dhara: AsyncMock):
    mock_dhara.post.return_value = MagicMock(
        status_code=201, json=lambda: {"version_id": "new-version-id"}
    )
    result = await activate_settings_version(
        adapter_id="prefect",
        config={"timeout": 30},
        activated_by="alice",
        notes="A/B test",
    )
    assert result == {"version_id": "new-version-id"}
    call_kwargs = mock_dhara.post.call_args.kwargs
    assert call_kwargs["json"]["config"] == {"timeout": 30}
    assert call_kwargs["json"]["activated_by"] == "alice"


@pytest.mark.asyncio
async def test_record_lifecycle_event_writes_correct_payload(mock_dhara: AsyncMock):
    mock_dhara.post.return_value = MagicMock(status_code=201, json=lambda: {})
    await record_lifecycle_event(
        adapter_id="prefect",
        event_type="start",
        settings_version_id="v-abc",
        reason="server_init",
        host_id="rev-42",
    )
    call_kwargs = mock_dhara.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["event_type"] == "start"
    assert payload["settings_version_id"] == "v-abc"
    assert payload["reason"] == "server_init"
    assert payload["host_id"] == "rev-42"
    assert "event_id" in payload
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_record_performance_metric_writes_correct_payload(mock_dhara: AsyncMock):
    mock_dhara.post.return_value = MagicMock(status_code=201, json=lambda: {})
    await record_performance_metric(
        adapter_id="prefect",
        metric_name="p99_latency_ms",
        metric_value=125.5,
        settings_version_id="v-abc",
    )
    call_kwargs = mock_dhara.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["metric_name"] == "p99_latency_ms"
    assert payload["metric_value"] == 125.5
    assert payload["settings_version_id"] == "v-abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_adapter_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the API**

Create `mahavishnu/core/adapter_runtime.py`:

```python
"""Async API for adapter runtime observability.

Dh Http client is module-level; tests monkeypatch the symbol.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx


DharaClient = httpx.AsyncClient(
    base_url=os.environ.get("MAHAVISHNU_DHARA_URL", "http://localhost:8683"),
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
    resp = await DharaClient.post(
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
    )
    resp.raise_for_status()
    return resp.json()


async def record_performance_metric(
    adapter_id: str,
    metric_name: str,
    metric_value: float,
    settings_version_id: str,
) -> None:
    resp = await DharaClient.post(
        f"/adapters/{adapter_id}/metrics",
        json={
            "metric_id": str(uuid.uuid4()),
            "metric_name": metric_name,
            "metric_value": metric_value,
            "settings_version_id": settings_version_id,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
    )
    resp.raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_adapter_runtime.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/adapter_runtime.py tests/unit/test_adapter_runtime.py
git commit -m "feat(adapter-runtime): add async API for settings/lifecycle/metrics"
```

______________________________________________________________________

## Task 3: Cold-start hook in MCP server

**Files:**

- Modify: `mahavishnu/mcp/server.py`

- [ ] **Step 1: Locate the server init section**

Run: `grep -n "def __init__\|on_startup\|lifespan" mahavishnu/mcp/server.py`
Find the existing server initialization section.

- [ ] **Step 2: Add the on_server_init hook**

Add the hook function (or wire it into the existing init section):

```python
async def on_server_init() -> None:
    """Cold-start: load active settings, emit start event, start metrics emitter.

    Called once per Cloud Run instance startup. Idempotent — safe to call
    on warm starts if the platform invokes the hook.
    """
    from oneiric.logging import get_logger
    from mahavishnu.background.metrics_emitter import start_metrics_emitter
    from mahavishnu.core.adapter_runtime import (
        get_active_settings_version,
        record_lifecycle_event,
    )
    from mahavishnu.adapters.registry import managed_adapters, apply_settings_to_adapter

    logger = get_logger(__name__)
    host_id = os.environ.get("K_REVISION", "local")

    for adapter_id in managed_adapters():
        version = await get_active_settings_version(adapter_id)
        if version is None:
            logger.warning(
                f"no active settings for {adapter_id}; adapter will not start",
                extra={"adapter_id": adapter_id, "host_id": host_id},
            )
            continue
        apply_settings_to_adapter(adapter_id, version["config"])
        await record_lifecycle_event(
            adapter_id=adapter_id,
            event_type="start",
            settings_version_id=version["version_id"],
            host_id=host_id,
            reason="server_init",
        )
        await start_metrics_emitter(adapter_id, version["version_id"])
```

Wire it into the existing FastMCP server lifespan / startup:

```python
@asynccontextmanager
async def lifespan(app):
    await on_server_init()
    yield
    # Shutdown: emit stop events for all managed adapters.
    ...
```

(Adapt to the existing server lifecycle pattern.)

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/mcp/server.py
git commit -m "feat(adapter-runtime): cold-start hook loads settings + emits start event"
```

______________________________________________________________________

## Task 4: Metrics emitter background task

**Files:**

- Create: `mahavishnu/background/metrics_emitter.py`

- Test: `tests/unit/test_metrics_emitter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_metrics_emitter.py`:

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.background.metrics_emitter import start_metrics_emitter


@pytest.mark.asyncio
async def test_emitter_samples_and_records_at_interval():
    sleep_calls: list[float] = []
    record_calls: list[dict] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError  # stop after 2 ticks

    async def fake_record(adapter_id, metric_name, metric_value, settings_version_id):
        record_calls.append({
            "adapter_id": adapter_id,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "settings_version_id": settings_version_id,
        })

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch("mahavishnu.background.metrics_emitter.record_performance_metric", side_effect=fake_record),
        patch("mahavishnu.background.metrics_emitter.collect_adapter_metrics",
              return_value={"p99_latency_ms": 100.0, "error_rate": 0.01}),
    ):
        await start_metrics_emitter("prefect", "v-abc", interval_seconds=60)

    assert sleep_calls == [60, 60]
    assert len(record_calls) == 2  # 2 ticks × 2 metrics each
    assert record_calls[0]["metric_name"] == "p99_latency_ms"
    assert record_calls[1]["metric_name"] == "error_rate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_metrics_emitter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the emitter**

Create `mahavishnu/background/metrics_emitter.py`:

```python
"""Background task: emit adapter performance metrics at a configurable interval."""

from __future__ import annotations

import asyncio

from oneiric.logging import get_logger

from mahavishnu.core.adapter_runtime import record_performance_metric
from mahavishnu.adapters.metrics_collector import collect_adapter_metrics

logger = get_logger(__name__)


async def start_metrics_emitter(
    adapter_id: str,
    settings_version_id: str,
    *,
    interval_seconds: int = 60,
) -> None:
    """Emit metrics every interval_seconds. Runs until cancelled.

    Note: at the time of this writing, the spec ties each emitted metric
    to the settings_version_id that was active when the emitter started.
    A future revision may re-query the active version on each tick
    to handle in-flight settings changes.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            samples = collect_adapter_metrics(adapter_id)
            for metric_name, metric_value in samples.items():
                await record_performance_metric(
                    adapter_id=adapter_id,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    settings_version_id=settings_version_id,
                )
        except Exception as exc:
            logger.exception(
                "metrics emit failed; will retry next tick",
                extra={"adapter_id": adapter_id, "error": str(exc)},
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_metrics_emitter.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/background/metrics_emitter.py tests/unit/test_metrics_emitter.py
git commit -m "feat(adapter-runtime): add background metrics emitter"
```

______________________________________________________________________

## Task 5: MCP tools

**Files:**

- Create: `mahavishnu/mcp/tools/adapter_runtime_tools.py`

- Modify: `mahavishnu/mcp/tools/__init__.py` (register in `full` profile)

- Test: `tests/integration/test_adapter_runtime_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_adapter_runtime_tools.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_query_adapter_history_returns_joined_view():
    fake_history = {
        "settings_versions": [{"version_id": "v1", "config": {}}],
        "lifecycle_events": [{"event_id": "e1", "event_type": "start"}],
        "performance_metrics": [{"metric_id": "m1", "metric_name": "p99"}],
    }
    with patch(
        "mahavishnu.mcp.tools.adapter_runtime_tools.DharaClient",
        new_callable=AsyncMock,
    ) as client:
        client.get.return_value = AsyncMock(
            status_code=200, json=lambda: fake_history
        )
        # Import the registered tool and call it.
        from mahavishnu.mcp.tools.adapter_runtime_tools import query_adapter_history
        result = await query_adapter_history.fn(
            adapter_id="prefect", time_from=None, time_to=None
        )
    assert result == fake_history
```

- [ ] **Step 2: Implement the tools**

Create `mahavishnu/mcp/tools/adapter_runtime_tools.py`:

```python
"""MCP tools for adapter runtime observability."""

from __future__ import annotations

import os
from typing import Any

import httpx

from mahavishnu.core.adapter_runtime import DharaClient


async def get_adapter_settings_version_fn(
    adapter_id: str, version_id: str | None = None
) -> dict[str, Any]:
    """Get current or specified settings version for an adapter."""
    if version_id is None:
        resp = await DharaClient.get(f"/adapters/{adapter_id}/active-settings-version")
    else:
        resp = await DharaClient.get(f"/adapters/{adapter_id}/settings-versions/{version_id}")
    if resp.status_code == 404:
        return {"error": "not_found"}
    resp.raise_for_status()
    return resp.json()


async def activate_settings_version_fn(
    adapter_id: str, config: dict, *, notes: str = "", activated_by: str = "system:mcp"
) -> dict[str, Any]:
    """Create new settings version and atomically activate it."""
    resp = await DharaClient.post(
        f"/adapters/{adapter_id}/settings-versions",
        json={"config": config, "activated_by": activated_by, "notes": notes},
    )
    resp.raise_for_status()
    return resp.json()


async def record_lifecycle_event_fn(
    adapter_id: str, event_type: str, *, reason: str = "", host_id: str = ""
) -> dict[str, Any]:
    """Record a lifecycle event for an adapter. settings_version_id must be the active one."""
    from mahavishnu.core.adapter_runtime import get_active_settings_version
    active = await get_active_settings_version(adapter_id)
    if active is None:
        return {"error": "no_active_settings"}
    return await _post_lifecycle(adapter_id, event_type, active["version_id"], reason, host_id)


async def _post_lifecycle(
    adapter_id: str, event_type: str, settings_version_id: str,
    reason: str, host_id: str,
) -> dict[str, Any]:
    from mahavishnu.core.adapter_runtime import record_lifecycle_event
    return await record_lifecycle_event(
        adapter_id=adapter_id,
        event_type=event_type,
        settings_version_id=settings_version_id,
        reason=reason,
        host_id=host_id,
    )


async def record_performance_metric_fn(
    adapter_id: str, metric_name: str, metric_value: float
) -> dict[str, Any]:
    """Record a single performance metric for an adapter. settings_version_id from active."""
    from mahavishnu.core.adapter_runtime import (
        get_active_settings_version, record_performance_metric
    )
    active = await get_active_settings_version(adapter_id)
    if active is None:
        return {"error": "no_active_settings"}
    await record_performance_metric(
        adapter_id=adapter_id,
        metric_name=metric_name,
        metric_value=metric_value,
        settings_version_id=active["version_id"],
    )
    return {"status": "recorded"}


async def query_adapter_history_fn(
    adapter_id: str, *, time_from: str | None = None, time_to: str | None = None
) -> dict[str, Any]:
    """Forensic query: settings versions + lifecycle events + metrics."""
    params: dict[str, str] = {}
    if time_from is not None:
        params["time_from"] = time_from
    if time_to is not None:
        params["time_to"] = time_to
    resp = await DharaClient.get(f"/adapters/{adapter_id}/history", params=params)
    resp.raise_for_status()
    return resp.json()


def register(server, app, mcp_client) -> None:
    """Register adapter runtime observability tools with the MCP server."""

    @server.tool()
    async def get_adapter_settings_version(
        adapter_id: str, version_id: str | None = None
    ) -> dict[str, Any]:
        return await get_adapter_settings_version_fn(adapter_id, version_id)

    @server.tool()
    async def activate_settings_version(
        adapter_id: str, config: dict, *, notes: str = ""
    ) -> dict[str, Any]:
        return await activate_settings_version_fn(adapter_id, config, notes=notes)

    @server.tool()
    async def record_lifecycle_event(
        adapter_id: str, event_type: str, *, reason: str = "", host_id: str = ""
    ) -> dict[str, Any]:
        return await record_lifecycle_event_fn(adapter_id, event_type, reason=reason, host_id=host_id)

    @server.tool()
    async def record_performance_metric(
        adapter_id: str, metric_name: str, metric_value: float
    ) -> dict[str, Any]:
        return await record_performance_metric_fn(adapter_id, metric_name, metric_value)

    @server.tool()
    async def query_adapter_history(
        adapter_id: str, *, time_from: str | None = None, time_to: str | None = None
    ) -> dict[str, Any]:
        return await query_adapter_history_fn(adapter_id, time_from=time_from, time_to=time_to)


# For tests
query_adapter_history = type("Q", (), {"fn": query_adapter_history_fn})()
```

In `mahavishnu/mcp/tools/__init__.py`, add the registration to the `full` profile (locate the existing profile registration pattern).

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/integration/test_adapter_runtime_tools.py -v`
Expected: PASS (1 test)

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/mcp/tools/adapter_runtime_tools.py mahavishnu/mcp/tools/__init__.py tests/integration/test_adapter_runtime_tools.py
git commit -m "feat(adapter-runtime): add MCP tools for query and write surfaces"
```

______________________________________________________________________

## Task 6: End-to-end cold-start integration test

**Files:**

- Test: `tests/integration/test_adapter_runtime_cold_start.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_adapter_runtime_cold_start.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cold_start_loads_active_settings_and_emits_start():
    """Simulate Cloud Run cold start:
    1. Instance spins up
    2. on_server_init runs
    3. For each managed adapter: load active settings + emit start event
    """
    active_settings = {
        "version_id": "v-active-123",
        "config": {"timeout": 30, "pool_size": 5},
    }
    applied: list[tuple[str, dict]] = []
    events: list[dict] = []

    def fake_apply(adapter_id: str, config: dict) -> None:
        applied.append((adapter_id, config))

    async def fake_get(adapter_id: str):
        return active_settings

    async def fake_record(adapter_id, event_type, settings_version_id, **kwargs):
        events.append({
            "adapter_id": adapter_id,
            "event_type": event_type,
            "settings_version_id": settings_version_id,
        })
        return {}

    with (
        patch("mahavishnu.adapters.registry.managed_adapters", return_value=["prefect", "llamaindex"]),
        patch("mahavishnu.adapters.registry.apply_settings_to_adapter", side_effect=fake_apply),
        patch("mahavishnu.core.adapter_runtime.get_active_settings_version", side_effect=fake_get),
        patch("mahavishnu.core.adapter_runtime.record_lifecycle_event", side_effect=fake_record),
        patch("mahavishnu.background.metrics_emitter.start_metrics_emitter", new_callable=AsyncMock),
    ):
        # Import and invoke the hook.
        from mahavishnu.mcp.server import on_server_init
        await on_server_init()

    # Settings applied for both adapters.
    assert ("prefect", {"timeout": 30, "pool_size": 5}) in applied
    assert ("llamaindex", {"timeout": 30, "pool_size": 5}) in applied
    # Start events emitted for both.
    start_events = [e for e in events if e["event_type"] == "start"]
    assert len(start_events) == 2
    assert all(e["settings_version_id"] == "v-active-123" for e in start_events)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/integration/test_adapter_runtime_cold_start.py -v`
Expected: PASS (1 test)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_adapter_runtime_cold_start.py
git commit -m "test(adapter-runtime): add cold-start integration test"
```

______________________________________________________________________

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Dhara schema (3 tables, partial unique index) | Task 1 |
| Python API (4 functions) | Task 2 |
| Cold-start hook | Task 3 |
| Metrics emitter | Task 4 |
| MCP tools | Task 5 |
| Forensic query | Task 5 (query_adapter_history tool) |
| End-to-end integration | Task 6 |

**2. Placeholder scan:** No `TBD`/`TODO` markers.

**3. Type consistency:** `record_lifecycle_event`, `record_performance_metric`, `get_active_settings_version`, `activate_settings_version` signatures consistent across Tasks 2-6.

**Gaps:** `collect_adapter_metrics` is referenced but its implementation is adapter-specific; documented as out-of-scope for this spec (lives in `mahavishnu/adapters/metrics_collector.py` per-adapter).

Plan complete. Moving to spec #9 brainstorm (`multi-client-context-packs`, Phase 3).
