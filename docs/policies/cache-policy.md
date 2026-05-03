# Cache Policy

**Version**: 1.0.0
**Last Updated**: 2026-04-05
**Scope**: All caching in the Mahavishnu codebase

## Overview

Mahavishnu uses multiple caching layers to reduce latency and avoid redundant computation. Caches are spread across core infrastructure, MCP tools, ingesters, and pool management. This document catalogs every cache, defines TTL defaults, and specifies invalidation rules.

## Cache Tiers

### L1 — In-Memory (Process-Local)

Fastest tier. Lives in the Python process's address space. Lost on restart.

| Cache | Location | Max Size | TTL | Eviction | Key Format |
|-------|----------|----------|-----|----------|------------|
| LRUCache (generic) | `core/cache_manager.py:160` | 1,000 | Per-entry | LRU | `str` |
| EmbeddingCache L1 | `core/embedding_cache.py:321` | 50,000 | None (managed by L2) | LRU | SHA-256 hash of text + model version |
| ResolutionCache | `core/adapter_registry.py:167` | Unbounded | 300s | TTL expiry | `domain:key:cap1,cap2` |
| AdapterDiscovery | `core/adapter_discovery.py:258` | Unbounded | 300s | TTL expiry | `domain` / `capability` |
| CrossRepoBlocker | `core/cross_repo_blocker.py:157-158` | Unbounded | None | Manual | `task_id` |
| Tree-sitter parse cache | `mcp/tools/treesitter_tools.py:25` | Configurable | None | Content-hash | File content SHA-256 |
| Pool search cache | `pools/memory_aggregator.py:146` | Unbounded | None | Manual clear | `query:limit` |
| OTel embedding cache | `ingesters/otel_ingester.py:460` | Configurable | None | FIFO | Raw content string |
| Content ingester | `ingesters/content_ingester.py:917` | Unbounded | Process lifetime | `@lru_cache` | Function args |

### L2 — SQLite (Persistent)

Survives restarts. Shared across sessions.

| Cache | Location | TTL | Invalidation |
|-------|----------|-----|-------------|
| EventBus events | `core/event_bus.py` (SQLite) | Permanent | Manual delete |
| Tool version registry | `mcp/tool_versions.py` | Permanent | Version bump |
| Mahavishnu settings | `core/paths.py` | Permanent | File modification |

### L3 — Redis (Distributed)

Optional backend. Only active when Redis is configured. Falls back to L1 when unavailable.

| Cache | Location | Max Size | TTL | Eviction |
|-------|----------|----------|-----|----------|
| EmbeddingCache L2 | `core/embedding_cache.py` | 1M+ | 86,400s (24h) ± 20% jitter | Redis TTL |
| CacheManager Redis | `core/cache_manager.py` | Configurable | Per-entry | Redis TTL |

## TTL Defaults

| Cache Type | Default TTL | Rationale |
|-----------|-------------|-----------|
| Adapter resolution | 300s (5 min) | Adapters don't change during a session |
| Adapter discovery | 300s (5 min) | Same as above |
| Embedding L2 (Redis) | 86,400s (24h) ± 20% jitter | Embeddings are stable; jitter prevents thundering herd |
| Embedding L1 (memory) | None (bounded by LRU) | Trust L2 TTL, let LRU manage memory |
| Content ingester | Process lifetime | `@lru_cache` — cleared on restart |
| Tree-sitter parse | None (content-hash) | Invalidated when file content changes |
| Pool search | None (manual) | Cleared on `clear_cache()` call |
| OTel embeddings | None (FIFO) | Bounded by `cache_size` config |

## Invalidation Rules

### Automatic Invalidation

| Trigger | What Gets Invalidated |
|---------|-----------------------|
| Model version bump | EmbeddingCache (via key prefix) |
| Content-hash change | Tree-sitter parse cache |
| TTL expiry | ResolutionCache, AdapterDiscovery, Redis entries |
| LRU eviction | LRUCache, EmbeddingCache L1 |
| Process restart | All L1 caches |
| `clear_cache()` call | Pool search cache, all via CacheManager |

### Manual Invalidation

| Method | Location | Scope |
|--------|----------|-------|
| `cache.invalidate_cache()` | `core/adapter_registry.py:618` | All adapter caches |
| `cache.clear_namespace(ns)` | `core/cache_manager.py:462` | Single namespace |
| `cache.invalidate_pattern(ns, pat)` | `core/cache_manager.py:479` | Pattern within namespace |
| `aggregator.clear_cache()` | `pools/memory_aggregator.py:574` | Pool search cache |
| `treesitter_clear_cache()` | MCP tool | Tree-sitter parse cache |

### Missing Invalidation (Known Gaps)

1. **CrossRepoBlocker** (`core/cross_repo_blocker.py:157-158`): ~~\_chain_cache and \_blocker_cache have no TTL or size limit~~ **FIXED (I11-2)** — 1-hour TTL added via `(value, timestamp)` tuples
1. **OTel embedding cache** (`ingesters/otel_ingester.py:460`): Uses FIFO eviction but no TTL — stale embeddings served indefinitely until capacity pressure
1. **Content ingester** (`ingesters/content_ingester.py:917`): ~~`@lru_cache` with no maxsize~~ **FIXED (I11-2)** — `maxsize=512` applied
1. **Pool search cache** (`pools/memory_aggregator.py:146`): ~~No TTL, entries cached indefinitely~~ **ALREADY HAD TTL** — 5-minute `CACHE_TTL` enforced on read (verified I11-2)

## Cache Key Construction

| Cache | Key Strategy | Collision Risk |
|-------|-------------|----------------|
| CacheManager | `namespace:identifier[:suffix]` | Low (structured keys) |
| EmbeddingCache | SHA-256(text + model_version) | Negligible |
| ResolutionCache | `domain:key:cap1,cap2` | Low (sorted capabilities) |
| AdapterDiscovery | Domain or capability string | Low |
| Tree-sitter | SHA-256(file content) | Negligible |
| Pool search | `query:limit` | Medium (different queries can collide on short limit) |

## Observability

### Available Metrics

| Cache | Hit/Miss Tracking | Stats Method |
|-------|-------------------|-------------|
| CacheManager (LRU) | ✅ | `CacheStats.to_dict()` — hits, misses, evictions, hit_rate |
| EmbeddingCache | ✅ | Prometheus metrics exposed via `core/embedding_cache.py` |
| Tree-sitter | ✅ | `treesitter_cache_stats` MCP tool |
| Pool search | ✅ | `MemoryAggregator.get_cache_stats()` — hits, size, hit_rate |
| AdapterResolution | ⚠️ | Debug logging only |
| CrossRepoBlocker | ❌ | None |
| OTel embeddings | ❌ | None |
| Content ingester | ❌ | None |

### Recommended Monitoring

```python
# From CacheManager
stats = cache_manager.get_stats()
print(f"Hit rate: {stats.hit_rate():.1%}")

# From EmbeddingCache
l1_stats = embedding_cache.get_l1_stats()
l2_stats = embedding_cache.get_l2_stats()

# From tree-sitter
stats = await treesitter_cache_stats()
```

## Memory Limits

| Cache | Default Max | Risk if Exceeded |
|-------|------------|-----------------|
| LRUCache | 1,000 entries | Configurable at construction |
| EmbeddingCache L1 | 50,000 entries | ~500MB at 10KB/entry — safe for most deployments |
| ResolutionCache | Unbounded | **Risk**: Can grow with unique capability combinations |
| CrossRepoBlocker | Unbounded | **Risk**: Can grow with unique task IDs |
| OTel embeddings | Configurable via `cache_size` | Bounded by config |
| Content ingester | Unbounded | **Risk**: `@lru_cache` without maxsize |

## Recommendations

### Immediate (I11-2)

1. **Add maxsize to content ingester cache** — change `@lru_cache` to `@lru_cache(maxsize=512)`
1. **Add TTL to CrossRepoBlocker caches** — entries older than 1 hour should be evicted
1. **Add TTL to pool search cache** — 5-minute TTL would prevent stale aggregation results

### Medium-term (I11-3)

4. **Unify cache stats reporting** — all caches should expose hit/miss/eviction via the same interface
1. **Add Prometheus metrics** for caches that only have debug logging (adapter resolution)
1. **Add cache health check** to the monitoring dashboard

### Long-term

7. **Consider a unified cache abstraction** — `CacheManager` already provides this; migrate ad-hoc caches to use it
1. **Evaluate Redis for adapter metadata** — currently in-memory only, lost on restart
