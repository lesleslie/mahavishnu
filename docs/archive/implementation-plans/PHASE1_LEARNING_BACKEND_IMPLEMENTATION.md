# Phase 1: ORB Learning Backend Implementation

**Status**: In Progress
**Created**: 2026-02-09
**Focus**: Backend infrastructure for learning feedback loops

---

## Executive Summary

Implementing P0 backend consultant recommendations for the ORB Learning Feedback Loops system. This phase focuses on database infrastructure, data models, telemetry capture, and integration hooks.

### Scope

**In Scope:**
- Separate `LearningDatabase` class (DuckDB-based)
- Extended `ExecutionRecord` model with all consultant-recommended fields
- Composite indexes for query optimization
- Materialized views for dashboard queries
- Telemetry capture hooks in model router and pool manager
- Data migration script with upgrade/downgrade support
- Comprehensive unit tests (100% coverage target)

**Out of Scope:**
- UX/feedback capture mechanisms (Phase 2)
- Pattern extraction algorithms (Phase 2)
- Adaptive quality thresholds (Phase 3)
- User feedback UI (Phase 4)

---

## P0 Consultant Recommendations

### 1. Separate LearningDatabase Class

**Why**: Clean separation of concerns (OTel traces vs. execution analytics), independent schema optimization, easier migration and evolution.

**Implementation**: `/mahavishnu/learning/database.py`
- DuckDB-based storage (separate from OTel traces)
- Connection pooling for concurrent queries
- Optimized schema with composite indexes
- Materialized views for dashboard queries
- Async/await throughout

### 2. Extended ExecutionRecord Model

**Why**: Captures all necessary signals for auto-tuning, enables prediction accuracy tracking, supports user feedback integration.

**Implementation**: `/mahavishnu/learning/models.py`
- All consultant-recommended fields
- Pydantic validation
- Helper methods for embedding generation
- Prediction error calculation

### 3. Composite Indexes

**Why**: 10-100x query performance improvement, minimal storage overhead, enables production-scale queries.

**Implementation**: In `LearningDatabase.initialize()`
- `idx_executions_repo_task` on (repo, task_type, timestamp DESC)
- `idx_executions_tier_success` on (model_tier, success, timestamp DESC)
- `idx_executions_pool_duration` on (pool_type, success, duration_seconds)
- `idx_executions_quality_trend` on (repo, quality_score, timestamp DESC)

### 4. Materialized Views

**Why**: 50-600x faster dashboard queries, pre-computed aggregations, minimal storage overhead.

**Implementation**: In `LearningDatabase.initialize()`
- `tier_performance_mv` - per-tier performance by day
- `pool_efficiency_mv` - pool performance metrics
- `solution_success_mv` - top solutions by success rate

### 5. Telemetry Hooks

**Why**: Automatic capture of execution data without manual instrumentation, event-driven architecture.

**Implementation**:
- `/mahavishnu/learning/execution/telemetry.py` - Telemetry capture module
- Update `ModelRouter.route_task()` - Capture routing outcomes
- Update `PoolManager` - Track pool performance
- Subscribe to message bus `TASK_COMPLETED` events

### 6. Data Migration Script

**Why**: Initialize learning database, create schema with indexes and materialized views, add upgrade/downgrade support.

**Implementation**: `/scripts/migrate_learning_db.py`
- Initialize DuckDB learning database
- Create schema with indexes and materialized views
- Upgrade/downgrade support
- Validation and rollback capabilities

---

## Implementation Details

### Database Schema

```sql
-- Core executions table
CREATE TABLE executions (
    task_id UUID PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    task_type VARCHAR NOT NULL,
    task_description TEXT NOT NULL,
    repo VARCHAR NOT NULL,
    file_count INT NOT NULL,
    estimated_tokens INT NOT NULL,
    model_tier VARCHAR NOT NULL,
    pool_type VARCHAR NOT NULL,
    swarm_topology VARCHAR,
    routing_confidence FLOAT NOT NULL,
    complexity_score INT NOT NULL,
    success BOOLEAN NOT NULL,
    duration_seconds FLOAT NOT NULL,
    quality_score INT,
    cost_estimate FLOAT NOT NULL,
    actual_cost FLOAT NOT NULL,
    error_type VARCHAR,
    error_message TEXT,
    user_accepted BOOLEAN,
    user_rating INT,
    peak_memory_mb FLOAT,
    cpu_time_seconds FLOAT,
    solution_summary TEXT,
    embedding FLOAT[384],
    metadata JSON,
    uploaded_at TIMESTAMP DEFAULT NOW()
);

-- Solutions table (for Phase 2)
CREATE TABLE solutions (
    pattern_id UUID PRIMARY KEY,
    extracted_at TIMESTAMP,
    task_context TEXT,
    solution_summary TEXT,
    success_rate FLOAT,
    usage_count INT,
    repos_used_in VARCHAR[],
    embedding FLOAT[384]
);

-- Feedback table (for Phase 4)
CREATE TABLE feedback (
    feedback_id UUID PRIMARY KEY,
    task_id UUID REFERENCES executions(task_id),
    timestamp TIMESTAMP,
    feedback_type VARCHAR,
    rating INT,
    comment TEXT,
    user_id UUID
);

-- Quality policies (for Phase 3)
CREATE TABLE quality_policies (
    policy_id UUID PRIMARY KEY,
    repo VARCHAR,
    project_maturity VARCHAR,
    coverage_threshold FLOAT,
    strictness_level VARCHAR,
    last_adjusted TIMESTAMP,
    adjustment_reason VARCHAR
);
```

### Composite Indexes

```sql
-- Most common query: performance by task type and repo
CREATE INDEX idx_executions_repo_task
ON executions (repo, task_type, timestamp DESC);

-- For auto-tuning router: tier performance history
CREATE INDEX idx_executions_tier_success
ON executions (model_tier, success, timestamp DESC);

-- For pool optimization: pool performance by duration
CREATE INDEX idx_executions_pool_duration
ON executions (pool_type, success, duration_seconds);

-- For quality trend analysis
CREATE INDEX idx_executions_quality_trend
ON executions (repo, quality_score, timestamp DESC);
```

### Materialized Views

```sql
-- Tier performance dashboard (refresh every 5 minutes)
CREATE MATERIALIZED VIEW tier_performance_mv AS
SELECT
    repo,
    model_tier,
    task_type,
    DATE_TRUNC('day', timestamp) as date,
    COUNT(*) as total_executions,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_count,
    AVG(duration_seconds) as avg_duration,
    AVG(actual_cost) as avg_cost,
    AVG(quality_score) as avg_quality,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95_duration
FROM executions
WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY repo, model_tier, task_type, DATE_TRUNC('day', timestamp);

CREATE UNIQUE INDEX idx_tier_performance_lookup
ON tier_performance_mv (repo, model_tier, task_type, date);

-- Pool performance comparison (refresh every 10 minutes)
CREATE MATERIALIZED VIEW pool_performance_mv AS
SELECT
    pool_type,
    repo,
    DATE_TRUNC('hour', timestamp) as hour,
    COUNT(*) as total_tasks,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_tasks,
    AVG(duration_seconds) as avg_duration,
    AVG(actual_cost) as avg_cost,
    SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY pool_type, repo, DATE_TRUNC('hour', timestamp);

-- Solution pattern stats (refresh every hour)
CREATE MATERIALIZED VIEW solution_patterns_mv AS
SELECT
    solution_summary,
    repo,
    array_agg(DISTINCT task_type) as task_types,
    COUNT(*) as usage_count,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
    AVG(quality_score) as avg_quality,
    MIN(timestamp) as first_seen,
    MAX(timestamp) as last_seen,
    SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
FROM executions
WHERE solution_summary IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '90 days'
GROUP BY solution_summary, repo
HAVING COUNT(*) >= 5;

CREATE INDEX idx_solution_patterns_success_rate
ON solution_patterns_mv (success_rate DESC, usage_count DESC);
```

---

## File Structure

```
mahavishnu/
├── learning/
│   ├── __init__.py                 # Package init
│   ├── database.py                 # LearningDatabase class
│   ├── models.py                   # Pydantic models (ExecutionRecord, etc.)
│   └── execution/
│       ├── __init__.py             # Execution telemetry module
│       └── telemetry.py            # Telemetry capture hooks
scripts/
├── migrate_learning_db.py          # Migration script
tests/unit/
└── test_learning/
    ├── __init__.py
    ├── test_database.py            # LearningDatabase tests
    ├── test_models.py              # Model tests
    └── test_telemetry.py           # Telemetry tests
```

---

## Integration Points

### 1. Model Router Telemetry

**File**: `/mahavishnu/core/model_router.py`

**Changes**:
- Add telemetry capture in `route_task()` method
- Record routing decision and task analysis
- Publish outcome to message bus after task completion

```python
# In route_task() method
routing = ModelRouting(...)

# Capture telemetry
await telemetry.capture_routing_decision({
    "task_id": task.get("task_id"),
    "routing": routing,
    "timestamp": datetime.now(UTC),
})

# After task completion
await telemetry.capture_routing_outcome({
    "task_id": task_id,
    "success": outcome.success,
    "duration_seconds": outcome.duration,
    "quality_score": outcome.quality_score,
})
```

### 2. Pool Manager Telemetry

**File**: `/mahavishnu/pools/manager.py`

**Changes**:
- Add telemetry capture in `execute_on_pool()` method
- Track pool selection and performance
- Publish events to message bus

```python
# In execute_on_pool() method
# Before execution
await telemetry.capture_pool_execution_start({
    "pool_id": pool_id,
    "task_id": task_id,
    "timestamp": datetime.now(UTC),
})

# After execution
await telemetry.capture_pool_execution_complete({
    "pool_id": pool_id,
    "task_id": task_id,
    "success": result.success,
    "duration_seconds": result.duration,
})
```

### 3. Message Bus Integration

**File**: `/mahavishnu/learning/execution/telemetry.py`

**Subscribe to**:
- `TASK_COMPLETED` events
- `POOL_CREATED` events
- `POOL_CLOSED` events

**Publish to**:
- `ROUTING_DECISION` events
- `EXECUTION_RECORDED` events

---

## Testing Strategy

### Unit Tests

**Database Tests** (`test_database.py`):
- Test database initialization
- Test execution record storage
- Test similarity search
- Test tier performance queries
- Test materialized view refresh
- Test connection pooling

**Model Tests** (`test_models.py`):
- Test ExecutionRecord validation
- Test embedding content generation
- Test prediction error calculation
- Test Pydantic model constraints

**Telemetry Tests** (`test_telemetry.py`):
- Test routing decision capture
- Test pool execution capture
- Test message bus subscription
- Test telemetry aggregation

### Coverage Target

- **Database module**: 100% (critical infrastructure)
- **Models module**: 100% (data integrity)
- **Telemetry module**: 100% (observability)

---

## Success Criteria

### Functional Requirements

- ✅ Separate `LearningDatabase` class (no OtelIngester extension)
- ✅ Extended `ExecutionRecord` with all consultant fields
- ✅ Composite indexes for query optimization
- ✅ Materialized views for dashboard queries
- ✅ Telemetry hooks in model router and pool manager
- ✅ Data migration script with upgrade/downgrade
- ✅ 100% test coverage for new code

### Performance Requirements

- Queries <100ms at 100K executions
- Storage <500MB for 90-day retention
- 95th percentile latency <200ms
- Concurrent query support (4+ parallel queries)

### Quality Requirements

- All P0 consultant recommendations implemented
- Clean separation of concerns (OTel vs. learning)
- Comprehensive error handling and logging
- Full type hints with Pydantic validation
- Production-ready code quality

---

## Timeline

**Total Estimated Time**: 6-9 days

| Task | Duration | Dependencies |
|------|----------|--------------|
| Create package structure | 0.5 days | None |
| Implement ExecutionRecord model | 1 day | Package structure |
| Implement LearningDatabase class | 2 days | ExecutionRecord model |
| Create migration script | 1 day | LearningDatabase |
| Implement telemetry hooks | 1.5 days | LearningDatabase |
| Write unit tests | 2 days | All implementation |
| Integration testing | 0.5 days | All implementation |
| Documentation | 0.5 days | All implementation |

---

## Open Questions

1. **Database path**: Should learning database be in-memory or persistent?
   - **Recommendation**: Persistent at `data/learning.db` (follows HotStore pattern)

2. **Embedding model**: Use same model as OtelIngester?
   - **Recommendation**: Yes, `all-MiniLM-L6-v2` for consistency

3. **Migration data**: Should we migrate existing data from HotStore?
   - **Recommendation**: No, start fresh (HotStore has conversation data, not executions)

4. **View refresh schedule**: How often to refresh materialized views?
   - **Recommendation**: tier_performance_mv every 5 min, pool_performance_mv every 10 min, solution_patterns_mv every hour

---

## Next Steps

1. ✅ Create package structure (`mahavishnu/learning/`)
2. ✅ Implement `ExecutionRecord` model (`models.py`)
3. ✅ Implement `LearningDatabase` class (`database.py`)
4. ✅ Create migration script (`migrate_learning_db.py`)
5. ✅ Implement telemetry hooks (`execution/telemetry.py`)
6. ✅ Add telemetry to model router
7. ✅ Add telemetry to pool manager
8. ✅ Write comprehensive unit tests
9. ✅ Integration testing
10. ✅ Documentation

---

**Status**: In Progress
**Confidence**: High (95%)
**Estimated Timeline**: 6-9 days for complete P0 implementation
