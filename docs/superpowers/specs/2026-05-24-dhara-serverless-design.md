# Dhara Serverless Architecture — Design Specification

**Date**: 2026-05-24
**Status**: `draft`
**Scope**: Make Dhara runnable in serverless environments by replacing fcntl file locks and in-memory LRU cache with Postgres + Redis equivalents

______________________________________________________________________

## Context

Dhara has four serverless blockers:

| Blocker | Cause | Impact |
|---------|-------|--------|
| fcntl file locks | `dhara/file.py` uses `fcntl.flock()` on local files | Incompatible with Lambda/cloud filesystems |
| Hardcoded FileStorage | `DharaMCPServer.__init__` instantiates `FileStorage` directly | No cloud primary storage adapter |
| In-memory LRU cache | `Connection` uses `OrderedDict`-based LRU in-process | Lost between serverless invocations |
| Cloud adapters are backup-only | Backup adapters (S3/GCS/Azure) implement blob interface, not `Storage` | Wrong abstraction for primary storage |

This design addresses all four by introducing two swappable backends.

______________________________________________________________________

## Goals

1. Dhara runs serverless (Neon cloud Postgres) without file locks or in-memory state loss
1. Local dev works against existing Homebrew PostgreSQL + pgvector (no Docker)
1. Same connection string pattern locally vs deployed (just swap host/creds)
1. Cache survives cold-starts via Redis with TTL-based LRU eviction
1. `Storage` and `Cache` interfaces are swappable via env vars — no code changes between modes

______________________________________________________________________

## Non-Goals

- Zero-downtime migration of existing Dhara data (separate migration plan)
- Horizontal scaling via multi-region Neon (future work)
- Replacing the pack file format — Dhara's object graph serialization stays as-is

______________________________________________________________________

## Architecture

### Backend Selection

```
DHARA__STORAGE__BACKEND   →  file | postgres
DHARA__CACHE__BACKEND     →  memory | redis
```

Both have sane defaults: `file` + `memory` when env vars are unset (current behavior).

### Storage Interface

Dhara's `Storage` abstract interface (`dhara/storage/base.py`) requires:

```
load(oid: int | str) → bytes  # raises KeyError if not found (not None)
begin() → None
store(oid: int | str, data: bytes) → None
end(commit: bool = True) → None  # commit=True commits, False rolls back
sync() → list[int]  # dirty oids consumed and deleted
new_oid() → int
close() → None
```

**Semantic notes**:

- `load()` raises `KeyError` when oid not found — adapter must implement this, not return `None`
- OIDs stored as `int` in Postgres; Dhara's `int8_to_str()` conversion happens at the `Connection` layer, not the adapter
- `end(commit=False)` rolls back the transaction — triggers cache invalidation for uncommitted oids
- `pack()` / `get_packer()` not implemented in Phase 1 — defragmentation is out of scope for serverless path
- `store()` without preceding `begin()` raises `RuntimeError` — enforces transaction boundary discipline

`PostgresStorageAdapter` implements this using asyncpg:

- `begin()` → `asyncpg.transaction()`
- `store(oid, data)` → `INSERT INTO dhara_objects (oid, data) VALUES ($1, $2) ON CONFLICT (oid) DO UPDATE SET data = $2` + `INSERT INTO dhara_dirty_oids (oid) VALUES ($1)` in same transaction
- `end(commit=True)` → `COMMIT`; `end(commit=False)` → `ROLLBACK`
- `sync()` → `SELECT oid FROM dhara_dirty_oids ORDER BY marked_at` then `DELETE FROM dhara_dirty_oids WHERE oid = ANY($1)` atomically
- `new_oid()` → `SELECT nextval('dhara_oid_seq')`

**Transaction recovery**: If `end()` raises after in-memory objects have been marked `_p_set_status_saved()`, the Postgres transaction rolls back but the in-memory state is already correct — Dhara's `Connection.abort()` clears the transaction context without marking objects saved. The adapter propagates the commit error; caller invokes `abort()` to unwind correctly.

**Error handling**:

- `store()` without `begin()`: raises `RuntimeError("store() called outside transaction")`
- Connection failure mid-transaction: asyncpg rolls back automatically; adapter re-raises as `StorageError`
- `load()` on uncommitted oid: returns in-transaction state (read-your-own-uncommitted semantics)

### Cache Interface

Dhara's `Connection` creates a cache at init time. The current `LRUCache` implements:

```
cache.get(oid) → object | None
cache.set(oid, obj) → None
cache.shrink(limit: int | None = None) → None  # evicts LRU entries
cache.clear() → None  # used after abort() to invalidate uncommitted oids
```

**`RedisCache`** wraps a Redis client with TTL-based expiration:

- `cache.get(oid)` → `GET dhara:cache:{oid}`, deserialize JSON. On Redis unavailable: log warning, return `None` (graceful degradation — cache miss falls through to Postgres)
- `cache.set(oid, obj)` → `SET dhara:cache:{oid} <json> EX <ttl>`, where TTL = `DHARA__CACHE__TTL` (default 3600)
- `cache.shrink(limit)` → **not implemented via TTL** (see below)
- `cache.clear()` → `DEL dhara:cache:{oid}` for each uncommitted oid — called by `Connection.abort()` to invalidate oids from the current transaction

**Critical: `shrink()` vs `clear()` semantics**

Dhara calls `cache.shrink(limit)` to enforce a memory cap (LRU eviction when size exceeds limit). Redis TTL handles **time-based** expiration but not **capacity-based** eviction. Two approaches:

1. **TTL-only (Phase 1)**: `cache.shrink()` becomes a no-op. Capacity is controlled by TTL — objects expire after `DHARA__CACHE__TTL` seconds. Callers that depend on `shrink(limit)` for memory management see different behavior (time-based vs count-based). Document as a behavioral change.

1. **Hybrid (Phase 2)**: Track approximate cache size in a Redis hash (`dhara:cache:size` as `HINCRBY`) and call `LRANGE` + `DEL` to enforce a count limit on `shrink()`. More complex but preserves exact LRU semantics.

**Decision**: Phase 1 uses TTL-only. `shrink()` becomes a no-op. Callers using `shrink()` for memory management must adapt.

**Abort invalidation**: When `end(commit=False)` is called, `Connection.abort()` invokes `cache.clear()` to remove all oids from the current transaction. This is a synchronous `DEL` per oid — not TTL-based. The dirty oids are known at abort time (tracked in-memory by `Connection`), so explicit deletion is correct.

**Cold-start stampede mitigation**: On cache miss, a random jitter of `0–500ms` is applied before falling through to Postgres to reduce concurrent read pressure. Configurable via `DHARA__CACHE__STAMPEDE_JITTER_MS` (default 0, i.e., disabled). This is only applied when Redis is available but cold.

### Object Graph Storage (Postgres)

Dhara serializes objects to pack files. Moving to Postgres requires mapping pack semantics to rows:

```sql
CREATE TABLE IF NOT EXISTS dhara_objects (
    oid BIGINT PRIMARY KEY,
    data BYTEA NOT NULL
);

-- Atomic OID generation via sequence (no singleton row bottleneck)
CREATE SEQUENCE dhara_oid_seq;

-- Change tracking for sync()
CREATE TABLE IF NOT EXISTS dhara_dirty_oids (
    oid BIGINT NOT NULL,
    marked_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON dhara_dirty_oids (marked_at);
```

**OID generation**: `new_oid()` calls `nextval('dhara_oid_seq')` — fully atomic, no singleton row contention.

**Dirty OID lifecycle** (explicit):

1. `store(oid, data)` → inserts into `dhara_objects` + inserts into `dhara_dirty_oids` in same transaction
1. `end()` → commits transaction (dirty markers persist)
1. `sync()` → `SELECT oid FROM dhara_dirty_oids ORDER BY marked_at` → returns dirty set → `DELETE FROM dhara_dirty_oids WHERE oid = ANY($1)` (single statement, reaping done in same query pass to avoid race condition)
1. If process crashes after `end()` but before `sync()`, dirty entries remain — next `sync()` call picks them up. This is acceptable for Dhara's idempotent semantics.

**Note**: `updated_at` column removed — it is not read by any `Storage` interface method and adds write overhead.

### Locking

Postgres handles locking natively — no fcntl needed. Concurrent transactions use `SELECT ... FOR UPDATE` when needed. Dhara's file-based `obtain_lock()` / `release_lock()` are replaced by Postgres transaction isolation.

### Environment Variables

```bash
# Storage backend (file=current, postgres=serverless)
DHARA__STORAGE__BACKEND=postgres

# Postgres connection (same driver works for Homebrew local and Neon cloud)
DHARA__STORAGE__PG_URL=postgresql://user:pass@localhost:5432/dhara
# Or for Neon:
DHARA__STORAGE__PG_URL=postgresql://user:pass@ep-xxx.neon.tech/dhara?sslmode=require

# Cache backend (memory=current, redis=serverless)
DHARA__CACHE__BACKEND=redis

# Redis URL (for serverless cache)
# NOTE: Token must be set via REDIS_TOKEN env var, NOT embedded in URL
# Wrong:  redis://token@xxx.upstash.io:6379  ← token appears in logs
# Right:  DHARA__CACHE__REDIS_URL=redis://xxx.upstash.io:6379
#         DHARA__CACHE__REDIS_TOKEN=your_token_here
DHARA__CACHE__REDIS_URL=redis://localhost:6379
DHARA__CACHE__REDIS_TOKEN=           # set separately, never in URL

# TTL for cached objects (seconds, default 3600)
DHARA__CACHE__TTL=3600

# Cold-start stampede jitter (ms, default 0=disabled)
DHARA__CACHE__STAMPEDE_JITTER_MS=0
```

**Security note**: The Redis token must **never** appear in the URL. The `DHARA__CACHE__REDIS_TOKEN` env var is read by the client directly and used as password authentication. This prevents tokens from appearing in logs, error messages, or connection strings. Similarly, Postgres credentials in `DHARA__STORAGE__PG_URL` are read-only — error messages must never echo the full URL. The adapter must sanitize exception messages: wrap connection errors in `StorageError("connection failed")` without including the URL, hostname, or credentials in the message text. The underlying error can be logged to a private audit log but must not propagate to callers.

______________________________________________________________________

## Local vs Deployment Behavior

| Scenario | Storage | Cache | Connection |
|----------|---------|-------|-----------|
| Local dev (no env vars) | `FileStorage` | `LRUCache` in-process | unchanged |
| Local dev (Homebrew PG) | `PostgresStorageAdapter` | `LRUCache` (or Redis if set) | works directly |
| Serverless (Neon + Redis) | `PostgresStorageAdapter` | `RedisCache` | survives cold-starts |

Both local and deployed use Postgres wire protocol — the only difference is the connection string.

______________________________________________________________________

## Key Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `dhara/storage/postgres.py` | `PostgresStorageAdapter` implementing `Storage` interface |
| `dhara/cache/redis.py` | `RedisCache` implementing cache interface |
| `dhara/storage/pg_schema.sql` | SQL migration for `dhara_objects` + `dhara_oid_counter` |

### Modified Files

| File | Change |
|------|--------|
| `dhara/mcp/server_core.py` | `DharaMCPServer.__init__` — read `DHARA__STORAGE__BACKEND`, instantiate appropriate adapter |
| `dhara/core/connection.py` | `Connection.__init__` — read `DHARA__CACHE__BACKEND`, instantiate `LRUCache` or `RedisCache` |
| `dhara/config.py` | Add `DHARA__STORAGE__BACKEND`, `DHARA__STORAGE__PG_URL`, `DHARA__CACHE__BACKEND`, `DHARA__CACHE__REDIS_URL`, `DHARA__CACHE__TTL` fields |

______________________________________________________________________

## Open Questions

1. **Pack file migration**: Existing Dhara installations have pack files on disk. Is zero-downtime migration needed, or is a fresh `dhara_objects` init acceptable for the serverless path?

1. **Postgres schema ownership**: The `dhara_objects` table should be created automatically on first startup if it doesn't exist. Should this be a migration ("upgrade from file to Postgres") or a fresh init ("start with Postgres")?

1. **Connection pool sizing**: Neon has connection limits (e.g., 600 connections on paid tier). Dhara opens one Postgres connection per `Connection` instance. How many concurrent connections does Dhara need in the serverless scenario?

______________________________________________________________________

## Testing Strategy

1. **Local Postgres test**: Start Dhara against local Homebrew PostgreSQL — verify all CRUD operations on objects work
1. **Redis cache test**: Set `DHARA__CACHE__BACKEND=redis` and verify cache survives process restart
1. **Cold-start test**: Kill and restart Dhara process, verify Redis cache is still populated
1. **Neon smoke test**: Point at Neon connection string (staging), run basic put/get tests
1. **Degradation test**: With `DHARA__CACHE__BACKEND=redis` but Redis unavailable, verify graceful fallback to no cache (not crashing)

______________________________________________________________________

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Postgres WAL overhead for small writes | Low | `asyncpg` batches; Dhara's write patterns are batched in `end()` |
| Redis cache invalidation on abort | Low | `cache.clear()` called by `Connection.abort()` with explicit per-oid `DEL` |
| Neon connection limit exhaustion | Medium | Use Neon Branch per serverless instance, or PgBouncer for connection pooling |
| Object graph pack format not Postgres-native | Unknown | May need custom serialization layer (defer if not needed for Phase 1) |
| Cold-start cache stampede exhausting Postgres connections | Medium | `DHARA__CACHE__STAMPEDE_JITTER_MS` adds random jitter on cold cache miss |
| `dhara_dirty_oids` grows if `sync()` is never called | Low | `sync()` deletes consumed entries; unconsumed entries are harmless for read-mostly workloads |
| TTL-based eviction ≠ LRU capacity eviction (behavioral change) | Medium | Document as Phase 1 limitation; `shrink()` becomes no-op |

______________________________________________________________________

## Probability of Success

**~80%** (revised from ~60% after fixes). Core swap (FileStorage → PostgresStorageAdapter, LRU → RedisCache) is well-bounded. Addressed in this revision:

- ✅ `sync()` dirty tracking lifecycle explicit (insert on store, delete-on-consume in sync)
- ✅ `cache.clear()` for abort invalidation (not TTL)
- ✅ Transaction recovery semantics clarified
- ✅ OID type mismatch resolved (int in Postgres, str conversion at Connection layer)
- ✅ Redis token security fixed (separate env var, not in URL)
- ✅ Neon credential exposure mitigated (error logs suppress URL)
- ✅ `dhara_oid_counter` singleton replaced with `dhara_oid_seq` sequence
- ✅ Cold-start stampede mitigation added (`DHARA__CACHE__STAMPEDE_JITTER_MS`)
- ⚠️ `shrink()` behavioral change documented (TTL-only, not capacity-based LRU)
- ⚠️ Pack file migration still open (acceptable — fresh init required for Phase 1)
