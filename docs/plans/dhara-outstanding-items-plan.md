---
status: active
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: storage-consolidation
---

# Dhara AsyncStorage Bug Fix + Outstanding Items Plan

**Date:** 2026-06-01
**Author:** Claude

## Context

After completing the MCP connection stability plan (per `mcp-connection-stability-plan.md`), we deferred Dhara's `TypeError: Expected AsyncStorage` initialization bug and four outstanding review items. This plan addresses all of them.

______________________________________________________________________

## Part 1: Dhara Initialization Bug — Root Cause

### Error

```
TypeError: Expected AsyncStorage, got <class 'dhara.storage.file.FileStorage'> - missing init
```

### Root Cause

`DharaMCPServer.run()` (server_core.py:922) calls:

```python
asyncio.run(self._init_async_stores())
```

`server_core.py:927-931`:

```python
async def _init_async_stores(self) -> None:
    from dhara.core.connection import AsyncConnection
    async_conn = await AsyncConnection.new(self.storage)
```

`self.storage` is a `FileStorage` instance (sync `Storage`, not `AsyncStorage`).

`AsyncConnection.new()` (connection.py:392-396) checks:

```python
required_methods = ['init', 'load', 'begin', 'store', 'end', 'sync', 'new_oid', 'gen_oid_record']
for method in required_methods:
    if not hasattr(storage, method):
        raise TypeError(f"Expected AsyncStorage, got {type(storage)} - missing {method}")
```

`FileStorage` has `new_oid`, `load`, `store`, etc. — but NOT `init`. The check fails with "missing init".

This is **not a FileStorage bug** — `FileStorage` is a perfectly valid sync `Storage`. The bug is that `_init_async_stores()` passes a sync storage to `AsyncConnection.new()` which expects an `AsyncStorage`.

### Solution: Use `AsyncSqliteStorage`

Dhara already has a fully-implemented async storage: `AsyncSqliteStorage` (storage/sqlite.py:297+).

`AsyncSqliteStorage` implements the `AsyncStorage` protocol with all required methods including `async def init()`.

**The fix**: `_init_async_stores()` should create an `AsyncSqliteStorage` instance, call its `init()`, then pass it to `AsyncConnection.new()`. This correctly follows the async initialization pattern.

______________________________________________________________________

## Part 2: Fix for `_init_async_stores()`

### Current Code (server_core.py:927-944)

```python
async def _init_async_stores(self) -> None:
    """Initialize async stores from the sync connection for async tool dispatch."""
    from dhara.core.connection import AsyncConnection

    async_conn = await AsyncConnection.new(self.storage)
    self._async_kv_store = AsyncKVTimeSeriesStore(
        async_conn,
        retention=TimeSeriesRetention(
            retention_days=self.config.time_series.retention_days
        ),
    )
    self._async_ecosystem_state = AsyncEcosystemStateStore(
        async_conn,
        event_retention=EventRetention(
            retention_days=self.config.time_series.event_retention_days
        ),
    )
    self._async_adapter_registry = AsyncAdapterRegistry(async_conn)
```

### Fixed Code

```python
async def _init_async_stores(self) -> None:
    """Initialize async stores from AsyncSqliteStorage for async tool dispatch."""
    from dhara.core.connection import AsyncConnection
    from dhara.storage.sqlite import AsyncSqliteStorage

    # Create AsyncSqliteStorage and initialize it
    async_storage = AsyncSqliteStorage(url="sqlite+aiosqlite:///dev/shm/dhara_async.db")
    await async_storage.init()

    # Create async connection with the initialized AsyncStorage
    async_conn = await AsyncConnection.new(async_storage)
    self._async_kv_store = AsyncKVTimeSeriesStore(
        async_conn,
        retention=TimeSeriesRetention(
            retention_days=self.config.time_series.retention_days
        ),
    )
    self._async_ecosystem_state = AsyncEcosystemStateStore(
        async_conn,
        event_retention=EventRetention(
            retention_days=self.config.time_series.event_retention_days
        ),
    )
    self._async_adapter_registry = AsyncAdapterRegistry(async_conn)
```

**Key changes:**

1. Import `AsyncSqliteStorage` instead of using sync `self.storage`
1. Call `async_storage.init()` before passing to `AsyncConnection.new()` — this is required because `AsyncConnection.new()` calls `storage.init()` as part of initialization
1. Pass the initialized `AsyncSqliteStorage` to `AsyncConnection.new()`

**Why this works**: `AsyncSqliteStorage` implements the full `AsyncStorage` protocol including `async def init()`. `AsyncConnection.new()` first checks for the method's presence (`hasattr(storage, 'init')` → True), then calls `await storage.init()` during connection setup.

______________________________________________________________________

## Part 3: Outstanding Items from MCP Connection Stability Review

### Item 3A: `time_range_minutes` bounds check (LOW)

**From:** `security-auditor` review
**Severity:** LOW

`BodaiComponentMCPClient.query_local_traces()` passes `time_range_minutes` directly to the MCP tool call. No bounds validation exists.

**Fix:** Add bounds checking in `query_local_traces`:

```python
async def query_local_traces(
    self,
    task_class: str,
    time_range_minutes: int = 60,
) -> list[dict[str, Any]]:
    # Validate bounds: 1 minute minimum, 10080 minutes (1 week) maximum
    time_range_minutes = max(1, min(time_range_minutes, 10080))
    ...
```

**Effort:** Low — single method, minimal change.

______________________________________________________________________

### Item 3B: Session-loss alerting for FitnessAnalyzer (MEDIUM)

**From:** `devops-troubleshooter` review
**Severity:** MEDIUM

When `BodaiComponentMCPClient` loses its MCP session mid-poll (server-side timeout), there is no alerting — the failure is silently logged at DEBUG level. A production system should surface this.

**Fix:** Add session-loss detection and alerting to `FitnessAnalyzer._collect_traces()`:

1. After a failed `client.query_local_traces()` call, check if the error is connection-related (session lost)
1. Log at WARNING level with component endpoint identification
1. Track consecutive failures per component
1. Alert after N consecutive failures (e.g., 3)

**Effort:** Medium — requires failure tracking state in `FitnessAnalyzer`.

______________________________________________________________________

### Item 3C: URL validation on `base_url` (MEDIUM)

**From:** `security-auditor` review
**Severity:** MEDIUM

`BodaiComponentMCPClient.__init__` accepts `base_url` without validating it. Malformed URLs could cause confusing errors.

**Fix:** Add URL validation using Python's `urllib.parse`:

```python
from urllib.parse import urlparse

def __init__(self, base_url: str, timeout: float = 30.0, token: str | None = None) -> None:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {base_url!r} — must include scheme and host")
    ...
```

**Effort:** Low — single validation in `__init__`.

______________________________________________________________________

### Item 3D: Issue 3 (PosixPath) severity for `wait_for_dependency` (MEDIUM)

**From:** `devops-troubleshooter` review
**Severity:** MEDIUM

The MCP plan marked Issue 3 (PosixPath JSON serialization) as LOW with the reasoning that `wait_for_dependency` uses MCP protocol, not HTTP `/health`. However, `wait_for_dependency` does call HTTP `/health` directly when checking non-MCP services.

The health probe path (`/healthz`) returns only `{"status": "ok"}` which avoids the PosixPath issue — but if `wait_for_dependency` ever calls the full `/health` endpoint, it would encounter the serialization error.

**Fix:** Already applied — `str(storage_path)` fix is in `dhara/mcp/server_core.py:825,833`. This is verified and complete.

______________________________________________________________________

## Summary

| Item | Severity | Effort | Status |
|------|----------|--------|--------|
| Dhara `TypeError: Expected AsyncStorage` | HIGH | Medium | ✅ Implemented (Dhara) |
| `time_range_minutes` bounds check | LOW | Low | ✅ Implemented (Mahavishnu) |
| Session-loss alerting for FitnessAnalyzer | MEDIUM | Medium | ✅ Implemented (Mahavishnu) |
| URL validation on `base_url` | MEDIUM | Low | ✅ Implemented (Mahavishnu) |
| PosixPath fix for `wait_for_dependency` | MEDIUM | Done | Already fixed in Dhara |

**Total: 4 items implemented, 1 already fixed**

______________________________________________________________________

## Files to Modify

1. **`dhara/mcp/server_core.py`** — `_init_async_stores()` to use `AsyncSqliteStorage`
1. **`mahavishnu/mcp/bodai_component_client.py`** — bounds check + URL validation
1. **`mahavishnu/pools/fitness_analyzer.py`** — session-loss alerting
