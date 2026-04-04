# Initiative 11: Cache + Tiered Retrieval Defaults

## Metadata
- Status: `not_started`
- Owner Role: `Search/Infra`
- Target Window: `2026-06-01` to `2026-06-19`

## Outcome
Standardize cache and progressive retrieval behavior for predictable performance.

## Work Package Checklist
- [ ] `I11-1` Cache policy doc (TTL/invalidation)
- [ ] `I11-2` Implement default tiering in query paths
- [ ] `I11-3` Cache observability and regression tests

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
