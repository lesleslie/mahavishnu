# ADR 008: Zero-Downtime SQLite to PostgreSQL Migration

**Status**: Accepted
**Date**: 2026-02-18
**Context**: Task Orchestration Master Plan v3.0
**Related**: ADR-006 (Storage Simplification), ADR-007 (Saga Coordinator)

---

## Context

The Task Orchestration System currently uses SQLite for development (Phase 0-1). PostgreSQL is required for production scalability, concurrency, and pgvector semantic search.

### Current State (v2.0)

The Master Plan v2.0 proposed a **big bang cutover** strategy:

```
1. Stop application
2. Dump SQLite data
3. Import to PostgreSQL
4. Update connection strings
5. Start application
6. Hope nothing breaks
```

### Problems with Big Bang Cutover

During the 5-agent review council, the Architecture Reviewer identified **weak rollback plan** as a **P0 critical issue**:

- **Downtime Required**: Application unavailable during migration (could be hours for large datasets)
- **No Validation**: No way to verify data integrity before cutover
- **Risky Rollback**: If issues found, rollback is complex and error-prone
- **No Performance Testing**: Can't test PostgreSQL performance under load before cutover
- **All-or-Nothing**: Either fully migrated or fully rolled back (no gradual transition)

### Architecture Reviewer Feedback

**Score**: 4.2/5.0 (APPROVED WITH RECOMMENDATIONS)

> "Big bang database migration is the #1 cause of production outages. You need a zero-downtime migration strategy with dual-write, validation triggers, and safe rollback. Database migrations should be boring, not terrifying."

### SRE Engineer Feedback

**Score**: 6.5/10 (APPROVED WITH CONDITIONS)

> "Migration rollback triggers are incomplete. What if PostgreSQL performance degrades? What if data validation fails? You need clear rollback criteria and automated rollback triggers."

---

## Decision

Implement **zero-downtime migration** using **dual-write strategy** with 4 phases:

### Migration Phases

```
Phase 0: Pre-Migration (Preparation)
  └─ Validate migration scripts in staging
  └─ Set up PostgreSQL infrastructure
  └─ Create rollback procedures

Phase 1: Dual-Write (2 weeks)
  └─ Write to both SQLite and PostgreSQL
  └─ Read from SQLite (existing behavior)
  └─ Validate writes to PostgreSQL succeed
  └─ Monitor PostgreSQL performance

Phase 2: Dual-Read (2 weeks)
  └─ Write to both SQLite and PostgreSQL
  └─ Read from PostgreSQL (fallback to SQLite on error)
  └─ Validate read consistency between databases
  └─ Monitor PostgreSQL query performance

Phase 3: Cutover (Instant)
  └─ Write to PostgreSQL only
  └─ Read from PostgreSQL only
  └─ Remove SQLite references
  └─ Monitor for errors

Phase 4: Cleanup (1 week)
  └─ Archive SQLite database
  └─ Remove dual-write code
  └─ Update documentation
  └─ Celebrate success 🎉
```

### Phase 1: Dual-Write (2 weeks)

**Objective**: Verify PostgreSQL can handle writes without errors

**Implementation**:

```python
from mahavishnu.core.storage import DatabaseAdapter
from mahavishnu.core.migration import MigrationStatus

class DualWriteDatabaseAdapter(DatabaseAdapter):
    """
    Dual-write adapter for migration Phase 1.

    Writes to both SQLite and PostgreSQL.
    Reads from SQLite only.
    """

    def __init__(self, sqlite_db: SQLiteDB, postgresql_db: PostgreSQLDB):
        self.sqlite = sqlite_db
        self.postgresql = postgresql_db
        self.phase = MigrationStatus.DUAL_WRITE

    async def create_task(self, task_data: TaskCreateRequest) -> Task:
        """
        Create task in both databases.

        Write Order:
        1. SQLite (primary, existing behavior)
        2. PostgreSQL (secondary, for validation)

        If PostgreSQL write fails, log error but don't fail operation.
        """
        # Write to SQLite first (primary)
        task = await self.sqlite.create_task(task_data)

        # Write to PostgreSQL (secondary, best-effort)
        try:
            await self.postgresql.create_task(task_data)
            dual_write_success_total.inc(phase='dual_write', operation='create_task')
        except Exception as e:
            logger.error(f"PostgreSQL write failed during dual-write: {e}")
            dual_write_errors_total.inc(phase='dual_write', operation='create_task', error_type=type(e).__name__)

            # Check if error rate is too high (rollback trigger)
            if await self._is_error_rate_too_high():
                logger.critical("Dual-write error rate too high, may need to rollback")
                await self._alert_ops_team("Dual-write error rate critical")

        return task

    async def get_task(self, task_id: int) -> Task | None:
        """
        Read from SQLite only (existing behavior).

        PostgreSQL not used for reads in Phase 1.
        """
        return await self.sqlite.get_task(task_id)

    async def _is_error_rate_too_high(self) -> bool:
        """
        Check if dual-write error rate exceeds threshold.

        Rollback Trigger: > 5% error rate over 5-minute window
        """
        error_rate = await self._calculate_error_rate(window_minutes=5)
        return error_rate > 0.05  # 5% threshold
```

**Validation Checks**:

```python
async def validate_dual_write_phase() -> MigrationValidationResult:
    """
    Validate dual-write phase is ready to proceed to dual-read.

    Checks:
    1. PostgreSQL write success rate > 99%
    2. PostgreSQL write latency p95 < 100ms
    3. No data corruption (row count matches)
    4. No critical errors in logs
    """
    # Check 1: Write success rate
    total_writes = dual_write_success_total.get(phase='dual_write')._value.get()
    failed_writes = dual_write_errors_total.get(phase='dual-write')._value.get()
    success_rate = (total_writes - failed_writes) / total_writes if total_writes > 0 else 0

    if success_rate < 0.99:
        return MigrationValidationResult(
            status="failed",
            reason=f"PostgreSQL write success rate {success_rate:.2%} < 99%",
        )

    # Check 2: Write latency
    write_latency = histogram_quantile(0.95, postgresql_write_duration_seconds)
    if write_latency > 0.1:  # 100ms
        return MigrationValidationResult(
            status="failed",
            reason=f"PostgreSQL write latency p95 {write_latency}s > 100ms",
        )

    # Check 3: Data integrity
    sqlite_count = await sqlite.execute("SELECT COUNT(*) FROM tasks")
    postgresql_count = await postgresql.execute("SELECT COUNT(*) FROM tasks")

    if sqlite_count != postgresql_count:
        return MigrationValidationResult(
            status="failed",
            reason=f"Row count mismatch: SQLite={sqlite_count}, PostgreSQL={postgresql_count}",
        )

    # All checks passed
    return MigrationValidationResult(status="passed")
```

### Phase 2: Dual-Read (2 weeks)

**Objective**: Verify PostgreSQL can handle reads without errors

**Implementation**:

```python
class DualReadDatabaseAdapter(DatabaseAdapter):
    """
    Dual-read adapter for migration Phase 2.

    Writes to both SQLite and PostgreSQL.
    Reads from PostgreSQL (fallback to SQLite on error).
    """

    def __init__(self, sqlite_db: SQLiteDB, postgresql_db: PostgreSQLDB):
        self.sqlite = sqlite_db
        self.postgresql = postgresql_db
        self.phase = MigrationStatus.DUAL_READ

    async def get_task(self, task_id: int) -> Task | None:
        """
        Read from PostgreSQL (fallback to SQLite on error).

        Fallback Strategy:
        1. Try PostgreSQL first
        2. On error, log and fallback to SQLite
        3. Increment fallback counter for monitoring
        """
        try:
            task = await self.postgresql.get_task(task_id)
            dual_read_success_total.inc(phase='dual_read', operation='get_task')
            return task
        except Exception as e:
            logger.warning(f"PostgreSQL read failed, falling back to SQLite: {e}")
            dual_read_fallbacks_total.inc(phase='dual_read', operation='get_task', error_type=type(e).__name__)

            # Fallback to SQLite
            task = await self.sqlite.get_task(task_id)

            # Check if fallback rate is too high (rollback trigger)
            if await self._is_fallback_rate_too_high():
                logger.critical("Dual-read fallback rate too high, may need to rollback")
                await self._alert_ops_team("Dual-read fallback rate critical")

            return task

    async def _is_fallback_rate_too_high(self) -> bool:
        """
        Check if fallback rate exceeds threshold.

        Rollback Trigger: > 1% fallback rate over 5-minute window
        """
        fallback_rate = await self._calculate_fallback_rate(window_minutes=5)
        return fallback_rate > 0.01  # 1% threshold
```

**Validation Checks**:

```python
async def validate_dual_read_phase() -> MigrationValidationResult:
    """
    Validate dual-read phase is ready to proceed to cutover.

    Checks:
    1. PostgreSQL read success rate > 99.9%
    2. PostgreSQL read latency p95 < 50ms (better than SQLite)
    3. Fallback rate < 1%
    4. Data consistency (hash comparison)
    5. No performance regression
    """
    # Check 1: Read success rate
    total_reads = dual_read_success_total.get(phase='dual_read')._value.get()
    fallbacks = dual_read_fallbacks_total.get(phase='dual_read')._value.get()
    success_rate = (total_reads - fallbacks) / total_reads if total_reads > 0 else 0

    if success_rate < 0.999:
        return MigrationValidationResult(
            status="failed",
            reason=f"PostgreSQL read success rate {success_rate:.2%} < 99.9%",
        )

    # Check 2: Read latency
    read_latency = histogram_quantile(0.95, postgresql_read_duration_seconds)
    sqlite_latency = histogram_quantile(0.95, sqlite_read_duration_seconds)

    if read_latency > sqlite_latency:
        return MigrationValidationResult(
            status="failed",
            reason=f"PostgreSQL read latency p95 {read_latency}s > SQLite {sqlite_latency}s",
        )

    # Check 3: Fallback rate
    fallback_rate = fallbacks / total_reads if total_reads > 0 else 0
    if fallback_rate > 0.01:
        return MigrationValidationResult(
            status="failed",
            reason=f"Fallback rate {fallback_rate:.2%} > 1%",
        )

    # Check 4: Data consistency (hash comparison)
    sqlite_hash = await self._calculate_table_hash(sqlite, "tasks")
    postgresql_hash = await self._calculate_table_hash(postgresql, "tasks")

    if sqlite_hash != postgresql_hash:
        return MigrationValidationResult(
            status="failed",
            reason=f"Data hash mismatch: SQLite={sqlite_hash}, PostgreSQL={postgresql_hash}",
        )

    # All checks passed
    return MigrationValidationResult(status="passed")
```

### Phase 3: Cutover (Instant)

**Objective**: Switch to PostgreSQL exclusively

**Implementation**:

```python
class PostgreSQLDatabaseAdapter(DatabaseAdapter):
    """
    PostgreSQL-only adapter for migration Phase 3+.

    Writes to PostgreSQL only.
    Reads from PostgreSQL only.
    """

    def __init__(self, postgresql_db: PostgreSQLDB):
        self.postgresql = postgresql_db
        self.phase = MigrationStatus.CUTOVER_COMPLETE

    async def create_task(self, task_data: TaskCreateRequest) -> Task:
        """Create task in PostgreSQL only."""
        return await self.postgresql.create_task(task_data)

    async def get_task(self, task_id: int) -> Task | None:
        """Read from PostgreSQL only."""
        return await self.postgresql.get_task(task_id)
```

**Cutover Process**:

```python
async def execute_cutover() -> CutoverResult:
    """
    Execute instant cutover from dual-read to PostgreSQL-only.

    Process:
    1. Run final validation checks
    2. Update configuration to use PostgreSQL adapter
    3. Reload application (zero-downtime reload)
    4. Monitor for errors
    5. Rollback if critical errors detected
    """
    # Step 1: Final validation
    validation = await validate_dual_read_phase()
    if validation.status != "passed":
        logger.critical(f"Pre-cutover validation failed: {validation.reason}")
        return CutoverResult(status="failed", reason=validation.reason)

    # Step 2: Update configuration
    await update_database_config(adapter="postgresql")

    # Step 3: Reload application (zero-downtime)
    await reload_application_gracefully()

    # Step 4: Monitor for 5 minutes
    await asyncio.sleep(300)  # 5 minutes

    # Step 5: Check for errors
    if await check_for_critical_errors():
        logger.critical("Critical errors detected after cutover, initiating rollback")
        await execute_rollback()
        return CutoverResult(status="rolled_back", reason="Critical errors detected")

    # Cutover successful
    await notify_ops_team("Database migration cutover completed successfully")
    return CutoverResult(status="success")
```

### Rollback Triggers

**Automated Rollback Conditions**:

1. **Data Validation Failure**: Row count mismatch or hash mismatch
2. **Performance Regression**: PostgreSQL latency p95 > 2x SQLite latency
3. **High Error Rate**: > 5% dual-write error rate or > 1% dual-read fallback rate
4. **Critical Errors**: Database connection failures, timeout spikes
5. **Manual Trigger**: Ops team can trigger rollback via command

**Rollback Process**:

```python
async def execute_rollback() -> RollbackResult:
    """
    Execute rollback from current phase to previous phase.

    Rollback Paths:
    - Dual-Write → Phase 0 (Pre-Migration)
    - Dual-Read → Dual-Write
    - Cutover → Dual-Read
    """
    current_phase = await get_current_migration_phase()

    if current_phase == MigrationStatus.DUAL_WRITE:
        # Rollback to Phase 0 (stop dual-write)
        await update_database_config(adapter="sqlite")
        await reload_application_gracefully()
        return RollbackResult(status="success", rolled_back_to="Phase 0")

    elif current_phase == MigrationStatus.DUAL_READ:
        # Rollback to Dual-Write
        await update_database_config(adapter="dual_write")
        await reload_application_gracefully()
        return RollbackResult(status="success", rolled_back_to="Phase 1 (Dual-Write)")

    elif current_phase == MigrationStatus.CUTOVER_COMPLETE:
        # Rollback to Dual-Read (emergency rollback)
        await update_database_config(adapter="dual_read")
        await reload_application_gracefully()
        return RollbackResult(status="success", rolled_back_to="Phase 2 (Dual-Read)")

    return RollbackResult(status="failed", reason="Unknown phase")
```

---

## Alternatives Considered

### Alternative 1: Big Bang Cutover (REJECTED)

**Pros**:
- Simpler implementation
- Faster migration (no dual-write period)

**Cons**:
- **Downtime required** (hours for large datasets)
- **No validation** before cutover
- **Risky rollback** (complex and error-prone)
- **No performance testing** under load

**Decision**: Unacceptable for production system. Users expect 24/7 availability.

### Alternative 2: Maintenance Window (REJECTED)

**Pros**:
- Safer than big bang cutover (have time to fix issues)
- Less pressure on ops team

**Cons**:
- **Still causes downtime** (users expect 24/7 availability)
- **Scheduling complexity** (global users, different timezones)
- **Extended downtime** if issues found

**Decision**: Modern SaaS should not require maintenance windows for database migrations.

### Alternative 3: Dual-Write Migration (ACCEPTED)

**Pros**:
- **Zero downtime** (application always available)
- **Safe rollback** (can rollback to previous phase)
- **Validation** (verify data integrity before cutover)
- **Performance testing** (test PostgreSQL under load)
- **Gradual transition** (2 weeks per phase = 4 weeks total)

**Cons**:
- More complex implementation
- Longer migration timeline (4 weeks vs 1 day)
- Dual-write doubles database I/O during Phase 1-2

**Decision**: Required for production system with 24/7 availability expectations.

---

## Consequences

### Positive Impacts

1. **Zero Downtime**: Users experience no interruption during migration
2. **Safe Rollback**: Can rollback to previous phase if issues found
3. **Data Validation**: Verify data integrity at each phase
4. **Performance Testing**: Test PostgreSQL under real load before cutover
5. **Gradual Transition**: 4 weeks to identify and fix issues

### Negative Impacts

1. **Complexity**: More complex than big bang cutover
2. **Timeline**: 4 weeks migration timeline (vs 1 day for big bang)
3. **Dual-Write Overhead**: Doubles database I/O during Phase 1-2
4. **Code Complexity**: Need to maintain multiple database adapters

### Risks

1. **Dual-Write Failures**: What if PostgreSQL write fails during Phase 1?
   - **Severity**: Medium
   - **Mitigation**: Log errors but don't fail operation (best-effort)
   - **Mitigation**: Alert on high error rate (> 5%)

2. **Data Inconsistency**: What if databases diverge during Phase 1-2?
   - **Severity**: High
   - **Mitigation**: Hash comparison validation checks
   - **Mitigation**: Automated rollback on data mismatch

3. **Performance Degradation**: What if dual-write doubles latency?
   - **Severity**: Medium
   - **Mitigation**: Connection pooling optimization
   - **Mitigation**: Async writes (fire-and-forget for non-critical data)

4. **Rollback Failures**: What if rollback itself fails?
   - **Severity**: Critical
   - **Mitigation**: Test rollback procedures in staging
   - **Mitigation**: Ops team manual override

---

## Implementation Timeline

**Phase 1, Week 2-3**: Implement Dual-Write (7 days)

- **Day 1-2**: Dual-write adapter implementation
- **Day 3**: PostgreSQL write monitoring and alerting
- **Day 4**: Rollback trigger implementation
- **Day 5**: Testing in staging environment
- **Day 6-7**: Deploy to production, monitor for 2 weeks

**Phase 1, Week 4-5**: Dual-Read Phase (7 days)

- **Day 1**: Dual-read adapter implementation
- **Day 2**: Fallback monitoring and alerting
- **Day 3**: Data consistency validation (hash comparison)
- **Day 4**: Performance comparison testing
- **Day 5**: Deploy to production, monitor for 2 weeks

**Phase 1, Week 6**: Cutover (instant)

- **Day 1**: Final validation checks
- **Day 1**: Execute cutover (instant, during business hours)
- **Day 1-7**: Monitor for errors, be ready to rollback

**Phase 1, Week 7**: Cleanup (7 days)

- **Day 1-3**: Archive SQLite database
- **Day 4-5**: Remove dual-write code
- **Day 6-7**: Update documentation and runbooks

---

## Monitoring

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Migration phase tracking
migration_phase = Gauge(
    'migration_phase',
    'Current migration phase',
    ['phase']  # dual_write, dual_read, cutover
)

# Dual-write metrics
dual_write_success_total = Counter(
    'dual_write_success_total',
    'Total successful dual-writes',
    ['phase', 'operation']
)

dual_write_errors_total = Counter(
    'dual_write_errors_total',
    'Total dual-write errors',
    ['phase', 'operation', 'error_type']
)

# Dual-read metrics
dual_read_success_total = Counter(
    'dual_read_success_total',
    'Total successful dual-reads',
    ['phase', 'operation']
)

dual_read_fallbacks_total = Counter(
    'dual_read_fallbacks_total',
    'Total dual-read fallbacks to SQLite',
    ['phase', 'operation', 'error_type']
)

# Performance comparison
postgresql_write_duration_seconds = Histogram(
    'postgresql_write_duration_seconds',
    'PostgreSQL write latency',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0]
)

sqlite_write_duration_seconds = Histogram(
    'sqlite_write_duration_seconds',
    'SQLite write latency',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0]
)
```

### Grafana Dashboard

- **Migration Phase**: Current phase indicator
- **Write Success Rate**: Dual-write success rate by operation
- **Read Success Rate**: Dual-read success rate by operation
- **Fallback Rate**: Dual-read fallback rate by operation
- **Performance Comparison**: PostgreSQL vs SQLite latency (p50, p95, p99)
- **Data Integrity**: Row count comparison, hash comparison
- **Error Rate**: Error rate by phase and operation

---

## Related Decisions

- **ADR-006: Storage Simplification**: PostgreSQL as primary storage
- **ADR-007: Saga Coordinator**: Saga coordinator uses PostgreSQL for saga log

---

## References

- Database Migration Best Practices: https://brandur.org/migrations
- Architecture Reviewer Report (2026-02-18): Score 4.2/5.0, identified weak rollback plan as P0
- SRE Engineer Report (2026-02-18): Score 6.5/10, required rollback triggers
- Master Plan v3.0: `/docs/TASK_ORCHESTRATION_MASTER_PLAN_V3.md`

---

**END OF ADR-003**
