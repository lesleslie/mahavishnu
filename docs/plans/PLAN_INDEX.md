# Plan Index

**Date:** 2026-04-02  
**Purpose:** Active plan ordering, dependencies, and supersession map for execution.

## External Review

For third-party review workflow and required reading order, use:

- `docs/plans/REVIEW_PACKET_2026-04-02.md`

## Active Execution Order

1. **Storage Consolidation And Akosha Role**
   - File: `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`
   - Status: Proposed, primary workflow anchor
   - Why first: Defines source-of-truth ownership and dependency criticality for all downstream work.

2. **Status Enum Consolidation**
   - File: `docs/plans/2026-02-20-status-enum-consolidation.md`
   - Status: Active prerequisite
   - Why second: Reduces state-model drift before broad persistence cutover.

3. **Health Check System (Design + Implementation)**
   - Files:
     - `docs/plans/2026-02-27-health-check-system-design.md`
     - `docs/plans/2026-02-27-health-check-implementation-plan.md`
   - Status: Mostly implemented, requires policy alignment
   - Required alignment: Akosha optional for core startup under consolidated storage architecture.

4. **Adaptive Router With Feedback Loops**
   - File: `docs/plans/2025-02-11-adaptive-router-feedback-loops.md`
   - Status: Partially implemented
   - Required alignment: Route metrics persistence to Mahavishnu PostgreSQL, not Dhara-default paths.

5. **Self-Improvement Implementation**
   - File: `docs/plans/2026-02-20-self-improvement-implementation.md`
   - Status: Partially implemented
   - Required alignment: Persist findings/approval/fix events in Mahavishnu PostgreSQL schemas.

6. **External Platform Integrations**
   - Status: Removed from active planning on 2026-04-04
   - Note: OpenCode/OMO/Sisyphus integration plans were explicitly abandoned and deleted.

## Reprioritized But Not Superseded

1. `docs/plans/PREFECT_ADAPTER_COMPLETION_PLAN.md`
   - Valid plan, lower priority than storage consolidation.

2. `docs/plans/TLS_IMPLEMENTATION_SUMMARY.md`
   - Historical summary with remaining ecosystem hardening tasks.
   - Not on current storage-critical path.

## Supersession Notes

1. `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md` is the current architecture authority for:
   - persistence ownership
   - Akosha role boundary
   - Session-Buddy write-path criticality

2. The following plans are **partially superseded** only where they conflict with the above:
   - `docs/plans/2025-02-11-adaptive-router-feedback-loops.md`
   - `docs/plans/2026-02-20-self-improvement-implementation.md`

3. The following are **not superseded**:
   - `docs/plans/2026-02-20-status-enum-consolidation.md`
   - `docs/plans/2026-02-27-health-check-system-design.md`
   - `docs/plans/2026-02-27-health-check-implementation-plan.md`

## Immediate Work Queue

1. ✅ Make Akosha optional in Mahavishnu startup dependency configuration and docs.
2. ✅ Finalize allowed status/priority/sync-state values and enforce `CHECK` constraints in the initial migration set.
3. ✅ Scaffold PostgreSQL + `pgvector` migration baseline.
4. ✅ Define repository interfaces for task/run/event/document/embedding persistence.
5. ✅ Implement feature-flagged cutover and rollback procedure (`dual|legacy|postgres` writes; `legacy|postgres` reads).
6. ✅ Complete enum consolidation in runtime modules still defining duplicate status enums.
7. ✅ Redirect adaptive routing metrics persistence assumptions to Mahavishnu PostgreSQL.

**Status:** All 7 items completed (2026-04-02).

**Implementation Details:**
- Item 7 implemented via `mahavishnu/core/routing_metrics_persistence.py`
- Migration: `migrations/versions/V202604021300__routing_metrics_schema.sql`
- Creates `metrics` schema with tables: `execution_records`, `adapter_stats`, `routing_decisions`, `cost_tracking`, `ab_tests`, `task_type_stats`
- Integrates with existing `ExecutionTracker` via storage_client interface

## Ownership Boundaries (Current)

1. **Mahavishnu**: source-of-truth task/run/event/search persistence.
2. **Session-Buddy**: async best-effort context memory.
3. **Akosha**: optional intelligence layer (initial scope: federated search, analytics, pattern detection).
