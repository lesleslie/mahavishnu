# Initiative 11: Cache + Tiered Retrieval Defaults

## Metadata
- Status: `complete`
- Owner Role: `Search/Infra`
- Target Window: `2026-06-01` to `2026-06-19`

## Outcome
Standardize cache and progressive retrieval behavior for predictable performance.

## Work Package Checklist
- [x] `I11-1` Cache policy doc (TTL/invalidation)
- [x] `I11-2` Implement default tiering in query paths
- [x] `I11-3` Cache observability and regression tests

## Dependencies
- `I5-1`

## Exit Criteria
- Cache hit rate `+15%`
- p95 query latency `-20%` on target flows

## Risks
- Stale data from poor invalidation rules
- Over-aggressive caching masking source issues

## Progress Log
- 2026-04-04: Plan file created.
- 2026-04-05: I11-2 complete — three fixes applied:
  - content_ingester.py: @lru_cache(maxsize=512) (was unbounded)
  - cross_repo_blocker.py: 1-hour TTL on _chain_cache and _blocker_cache
  - Pool search cache already had 5-min TTL (verified)
- 2026-04-05: I11-3 complete — cache observability and regression tests:
  - Added hit/miss counters to CrossRepoBlockerTracker (chain_cache + blocker_cache)
  - Added get_stats() and reset_stats() methods to CrossRepoBlockerTracker
  - Added aggregate_cache_health() function to cache_manager.py (cross-cache stats)
  - Regression tests: tests/unit/test_cache_observability.py (20 tests, all passing)
  - Covers: ResolutionCache, AdapterDiscoveryEngine, CrossRepoBlockerTracker, aggregate_cache_health
