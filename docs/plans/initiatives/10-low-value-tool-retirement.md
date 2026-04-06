# Initiative 10: Low-Value Tool Retirement

## Metadata
- Status: `not_started`
- Owner Role: `Product + Platform`
- Target Window: `2026-05-25` to `2026-06-19`

## Outcome
Reduce operational and maintenance burden by deprecating low-value/high-failure tools.

## Work Package Checklist
- [x] `I10-1` Telemetry-based tool ranking report
- [x] `I10-2` Deprecation warnings and migration notes
- [x] `I10-3` Remove bottom 10-20% tools safely

## Dependencies
- `I4-3`, `I5-3`

## Exit Criteria
- Tool surface reduced per target
- Tool-related incidents decrease by at least `20%` over the next 30-day window
- Mean monthly maintenance tickets for removed tools drops by at least `30%`

## Risks
- User disruption from premature removals
- Missing migration guidance

## Progress Log
- 2026-04-04: Plan file created.
- 2026-04-05: I10-2 complete — deprecation warnings added to content_ingestion_tools.py, worktree_tools.py, oneiric_tools.py. Migration guide at docs/reports/deprecation-migration.md.
- 2026-04-05: I10-3 complete — removed 2 dormant modules (content_ingestion_tools.py, oneiric_tools.py). Cleaned up dead import in ingestion_cli.py, removed stale tool_versions entries, updated __init__.py comments. Worktree tools retained (consolidation deferred to v0.6.0 due to test surface). Net: -11 tools removed.
