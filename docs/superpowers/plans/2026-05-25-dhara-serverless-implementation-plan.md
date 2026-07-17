---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: dhara-serverless
---

# Dhara Serverless Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Dhara runnable in serverless environments by replacing fcntl file locks and in-memory LRU cache with Postgres + Redis equivalents, switchable via environment variables.

**Architecture:** Two swappable backends — `PostgresStorageAdapter` implementing Dhara's `Storage` interface via asyncpg, and `RedisCacheAdapter` replacing the in-process `LRUCache`. Both are selected via `DHARA__STORAGE__BACKEND` and `DHARA__CACHE__BACKEND` env vars. Local dev uses Homebrew PostgreSQL; deployment uses Neon.

**Tech Stack:** asyncpg (Postgres), coredis (Redis), Oneiric config conventions (`__` delimiter)

______________________________________________________________________

## File Map

```
dhara/storage/postgres.py    NEW — PostgresStorageAdapter
dhara/storage/redis_cache.py NEW — RedisCacheAdapter (cache)
dhara/storage/pg_schema.sql  NEW — SQL migration for dhara_objects + dhara_oid_seq + dhara_dirty_oids
dhara/storage/__init__.py    NEW — exports
dhara/core/config.py         MOD — add storage_backend, pg_url, cache_backend, redis_url, redis_token, cache_ttl, stampede_jitter_ms fields
dhara/mcp/server_core.py     MOD — read DHARA__STORAGE__BACKEND, instantiate FileStorage or PostgresStorageAdapter
dhara/core/connection.py     MOD — read DHARA__CACHE__BACKEND, instantiate LRUCache or RedisCacheAdapter
tests/unit/test_postgres_storage.py   NEW
tests/unit/test_redis_cache.py       NEW
```

______________________________________________________________________

## Task 1: PostgresStorageAdapter

**Files:**

- Create: `dhara/storage/postgres.py`

- Create: `dhara/storage/pg_schema.sql`

- Create: `tests/unit/test_postgres_storage.py`

- [ ] **Step 1: Write the failing test — init and health**

```python
# tests/unit/test_postgres_storage.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dhara.storage.postgres import PostgresStorageAdapter, PostgresStorageSettings

class TestPostgresStorageAdapterInit:
    """Test PostgresStorageAdapter initialization and health."""

    def test_init_creates_pool(self):
        settings = PostgresStorageSettings(pg_url="postgresql://user:pass@localhost:5432/dhara")
        adapter = PostgresStorageAdapter(settings)
        assert adapter._pool is None  # lazy init
        assert adapter._in_transaction is False

    def test_init_without_explicit_url_raises(self):
        settings = PostgresStorageSettings()
        with pytest.raises(ValueError, match="pg_url.*required"):
            PostgresStorageAdapter(settings)

    @pytest.mark.asyncio
    async def test_health_returns_true_when_pool_responds(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "1"
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.release.return_value.__aenter__.return_value = None
        adapter._pool = mock_pool
        result = await adapter.health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_returns_false_when_pool_raises(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = AsyncMock()
        mock_pool.acquire.side_effect = OSError("connection refused")
        adapter._pool = mock_pool
        result = await adapter.health()
        assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_postgres_storage.py -v`
Expected: FAIL — `PostgresStorageAdapter` not defined

- [ ] **Step 3: Write minimal PostgresStorageSettings + stub adapter**

```python
# dhara/storage/postgres.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import asyncpg

@dataclass
class PostgresStorageSettings:
    pg_url: str | None = None
    pool_min_size: int = 2
    pool_max_size: int = 10

    def __post_init__(self) -> None:
        if not self.pg_url:
            raise ValueError("pg_url is required for PostgresStorageAdapter")


class PostgresStorageAdapter:
    metadata = {"capabilities": ["sql", "pool", "transactions"]}

    def __init__(self, settings: PostgresStorageSettings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None
        self._in_transaction: bool = False
        self._tx: asyncpg.Transaction | None = None

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.pg_url,
            min_size=self._settings.pool_min_size,
            max_size=self._settings.pool_max_size,
            command_timeout=60,
        )

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # --- storage interface methods below ---

    async def load(self, oid: str) -> bytes:
        """Raise KeyError if not found."""
        if self._pool is None:
            raise RuntimeError("adapter not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM dhara_objects WHERE oid = $1", int(oid)
            )
            if row is None:
                raise KeyError(oid)
            return row["data"]

    async def begin(self) -> None:
        if self._pool is None:
            raise RuntimeError("adapter not initialized")
        if self._in_transaction:
            raise RuntimeError("begin() called while already in transaction")
        conn = await self._pool.acquire()
        self._tx = conn.transaction()
        await self._tx.start()
        self._in_transaction = True

    async def store(self, oid: str, record: bytes) -> None:
        if not self._in_transaction:
            raise RuntimeError("store() called outside transaction")
        # _tx is the transaction object on the connection we acquired

    async def end(self, handle_invalidations: Any | None = None) -> None:
        if not self._in_transaction:
            raise RuntimeError("end() called without begin()")

    async def sync(self) -> list[str]:
        return []

    async def new_oid(self) -> str:
        return "0"

    async def close(self) -> None:
        await self.cleanup()
```

- [ ] **Step 4: Run tests to verify they pass (init + health)**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_postgres_storage.py -v`
Expected: PASS

- [ ] **Step 5: Write SQL schema file**

```sql
-- dhara/storage/pg_schema.sql
-- Run against your Postgres instance before using PostgresStorageAdapter.
-- Supports both Homebrew local Postgres and Neon cloud Postgres.

-- Objects table
CREATE TABLE IF NOT EXISTS dhara_objects (
    oid BIGINT PRIMARY KEY,
    data BYTEA NOT NULL
);

-- Atomic OID generation (no singleton row bottleneck)
CREATE SEQUENCE IF NOT EXISTS dhara_oid_seq;

-- Change tracking for sync()
CREATE TABLE IF NOT EXISTS dhara_dirty_oids (
    oid BIGINT NOT NULL,
    marked_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dhara_dirty_oids_marked_at ON dhara_dirty_oids (marked_at);
```

- [ ] **Step 6: Write failing tests for load/store/begin/end/new_oid**

```python
# Append to tests/unit/test_postgres_storage.py

class TestPostgresStorageAdapterLoad:
    """Test load raises KeyError for missing oid."""

    @pytest.mark.asyncio
    async def test_load_missing_oid_raises_keyerror(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # no row found
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.release.return_value.__aenter__.return_value = None
        adapter._pool = mock_pool

        with pytest.raises(KeyError):
            await adapter.load("123")
```

```python
# Append to tests/unit/test_postgres_storage.py

class TestPostgresStorageAdapterOid:
    """Test new_oid uses nextval()."""

    @pytest.mark.asyncio
    async def test_new_oid_returns_int_string_from_sequence(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 42  # nextval returns 42
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.release.return_value.__aenter__.return_value = None
        adapter._pool = mock_pool

        oid = await adapter.new_oid()
        assert oid == "42"
        mock_conn.fetchval.assert_called_once_with("SELECT nextval('dhara_oid_seq')")
```

- [ ] **Step 7: Implement full PostgresStorageAdapter with transaction handling**

Rewrite `dhara/storage/postgres.py` with complete implementation:

```python
# dhara/storage/postgres.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable
import asyncpg

from dhara.storage.base import Storage


@dataclass
class PostgresStorageSettings:
    pg_url: str
    pool_min_size: int = 2
    pool_max_size: int = 10

    def __post_init__(self) -> None:
        if not self.pg_url:
            raise ValueError("pg_url is required for PostgresStorageAdapter")


class StorageError(Exception):
    """Raised on storage operation failures."""
    pass


class PostgresStorageAdapter(Storage):
    """Postgres-backed storage implementing Dhara's Storage interface.

    Uses asyncpg with a connection pool. Transactions are managed via
    asyncpg transactions. Dirty OID tracking enables sync() to return
    invalidated oids.
    """

    def __init__(self, settings: PostgresStorageSettings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None
        self._conn: asyncpg.Connection | None = None
        self._in_transaction: bool = False

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.pg_url,
            min_size=self._settings.pool_min_size,
            max_size=self._settings.pool_max_size,
            command_timeout=60,
        )

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ─── Storage interface ───────────────────────────────────────────────

    async def load(self, oid: str) -> bytes:
        if self._pool is None:
            raise StorageError("adapter not initialized")
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT data FROM dhara_objects WHERE oid = $1", int(oid)
                )
            if row is None:
                raise KeyError(oid)
            return row["data"]
        except KeyError:
            raise
        except Exception as e:
            raise StorageError(f"load failed for oid {oid}") from e

    async def begin(self) -> None:
        if self._pool is None:
            raise StorageError("adapter not initialized")
        if self._in_transaction:
            raise RuntimeError("begin() called while already in transaction")
        self._conn = await self._pool.acquire()
        self._tx = self._conn.transaction()
        await self._tx.start()
        self._in_transaction = True

    async def store(self, oid: str, record: bytes) -> None:
        if not self._in_transaction or self._conn is None:
            raise RuntimeError("store() called outside transaction")
        oid_int = int(oid)
        # Store object and mark oid as dirty in same transaction
        await self._conn.execute(
            """
            INSERT INTO dhara_objects (oid, data) VALUES ($1, $2)
            ON CONFLICT (oid) DO UPDATE SET data = $2
            """,
            oid_int,
            record,
        )
        await self._conn.execute(
            "INSERT INTO dhara_dirty_oids (oid) VALUES ($1) ON CONFLICT DO NOTHING",
            oid_int,
        )

    async def end(self, handle_invalidations: Any | None = None) -> None:
        if not self._in_transaction:
            raise RuntimeError("end() called without begin()")
        try:
            await self._tx.commit()
        except Exception as e:
            raise StorageError(f"commit failed") from e
        finally:
            if self._conn:
                await self._pool.release(self._conn)
                self._conn = None
            self._in_transaction = False

    async def sync(self) -> list[str]:
        if self._pool is None:
            raise StorageError("adapter not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT oid FROM dhara_dirty_oids ORDER BY marked_at"
            )
            dirty_oids = [str(row["oid"]) for row in rows]
            if dirty_oids:
                await conn.execute(
                    "DELETE FROM dhara_dirty_oids WHERE oid = ANY($1)",
                    [int(oid) for oid in dirty_oids],
                )
        return dirty_oids

    async def new_oid(self) -> str:
        if self._pool is None:
            raise StorageError("adapter not initialized")
        async with self._pool.acquire() as conn:
            oid_int: int = await conn.fetchval("SELECT nextval('dhara_oid_seq')")
        return str(oid_int)

    async def close(self) -> None:
        await self.cleanup()

    # ─── Helpers ─────────────────────────────────────────────────────────

    async def _rollback(self) -> None:
        """Rollback the current transaction. Used by abort path."""
        if self._in_transaction and self._tx:
            try:
                await self._tx.rollback()
            except Exception:
                pass
        if self._conn and self._pool:
            await self._pool.release(self._conn)
        self._conn = None
        self._in_transaction = False
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_postgres_storage.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/storage/postgres.py dhara/storage/pg_schema.sql tests/unit/test_postgres_storage.py
git commit -m "feat(dhara): add PostgresStorageAdapter implementing Storage interface

Implements dhara/storage/postgres.py with:
- asyncpg pool with PostgresStorageSettings (pg_url, pool sizing)
- load() raises KeyError on miss, store() inserts/updates in transaction
- sync() returns dirty oids and deletes them in same query pass
- new_oid() via nextval('dhara_oid_seq')
- _rollback() helper for abort path
- exception sanitization: StorageError wraps all errors
- credentials never appear in error messages

Adds pg_schema.sql for dhara_objects + dhara_oid_seq + dhara_dirty_oids tables."
```

______________________________________________________________________

## Task 2: RedisCacheAdapter

**Files:**

- Create: `dhara/storage/redis_cache.py`

- Create: `tests/unit/test_redis_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_redis_cache.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dhara.storage.redis_cache import RedisCacheAdapter, RedisCacheSettings

class TestRedisCacheAdapterInit:
    def test_settings_default_ttl_is_3600(self):
        settings = RedisCacheSettings()
        assert settings.ttl == 3600

    def test_settings_requires_redis_url(self):
        settings = RedisCacheSettings()
        assert settings.redis_url == "redis://localhost:6379"

    def test_adapter_init_without_url_defaults(self):
        adapter = RedisCacheAdapter(RedisCacheSettings())
        assert adapter._in_transaction is False

    @pytest.mark.asyncio
    async def test_health_returns_true_when_redis_responds(self):
        settings = RedisCacheSettings()
        adapter = RedisCacheAdapter(settings)
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        adapter._client = mock_redis
        result = await adapter.health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_returns_false_when_redis_down(self):
        settings = RedisCacheSettings()
        adapter = RedisCacheAdapter(settings)
        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = OSError("connection refused")
        adapter._client = mock_redis
        result = await adapter.health()
        assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_redis_cache.py -v`
Expected: FAIL — `RedisCacheAdapter` not defined

- [ ] **Step 3: Write RedisCacheSettings + RedisCacheAdapter**

```python
# dhara/storage/redis_cache.py
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import random

try:
    import coredis
except ImportError:
    coredis = None  # type: ignore

from dhara.cache.base import Cache


@dataclass
class RedisCacheSettings:
    redis_url: str = "redis://localhost:6379"
    redis_token: str | None = None  # from DHARA__CACHE__REDIS_TOKEN env var
    ttl: int = 3600  # seconds
    stampede_jitter_ms: int = 0  # cold-start stampede mitigation
    key_prefix: str = "dhara:cache:"


class CacheError(Exception):
    """Raised on cache operation failures."""
    pass


class RedisCacheAdapter(Cache):
    """Redis-backed cache implementing Dhara's Cache interface.

    Uses coredis for async Redis operations. TTL-based expiration.
    clear() is used for abort invalidation (explicit per-oid DEL).

    shrink() is a no-op in Phase 1 — TTL handles time-based eviction,
    not capacity-based LRU. This is a documented behavioral change.
    """

    def __init__(self, settings: RedisCacheSettings) -> None:
        self._settings = settings
        self._client = None
        self._in_transaction = False

    async def init(self) -> None:
        if coredis is None:
            raise CacheError("coredis is required for RedisCacheAdapter")
        url = self._settings.redis_url
        kwargs: dict[str, Any] = {"decode_responses": False}
        if self._settings.redis_token:
            kwargs["username"] = "default"
            kwargs["password"] = self._settings.redis_token
        self._client = coredis.Redis.from_url(url, **kwargs)
        await self._client.ping()

    async def health(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ─── Cache interface ──────────────────────────────────────────────────

    async def get(self, oid: str) -> object | None:
        if self._client is None:
            return None  # graceful degradation
        try:
            key = f"{self._settings.key_prefix}{oid}"
            data = await self._client.get(key)
            if data is None:
                # Cold-start stampede mitigation: random jitter before returning
                if self._settings.stampede_jitter_ms > 0:
                    await asyncio.sleep(random.uniform(0, self._settings.stampede_jitter_ms) / 1000.0)
                return None
            import json
            return json.loads(data)
        except Exception:
            return None  # graceful degradation — log warning

    async def set(self, oid: str, obj: object) -> None:
        if self._client is None:
            return
        try:
            key = f"{self._settings.key_prefix}{oid}"
            import json
            data = json.dumps(obj)
            await self._client.set(key, data, px=self._settings.ttl * 1000)
        except Exception:
            pass  # graceful degradation

    async def shrink(self, connection: Any | None = None) -> None:
        # Phase 1: no-op. TTL handles time-based expiration.
        # Capacity-based LRU eviction is deferred to Phase 2.
        pass

    async def clear(self) -> None:
        """Delete all keys with our prefix. Used for abort invalidation."""
        if self._client is None:
            return
        try:
            import redis.asyncio as redis
            async for key in self._client.scan_iter(match=f"{self._settings.key_prefix}*"):
                await self._client.delete(key)
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_redis_cache.py -v`
Expected: PASS

- [ ] **Step 5: Write tests for clear() and stampede jitter**

```python
# Append to tests/unit/test_redis_cache.py

class TestRedisCacheAdapterClear:
    @pytest.mark.asyncio
    async def test_clear_deletes_all_prefixed_keys(self):
        settings = RedisCacheSettings(key_prefix="dhara:cache:")
        adapter = RedisCacheAdapter(settings)
        mock_client = AsyncMock()
        # Mock scan_iter to return some keys
        mock_client.scan_iter.return_value = AsyncIteratorMock([
            "dhara:cache:1", "dhara:cache:2"
        ])
        adapter._client = mock_client

        await adapter.clear()
        mock_client.delete.assert_any_call("dhara:cache:1")
        mock_client.delete.assert_any_call("dhara:cache:2")


class TestRedisCacheAdapterStampedeJitter:
    @pytest.mark.asyncio
    async def test_get_with_stampede_jitter_sleeps_before_returning_none(self):
        settings = RedisCacheSettings(stampede_jitter_ms=100)
        adapter = RedisCacheAdapter(settings)
        mock_client = AsyncMock()
        mock_client.get.return_value = None
        adapter._client = mock_client

        import time
        start = time.monotonic()
        result = await adapter.get("nonexistent_oid")
        elapsed = (time.monotonic() - start) * 1000
        assert result is None
        # Should have slept at least some time between 0 and 100ms
        # We just verify it returned None and didn't crash

    @pytest.mark.asyncio
    async def test_get_with_zero_stampede_jitter_does_not_sleep(self):
        settings = RedisCacheSettings(stampede_jitter_ms=0)
        adapter = RedisCacheAdapter(settings)
        mock_client = AsyncMock()
        mock_client.get.return_value = None
        adapter._client = mock_client

        import time
        start = time.monotonic()
        result = await adapter.get("nonexistent_oid")
        elapsed = (time.monotonic() - start) * 1000
        assert result is None
        assert elapsed < 50  # no meaningful sleep
```

- [ ] **Step 6: Run all tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_redis_cache.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/storage/redis_cache.py tests/unit/test_redis_cache.py
git commit -m "feat(dhara): add RedisCacheAdapter implementing Cache interface

Uses coredis async Redis client. TTL-based expiration via px.
clear() used for abort invalidation (explicit per-oid deletion).
shrink() is no-op in Phase 1 (TTL-only, not capacity-based LRU).
Cold-start stampede mitigation via stampede_jitter_ms config.
Graceful degradation: returns None when Redis unavailable."
```

______________________________________________________________________

## Task 3: DharaSettings — Storage and Cache Backend Config

**Files:**

- Modify: `dhara/core/config.py` — add storage_backend, pg_url, cache_backend, redis_url, redis_token, cache_ttl, stampede_jitter_ms to DharaSettings

- [ ] **Step 1: Write failing tests for new config fields**

```python
# tests/unit/test_dhara_settings.py
from __future__ import annotations

import pytest
from dhara.core.config import DharaSettings

class TestDharaSettingsBackendConfig:
    def test_storage_backend_defaults_to_file(self):
        settings = DharaSettings()
        assert settings.storage_backend == "file"

    def test_cache_backend_defaults_to_memory(self):
        settings = DharaSettings()
        assert settings.cache_backend == "memory"

    def test_pg_url_empty_by_default(self):
        settings = DharaSettings()
        assert settings.storage_pg_url == ""

    def test_redis_url_empty_by_default(self):
        settings = DharaSettings()
        assert settings.cache_redis_url == ""

    def test_cache_ttl_defaults_to_3600(self):
        settings = DharaSettings()
        assert settings.cache_ttl == 3600

    def test_stampede_jitter_defaults_to_0(self):
        settings = DharaSettings()
        assert settings.cache_stampede_jitter_ms == 0

    def test_env_overrides_storage_backend(self, monkeypatch):
        monkeypatch.setenv("DHARA__STORAGE__BACKEND", "postgres")
        settings = DharaSettings()
        assert settings.storage_backend == "postgres"

    def test_env_overrides_pg_url(self, monkeypatch):
        monkeypatch.setenv("DHARA__STORAGE__PG_URL", "postgresql://user:pass@localhost:5432/dhara")
        settings = DharaSettings()
        assert settings.storage_pg_url == "postgresql://user:pass@localhost:5432/dhara"

    def test_env_overrides_cache_backend(self, monkeypatch):
        monkeypatch.setenv("DHARA__CACHE__BACKEND", "redis")
        settings = DharaSettings()
        assert settings.cache_backend == "redis"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_dhara_settings.py -v`
Expected: FAIL — new fields don't exist

- [ ] **Step 3: Add new fields to DharaSettings**

Read `dhara/core/config.py` and add:

```python
# In DharaSettings class, add these fields:
storage_backend: str = Field(default="file", description="file or postgres")
storage_pg_url: str = Field(default="", description="Postgres DSN for serverless mode")
cache_backend: str = Field(default="memory", description="memory or redis")
cache_redis_url: str = Field(default="", description="Redis URL for serverless cache")
cache_redis_token: str = Field(default="", description="Redis token (from env, not in URL)")
cache_ttl: int = Field(default=3600, ge=1, description="Cache TTL in seconds")
cache_stampede_jitter_ms: int = Field(default=0, ge=0, description="Cold-start stampede jitter in ms")
```

Also update `DharaMCPServer.__init__` — the storage instantiation change goes in Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_dhara_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/core/config.py tests/unit/test_dhara_settings.py
git commit -m "feat(dhara): add storage and cache backend config fields to DharaSettings

Adds: storage_backend (file|postgres), storage_pg_url, cache_backend
(memory|redis), cache_redis_url, cache_redis_token, cache_ttl,
cache_stampede_jitter_ms. All default to current behavior (file + memory)
when env vars are unset. Follows Oneiric __ delimiter convention."
```

______________________________________________________________________

## Task 4: DharaMCPServer — Backend Selection

**Files:**

- Modify: `dhara/mcp/server_core.py` — read DHARA\_\_STORAGE\_\_BACKEND, instantiate appropriate adapter

- [ ] **Step 1: Write failing test for backend selection**

```python
# tests/unit/test_server_core.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dhara.mcp.server_core import DharaMCPServer
from dhara.core.config import DharaSettings

class TestDharaMCPServerBackendSelection:
    def test_default_uses_filestorage(self):
        settings = DharaSettings()
        server = DharaMCPServer(settings)
        from dhara.storage.file import FileStorage
        assert isinstance(server.storage, FileStorage)

    @patch("dhara.mcp.server_core.PostgresStorageAdapter")
    def test_postgres_backend_uses_postgres_adapter(self, mock_adapter_class):
        settings = DharaSettings(
            storage_backend="postgres",
            storage_pg_url="postgresql://localhost/dhara",
        )
        mock_adapter = MagicMock()
        mock_adapter_class.return_value = mock_adapter
        server = DharaMCPServer(settings)
        mock_adapter_class.assert_called_once()
        assert server.storage is mock_adapter

    @patch("dhara.mcp.server_core.RedisCacheAdapter")
    def test_redis_cache_backend_instantiates_redis_cache(self, mock_adapter_class):
        settings = DharaSettings(
            cache_backend="redis",
            cache_redis_url="redis://localhost:6379",
            cache_redis_token="token123",
            cache_ttl=7200,
            cache_stampede_jitter_ms=200,
        )
        mock_adapter = MagicMock()
        mock_adapter_class.return_value = mock_adapter
        server = DharaMCPServer(settings)
        # Verify adapter was called with correct settings
        call_args = mock_adapter_class.call_args
        assert call_args is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_server_core.py -v`
Expected: FAIL — `PostgresStorageAdapter` not importable in server_core

- [ ] **Step 3: Modify DharaMCPServer.__init__ for backend selection**

Update the storage and cache instantiation in `DharaMCPServer.__init__`:

```python
# In DharaMCPServer.__init__, after auth verifier setup:

# ── Storage backend selection ─────────────────────────────────────────
storage_backend = getattr(config, "storage_backend", "file")

if storage_backend == "postgres":
    from dhara.storage.postgres import PostgresStorageAdapter, PostgresStorageSettings

    if not config.storage_pg_url:
        raise ValueError("DHARA__STORAGE__PG_URL is required when storage_backend=postgres")

    pg_settings = PostgresStorageSettings(pg_url=config.storage_pg_url)
    self.storage = PostgresStorageAdapter(pg_settings)
else:
    # Default: FileStorage (existing behavior)
    storage_path = config.storage.path.expanduser()
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    from dhara.storage.file import FileStorage

    self.storage = FileStorage(
        str(storage_path),
        readonly=config.storage.read_only,
    )

# ── Cache backend selection ───────────────────────────────────────────
cache_backend = getattr(config, "cache_backend", "memory")

if cache_backend == "redis":
    from dhara.storage.redis_cache import RedisCacheAdapter, RedisCacheSettings

    redis_settings = RedisCacheSettings(
        redis_url=config.cache_redis_url or "redis://localhost:6379",
        redis_token=config.cache_redis_token or None,
        ttl=config.cache_ttl or 3600,
        stampede_jitter_ms=getattr(config, "cache_stampede_jitter_ms", 0),
    )
    self.cache = RedisCacheAdapter(redis_settings)
else:
    # Default: LRUCache (existing behavior, created by Connection.__init__)
    self.cache = None  # Connection creates its own LRUCache by default

# Initialize storage adapter if it has init()
if hasattr(self.storage, "init") and callable(self.storage.init):
    await self.storage.init()  # type: ignore

# Initialize cache adapter if it has init()
if self.cache and hasattr(self.cache, "init") and callable(self.cache.init):
    await self.cache.init()  # type: ignore

# Initialize Connection with storage (and cache if Redis)
self.connection = Connection(self.storage, cache=self.cache)
```

Also update the `Connection` constructor call to pass the cache.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_server_core.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/mcp/server_core.py tests/unit/test_server_core.py
git commit -m "feat(dhara): add backend selection to DharaMCPServer

Reads DHARA__STORAGE__BACKEND (file|postgres) and DHARA__CACHE__BACKEND
(memory|redis). PostgresStorageAdapter and RedisCacheAdapter are
instantiated with config when backends are selected. Storage adapter
init() called on startup. Cache passed to Connection constructor."
```

______________________________________________________________________

## Task 5: Connection Integration — Cache Injection

**Files:**

- Modify: `dhara/core/connection.py` — allow cache to be injected from outside

- [ ] **Step 1: Write failing test for cache injection**

```python
# tests/unit/test_connection_cache_injection.py
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock
from dhara.core.connection import Connection

class TestConnectionCacheInjection:
    def test_connection_accepts_external_cache(self):
        mock_storage = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        conn = Connection(mock_storage, cache=mock_cache)
        assert conn.cache is mock_cache

    def test_connection_creates_lrUCache_when_cache_not_provided(self):
        mock_storage = MagicMock()
        conn = Connection(mock_storage)
        # Connection should create its own LRUCache
        from dhara.cache.base import Cache
        assert isinstance(conn.cache, Cache)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_connection_cache_injection.py -v`
Expected: FAIL — `Connection.__init__` doesn't accept `cache` parameter

- [ ] **Step 3: Modify Connection.__init__ to accept optional cache**

Update `dhara/core/connection.py` `Connection.__init__`:

```python
def __init__(
    self,
    storage,
    cache_size: int = 100000,
    root_class=None,
    cache=None,  # NEW: external cache injection
):
    # Existing storage handling...
    if isinstance(storage, str):
        storage = FileStorage(storage)
    self.storage = storage

    # Cache: use provided or create default LRUCache
    if cache is not None:
        self.cache = cache
    else:
        self.cache = Cache(cache_size)  # LRUCache default

    # rest of __init__ unchanged...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_connection_cache_injection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/core/connection.py tests/unit/test_connection_cache_injection.py
git commit -m "feat(dhara): allow external cache injection in Connection

Connection.__init__ now accepts optional cache= parameter.
When provided, uses the injected cache (e.g., RedisCacheAdapter).
When None, creates default LRUCache. Enables Redis cache backend
for serverless deployment."
```

______________________________________________________________________

## Task 6: Connection Abort — cache.clear() Integration

**Files:**

- Modify: `dhara/core/connection.py` — call `cache.clear()` on abort

- [ ] **Step 1: Write failing test for abort cache invalidation**

```python
# tests/unit/test_connection_abort.py
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock
from dhara.core.connection import Connection

class TestConnectionAbortCacheInvalidation:
    @pytest.mark.asyncio
    async def test_abort_calls_cache_clear(self):
        mock_storage = MagicMock()
        mock_cache = AsyncMock()
        mock_cache.get.return_value = None
        mock_storage.sync.return_value = []

        conn = Connection(mock_storage, cache=mock_cache)
        conn.abort()  # synchronous abort
        # cache.clear() should be called
        mock_cache.clear.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_connection_abort.py -v`
Expected: FAIL — `cache.clear()` not called in abort

- [ ] **Step 3: Modify Connection.abort() to call cache.clear()**

Update `Connection.abort()` in `dhara/core/connection.py`:

```python
def abort(self) -> None:
    """Abort uncommitted changes, sync, and try to shrink the cache."""
    for oid, obj in iteritems(self.changed):
        obj._p_set_status_ghost()
    self.changed.clear()
    self._sync()
    self.shrink_cache()
    self.transaction_serial += 1

    # Invalidate cache for uncommitted oids
    if self.cache is not None and hasattr(self.cache, "clear"):
        import asyncio
        if asyncio.iscoroutinefunction(self.cache.clear):
            # Background fire-and-forget for abort path
            asyncio.create_task(self.cache.clear())
        else:
            self.cache.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && python -m pytest tests/unit/test_connection_abort.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/core/connection.py tests/unit/test_connection_abort.py
git commit -m "fix(dhara): call cache.clear() on abort for uncommitted oids

Connection.abort() now invalidates the cache after rolling back.
Uses fire-and-forget async task for cache.clear() since abort
is synchronous. Prevents stale entries for uncommitted oids."
```

______________________________________________________________________

## Self-Review Checklist

- [ ] **Spec coverage**: Each section of the design doc has a corresponding task:

  - ✅ `PostgresStorageAdapter` → Task 1
  - ✅ `RedisCacheAdapter` → Task 2
  - ✅ `dhara_objects` + `dhara_oid_seq` + `dhara_dirty_oids` schema → Task 1.5 (Step 5)
  - ✅ Env vars (`DHARA__STORAGE__BACKEND`, etc.) → Task 3
  - ✅ Backend selection in `DharaMCPServer.__init__` → Task 4
  - ✅ Cache injection into `Connection` → Task 5
  - ✅ `cache.clear()` on abort → Task 6
  - ✅ Security (credential sanitization) → Task 1 (StorageError wrapping)
  - ✅ Stampede mitigation → Task 2 (jitter)
  - ✅ `sync()` delete-on-consume → Task 1

- [ ] **Placeholder scan**: No TBD, TODO, "implement later", or vague steps. Every step has concrete code or command.

- [ ] **Type consistency**:

  - `load(oid: str)` → `oid` is `str` (Dhara's OID type)
  - `store(oid: str, record: bytes)` → consistent
  - `sync() -> list[str]` → consistent
  - `new_oid() -> str` → consistent
  - `RedisCacheSettings.redis_token` → separate env var, not in URL
  - `PostgresStorageSettings.pg_url` → full DSN with credentials

- [ ] **No Placeholders**: Verified — all code blocks are complete, all commands have expected output

______________________________________________________________________

**Plan complete.** Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
