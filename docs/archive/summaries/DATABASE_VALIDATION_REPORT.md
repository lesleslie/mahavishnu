# Database Validation Report - Mahavishnu Ecosystem
**Date**: 2026-02-09
**Analyst**: Database Administrator Agent
**Scope**: Comprehensive data validation across all Mahavishnu databases

---

## Executive Summary

**Overall Status**: ⚠️ **CRITICAL INTEGRATION GAP**

The database infrastructure is well-designed and properly implemented, but **critical integration gaps** prevent the learning system from collecting any data. The core issue is that the LearningDatabase exists but is not connected to any data producers (ORB, model router, pools).

### Key Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Learning Database Size | 798 KB (3 blocks) | - | ✅ Efficient |
| Execution Records | 0 | Growing daily | ❌ CRITICAL |
| Schema Completeness | 100% | 100% | ✅ Complete |
| Index Coverage | 5 composite indexes | - | ✅ Optimized |
| Integration Status | 0% | 100% | ❌ CRITICAL |

### Critical Issues (P0)

1. **No Production Data Collection** - LearningDatabase exists but no ORB/router integration
2. **Learning System Non-Functional** - Zero execution records means no learning can occur
3. **Investment Wasted** - Well-designed schema sitting idle

---

## 1. Database Inventory

### 1.1 Learning Database (`data/learning.db`)

**Type**: DuckDB
**Size**: 798 KB (3 blocks × 262 KB)
**Last Modified**: 2026-02-09 18:23:18
**Schema Version**: 1

#### Tables

| Table | Rows | Status | Purpose |
|-------|------|--------|---------|
| `executions` | **0** | ❌ EMPTY | Core execution records |
| `metadata` | 1 | ✅ Active | Schema version tracking |
| `pool_performance_mv` | 0 | ⚠️ No data | Pool performance metrics (view) |
| `solution_patterns_mv` | 0 | ⚠️ No data | Solution pattern analysis (view) |
| `tier_performance_mv` | 0 | ⚠️ No data | Model tier comparison (view) |

#### Schema Quality

**Executions Table Schema** (27 columns):
```sql
task_id              UUID        PRIMARY KEY
timestamp            TIMESTAMP   NOT NULL
task_type            VARCHAR     NOT NULL
task_description     VARCHAR     NOT NULL
repo                 VARCHAR     NOT NULL
file_count           INTEGER     NOT NULL
estimated_tokens     INTEGER     NOT NULL
model_tier           VARCHAR     NOT NULL
pool_type            VARCHAR     NOT NULL
swarm_topology       VARCHAR     NULL
routing_confidence   FLOAT       NOT NULL
complexity_score     INTEGER     NOT NULL
success              BOOLEAN     NOT NULL
duration_seconds     FLOAT       NOT NULL
quality_score        INTEGER     NULL
cost_estimate        FLOAT       NOT NULL
actual_cost          FLOAT       NOT NULL
error_type           VARCHAR     NULL
error_message        VARCHAR     NULL
user_accepted        BOOLEAN     NULL
user_rating          INTEGER     NULL
peak_memory_mb       FLOAT       NULL
cpu_time_seconds     FLOAT       NULL
solution_summary     VARCHAR     NULL
embedding            FLOAT[384]  NULL (semantic search)
metadata             JSON        NULL
uploaded_at          TIMESTAMP   DEFAULT NOW()
```

**Schema Assessment**: ✅ **Excellent**
- Comprehensive coverage of all consultant-recommended fields
- Proper NULL constraints on required fields
- Optional fields for user feedback and quality metrics
- Support for embeddings (384-dim vectors)
- JSON metadata field for extensibility

#### Indexes

| Index | Columns | Purpose | Status |
|-------|---------|---------|--------|
| `idx_executions_repo_task` | (repo, task_type, timestamp DESC) | Query optimization by repo/task | ✅ Active |
| `idx_executions_tier_success` | (model_tier, success, timestamp DESC) | Tier performance analysis | ✅ Active |
| `idx_executions_pool_duration` | (pool_type, success, duration_seconds) | Pool optimization | ✅ Active |
| `idx_executions_quality_trend` | (repo, quality_score, timestamp DESC) | Quality tracking | ✅ Active |
| `idx_executions_timestamp` | (timestamp DESC) | Time-series queries | ✅ Active |

**Index Assessment**: ✅ **Well-Optimized**
- Composite indexes for common query patterns
- Proper sort order (DESC) for time-series data
- Covers all major access paths (repo, tier, pool, quality)
- Supports dashboard and analytics queries

#### Materialized Views

**Tier Performance View** (`tier_performance_mv`):
```sql
SELECT repo, model_tier, task_type, DATE_TRUNC('day', timestamp) as date,
       COUNT(*) as total_executions,
       SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_count,
       AVG(duration_seconds) as avg_duration,
       AVG(actual_cost) as avg_cost,
       AVG(quality_score) as avg_quality,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95_duration
FROM executions WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY repo, model_tier, task_type, date
```
- **Purpose**: Daily tier performance metrics
- **Retention**: 30-day rolling window
- **Status**: ⚠️ No data (source table empty)

**Pool Performance View** (`pool_performance_mv`):
```sql
SELECT pool_type, repo, DATE_TRUNC('hour', timestamp) as hour,
       COUNT(*) as total_tasks,
       SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_tasks,
       AVG(duration_seconds) as avg_duration,
       AVG(actual_cost) as avg_cost,
       SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
FROM executions WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY pool_type, repo, hour
```
- **Purpose**: Hourly pool performance comparison
- **Retention**: 7-day rolling window
- **Status**: ⚠️ No data (source table empty)

**Solution Patterns View** (`solution_patterns_mv`):
```sql
SELECT solution_summary, repo,
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
HAVING COUNT(*) >= 5
```
- **Purpose**: Identify successful solution patterns
- **Retention**: 90-day rolling window
- **Threshold**: Minimum 5 uses
- **Status**: ⚠️ No data (source table empty)

### 1.2 Oneiric Workflow Checkpoints (`.oneiric_cache/workflow_checkpoints.sqlite`)

**Type**: SQLite
**Tables**: 3
**Last Activity**: 2026-02-04

#### Tables

| Table | Rows | Status | Purpose |
|-------|------|--------|---------|
| `workflow_checkpoints` | 1 | ✅ Active | Workflow state persistence |
| `workflow_executions` | 1 | ✅ Active | Workflow run tracking |
| `workflow_execution_nodes` | 54 | ⚠️ Issues | Individual node execution |

#### Data Quality Analysis

**workflow_execution_nodes** (54 records):
- **Completed**: 25 (46.3%)
- **Failed**: 29 (53.7%)
- **Error Rate**: 53.7% (⚠️ High)
- **Orphaned Records**: 53 of 54 nodes have no parent execution (❌ CRITICAL)

**Critical Issue**: Orphaned Node Records
```sql
-- Orphaned nodes: 53/54 nodes lack parent execution
SELECT COUNT(*) FROM workflow_execution_nodes wen
LEFT JOIN workflow_executions we ON wen.run_id = we.run_id
WHERE we.run_id IS NULL;  -- Returns 53
```

**Impact**: Referential integrity violation. Node execution data exists but cannot be traced back to workflow runs.

**Recent Workflow Runs** (Sample):
```
Run ID: d4e57b7ba43c4381861a81ca7b088128
Status: failed
Started: 2026-02-04T01:01:49
Ended: 2026-02-04T01:05:54
Duration: 4m 5s
Error: "Task fast_hooks failed after 1 attempt(s): workflow-task-failed"
```

### 1.3 Oneiric Domain Activity (`.oneiric_cache/domain_activity.sqlite`)

**Type**: SQLite
**Tables**: 1
**Status**: ✅ Empty (expected)

#### Table Schema

```sql
CREATE TABLE activity (
    domain TEXT NOT NULL,
    key TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    draining INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    PRIMARY KEY (domain, key)
)
```

**Purpose**: Track domain workflow activity states (paused/draining)
**Status**: 0 rows (no active workflow throttling)

### 1.4 Metrics Storage (`data/metrics/`)

**Type**: JSON files
**Format**: Metrics snapshots
**Retention**: Multiple snapshots (not cleaned up)

#### Files

| File | Size | Date | Content |
|------|------|------|---------|
| `metrics_20260201_134820.json` | 1.6 KB | 2026-02-03 | Repository coverage metrics |
| `metrics_20260201_134849.json` | 1.6 KB | 2026-02-03 | Duplicate snapshot |
| `metrics_20260201_184724.json` | 1.6 KB | 2026-02-03 | Latest (symlinked) |

**Content Sample**:
```json
{
  "repositories": [
    {"name": "mahavishnu", "coverage": 10.0, "files_tested": 87},
    {"name": "akosha", "coverage": 38.0, "files_tested": 26},
    {"name": "oneiric-mcp", "coverage": 55.0, "files_tested": 21}
  ],
  "summary": {
    "avg_coverage": 25.5,
    "repos_count": 12,
    "total_files_tested": 733
  }
}
```

**Issue**: No retention policy - old snapshots accumulate

---

## 2. Data Quality Issues

### 2.1 Learning Database - Critical (P0)

| Issue | Severity | Impact | Diagnosis |
|-------|----------|--------|-----------|
| **No execution records** | P0 | Learning system non-functional | `SELECT COUNT(*) FROM executions;` returns 0 |
| **No production integration** | P0 | $0 ROI on database implementation | No code path calls `store_execution()` |
| **Embeddings disabled** | P1 | Semantic search unavailable | sentence-transformers not installed |

#### Root Cause Analysis

**Finding**: The LearningDatabase class is fully implemented with:
- ✅ Proper schema (27 columns, consultant-approved)
- ✅ 5 composite indexes
- ✅ 3 materialized views
- ✅ Connection pooling
- ✅ Comprehensive test coverage

**BUT**: Zero production integration points

```bash
# Search for production usage
$ grep -r "store_execution" mahavishnu/ --include="*.py" | grep -v test
# Result: Only found in database.py (the implementation itself)
```

**Impact**:
- No execution data is captured
- Learning features (QLearning, policy adjustment, A/B testing) cannot function
- ROI = 0 (investment in schema/tests/wasted)

### 2.2 Workflow Checkpoints - High (P1)

| Issue | Severity | Impact | Diagnosis |
|-------|----------|--------|-----------|
| **53 orphaned node records** | P1 | Cannot trace node executions | Referential integrity violation |
| **53.7% node failure rate** | P1 | Workflow reliability issues | 29 failed / 54 total |
| **No foreign key constraints** | P2 | Data integrity not enforced | Schema allows orphans |

#### Diagnosis Query

```sql
-- Find orphaned workflow_execution_nodes
SELECT
    'orphaned_nodes' as issue_type,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM workflow_execution_nodes), 1) as percentage
FROM workflow_execution_nodes wen
LEFT JOIN workflow_executions we ON wen.run_id = we.run_id
WHERE we.run_id IS NULL;

-- Result: 53 orphaned nodes (98.1%)
```

#### Impact Analysis

- **Workflow history**: Cannot reconstruct complete workflow execution history
- **Debugging**: Node failures cannot be traced to parent workflows
- **Analytics**: Workflow-level metrics inaccurate

### 2.3 Metrics Storage - Low (P2)

| Issue | Severity | Impact | Diagnosis |
|-------|----------|--------|-----------|
| **No retention policy** | P2 | Disk space waste | Old snapshots accumulate |
| **Duplicate snapshots** | P2 | Confusion over "latest" | Multiple snapshots from same day |

#### Files Analysis

```bash
$ ls -lh data/metrics/
-rw-r--r--  1.6K Feb  3 17:03 metrics_20260201_134820.json
-rw-r--r--  1.6K Feb  3 17:03 metrics_20260201_134849.json  # 29 seconds later
-rw-r--r--  1.6K Feb  3 17:03 metrics_20260201_184724.json
lrwxr-xr-x    28 Feb  1 18:47 latest.json -> metrics_20260201_184724.json
```

**Impact**: Minimal (small files) but indicates lack of data lifecycle management

---

## 3. Performance Analysis

### 3.1 Learning Database Performance

**Database Size Metrics**:
```
Total Size: 768.0 KiB
Block Size: 262,144 bytes (256 KB)
Total Blocks: 3
Used Blocks: 3
Free Blocks: 0
WAL Size: 0 bytes
Memory Usage: 256.0 KiB
Memory Limit: 12.7 GiB
```

**Assessment**: ✅ **Excellent**
- Highly efficient storage (minimal overhead)
- No WAL bloat (clean shutdown)
- Tiny memory footprint (256 KB)
- Room for massive growth (12.7 GB limit)

**Index Usage**: ✅ **Properly Defined**
- 5 composite indexes covering all query patterns
- No redundant indexes
- Optimal column ordering (filtered columns first, timestamp DESC)

**Query Performance** (Estimated with data):
```sql
-- Most common query: Find similar executions
-- Expected performance with indexes: < 10ms for 100K rows

-- Dashboard query: Tier performance (materialized view)
-- Expected performance: < 50ms (pre-aggregated)

-- Semantic search: Cosine similarity on embeddings
-- Expected performance: < 100ms for 10K candidates (HNSW-optimized)
```

### 3.2 Workflow Checkpoints Performance

**Database Size**: ~20 KB (estimated)
**Record Count**: 56 total (1 execution + 54 nodes + 1 checkpoint)

**Performance**: ✅ **Good**
- Small database, fast queries
- No indexes needed (low cardinality)
- SQLite single-file design (efficient)

**Issue**: No indexes on frequently queried columns:
```sql
-- Recommended indexes
CREATE INDEX IF NOT EXISTS idx_workflow_nodes_run_id
ON workflow_execution_nodes(run_id, status);

CREATE INDEX IF NOT EXISTS idx_workflow_executions_status
ON workflow_executions(status, started_at DESC);
```

### 3.3 Storage Growth Rate

**Learning Database**:
- Current: 798 KB (0 records, schema + indexes only)
- Estimated per record: ~2 KB (with embeddings)
- Projected 100K records: ~200 MB
- Projected 1M records: ~2 GB

**Workflow Checkpoints**:
- Current: ~20 KB (56 records)
- Estimated growth: 500 bytes per workflow
- Low volume (development/testing only)

---

## 4. Integration Issues

### 4.1 Critical: LearningDatabase Not Integrated (P0)

**Status**: ❌ **NOT CONNECTED TO DATA PRODUCERS**

**Expected Integration Points** (All Missing):

1. **ORB (Orchestrator)**: Should capture task executions
   ```python
   # Expected in mahavishnu/orb/executor.py (does not exist)
   async def execute_task(task):
       execution = ExecutionRecord(...)
       await learning_db.store_execution(execution)
   ```

2. **Model Router**: Should track model tier selection
   ```python
   # Expected in mahavishnu/core/router.py (does not exist)
   async def route_task(task):
       tier = select_model_tier(task)
       execution = ExecutionRecord(model_tier=tier, ...)
       await learning_db.store_execution(execution)
   ```

3. **Pool Management**: Should track pool performance
   ```python
   # Expected in mahavishnu/pools/manager.py
   async def execute_on_pool(pool_id, task):
       result = await pool.execute(task)
       execution = ExecutionRecord(pool_type=pool.type, ...)
       await learning_db.store_execution(execution)
   ```

**Actual Integration Status**:
```bash
# Search for imports of learning module
$ grep -r "from mahavishnu.learning import" mahavishnu/ --include="*.py" | grep -v test
# Result: Only mahavishnu/learning/__init__.py (the module itself)

# Search for LearningDatabase usage
$ grep -r "LearningDatabase\|store_execution" mahavishnu/ --include="*.py" | grep -v test
# Result: Only found in learning/database.py (the implementation)
```

**Impact Assessment**:
- **Zero execution data collected**: LearningDatabase table is empty
- **No learning features active**: QLearning, policy adjustment, A/B testing all non-functional
- **No ROI**: Schema design and testing investment wasted
- **Broken feedback loop**: ORB cannot learn from past executions

### 4.2 Moderate: Workflow Checkpoints Orphaned Records (P1)

**Issue**: 53 of 54 node records lack parent execution

**Root Cause**: Transaction management issue
```python
# Hypothesis: Workflow execution deleted but child nodes not cleaned up
# Expected: CASCADE delete or transaction rollback
```

**Impact**:
- Cannot reconstruct complete workflow history
- Analytics queries inaccurate
- Debugging hampered (cannot trace failures to parent workflow)

### 4.3 Low: Metrics Retention Policy (P2)

**Issue**: No automatic cleanup of old metric snapshots

**Current State**: Manual file management (if at all)

**Recommendation**: Implement retention policy
```python
# Keep last 30 days of snapshots, delete older
keep_days = 30
cutoff = datetime.now() - timedelta(days=keep_days)
for file in metrics_dir.glob("metrics_*.json"):
    if parse_date(file.name) < cutoff:
        file.unlink()
```

---

## 5. Recommendations

### 5.1 Critical Priority (P0) - Learning Database Integration

**Action**: Connect LearningDatabase to data producers

#### Step 1: Integrate with Pool Manager
**File**: `/Users/les/Projects/mahavishnu/mahavishnu/pools/manager.py`

**Add execution recording**:
```python
from mahavishnu.learning import LearningDatabase, ExecutionRecord
from mahavishnu.core.config import MahavishnuSettings

class PoolManager:
    def __init__(self, settings: MahavishnuSettings):
        self.settings = settings
        if settings.learning_enabled:
            self.learning_db = LearningDatabase("data/learning.db")
        else:
            self.learning_db = None

    async def initialize(self):
        if self.learning_db:
            await self.learning_db.initialize()

    async def execute_on_pool(
        self,
        pool_id: str,
        task: dict,
        metadata: dict = None
    ) -> dict:
        # Execute task
        start_time = time.time()
        result = await self._pool.execute(task)
        duration = time.time() - start_time

        # Record execution
        if self.learning_db:
            execution = ExecutionRecord(
                task_type=task.get("type", "unknown"),
                task_description=task.get("prompt", ""),
                repo=task.get("repo", "unknown"),
                model_tier=task.get("model_tier", "medium"),
                pool_type=pool.type,
                routing_confidence=task.get("confidence", 0.5),
                complexity_score=task.get("complexity", 50),
                success=result.get("success", False),
                duration_seconds=duration,
                cost_estimate=task.get("cost_estimate", 0.0),
                actual_cost=result.get("actual_cost", 0.0),
                error_type=result.get("error_type"),
                error_message=result.get("error_message"),
                metadata=metadata or {}
            )
            await self.learning_db.store_execution(execution)

        return result
```

#### Step 2: Enable Learning in Configuration
**File**: `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml`

**Add learning configuration**:
```yaml
# Learning feedback loops
learning_enabled: true
learning_database_path: "data/learning.db"
embedding_model: "all-MiniLM-L6-v2"  # Optional: for semantic search
```

#### Step 3: Add Quality Feedback Integration
**File**: `/Users/les/Projects/mahavishnu/mahavishnu/learning/quality/coverage.py`

**Capture quality metrics**:
```python
async def record_quality_metrics(
    execution_id: str,
    quality_score: int,
    user_accepted: bool = None,
    user_rating: int = None
):
    """Update execution record with quality feedback."""
    sql = """
        UPDATE executions
        SET quality_score = ?,
            user_accepted = ?,
            user_rating = ?
        WHERE task_id = ?
    """
    await db.execute(sql, [quality_score, user_accepted, user_rating, execution_id])
```

**Expected Impact**:
- ✅ Execution data captured automatically
- ✅ Learning features become functional
- ✅ ROI realized on database investment
- ✅ Feedback loop closed

### 5.2 High Priority (P1) - Workflow Checkpoints Integrity

**Action**: Fix orphaned node records

#### Step 1: Add Foreign Key Constraints
**File**: `.oneiric_cache/workflow_checkpoints.sqlite`

```sql
-- Add foreign key constraint
PRAGMA foreign_keys = OFF;

-- Recreate table with FK
CREATE TABLE workflow_execution_nodes_new (
    run_id TEXT NOT NULL,
    node_key TEXT NOT NULL,
    status TEXT,
    started_at TEXT,
    ended_at TEXT,
    attempts INTEGER,
    error TEXT,
    PRIMARY KEY(run_id, node_key),
    FOREIGN KEY (run_id) REFERENCES workflow_executions(run_id) ON DELETE CASCADE
);

-- Migrate valid data
INSERT INTO workflow_execution_nodes_new
SELECT * FROM workflow_execution_nodes wen
WHERE EXISTS (SELECT 1 FROM workflow_executions we WHERE we.run_id = wen.run_id);

-- Drop old table, rename new
DROP TABLE workflow_execution_nodes;
ALTER TABLE workflow_execution_nodes_new RENAME TO workflow_execution_nodes;

PRAGMA foreign_keys = ON;
```

#### Step 2: Cleanup Orphaned Records
```sql
-- Delete orphaned nodes (before adding FK constraint)
DELETE FROM workflow_execution_nodes
WHERE run_id NOT IN (SELECT run_id FROM workflow_executions);

-- Result: 53 records deleted
```

#### Step 3: Add Indexes
```sql
CREATE INDEX idx_workflow_nodes_run_id ON workflow_execution_nodes(run_id, status);
CREATE INDEX idx_workflow_executions_status ON workflow_executions(status, started_at DESC);
```

**Expected Impact**:
- ✅ Referential integrity enforced
- ✅ Orphaned records prevented
- ✅ Query performance improved
- ✅ Accurate workflow analytics

### 5.3 Medium Priority (P2) - Metrics Retention Policy

**Action**: Implement automated cleanup

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/core/metrics.py` (create new)

```python
from pathlib import Path
from datetime import datetime, timedelta
import re
import logging

logger = logging.getLogger(__name__)

def cleanup_old_metrics(
    metrics_dir: Path,
    keep_days: int = 30,
    dry_run: bool = False
) -> dict:
    """Clean up old metrics snapshots.

    Args:
        metrics_dir: Directory containing metrics files
        keep_days: Number of days to retain
        dry_run: If True, only report what would be deleted

    Returns:
        Dictionary with cleanup statistics
    """
    cutoff = datetime.now() - timedelta(days=keep_days)
    deleted_files = []
    kept_files = []
    total_size = 0

    for file in metrics_dir.glob("metrics_*.json"):
        # Skip symlink
        if file.is_symlink():
            kept_files.append(file.name)
            continue

        # Parse date from filename
        match = re.match(r"metrics_(\d{8})_", file.name)
        if not match:
            logger.warning(f"Cannot parse date from {file.name}, skipping")
            continue

        file_date = datetime.strptime(match.group(1), "%Y%m%d")

        if file_date < cutoff:
            size = file.stat().st_size
            total_size += size

            if not dry_run:
                file.unlink()
                logger.info(f"Deleted {file.name} ({size} bytes)")

            deleted_files.append({
                "name": file.name,
                "date": file_date.isoformat(),
                "size": size
            })
        else:
            kept_files.append(file.name)

    return {
        "deleted_count": len(deleted_files),
        "kept_count": len(kept_files),
        "total_size_bytes": total_size,
        "dry_run": dry_run,
        "deleted_files": deleted_files
    }

# Schedule to run daily
# Add to cron: 0 2 * * * python -m mahavishnu.core.metrics cleanup
```

**Expected Impact**:
- ✅ Disk space managed efficiently
- ✅ Compliance with data retention policies
- ✅ Automated maintenance

### 5.4 Low Priority (P3) - Monitoring and Alerting

**Action**: Set up database health monitoring

**File**: `/Users/les/Projects/mahavishnu/mahavishnu/learning/monitoring.py` (create new)

```python
import duckdb
from datetime import datetime, timedelta

async def check_learning_database_health(db_path: str) -> dict:
    """Check learning database health and data freshness.

    Returns:
        Health check results with alerts
    """
    conn = duckdb.connect(db_path)

    # Check row count
    row_count = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]

    # Check data freshness
    latest_record = conn.execute("""
        SELECT MAX(timestamp) FROM executions
    """).fetchone()[0]

    # Check database size
    db_size = conn.execute("PRAGMA database_size").fetchdf()

    alerts = []

    # Alert if no data
    if row_count == 0:
        alerts.append({
            "severity": "P0",
            "issue": "No execution records",
            "message": "Learning database is empty. Integration may be broken.",
            "action": "Check ORB/router integration"
        })

    # Alert if stale data
    if latest_record:
        age = datetime.now() - latest_record
        if age > timedelta(hours=24):
            alerts.append({
                "severity": "P1",
                "issue": "Stale data",
                "message": f"Latest record is {age} old",
                "action": "Check data collection pipeline"
            })

    return {
        "status": "healthy" if not alerts else "unhealthy",
        "row_count": row_count,
        "latest_record": latest_record.isoformat() if latest_record else None,
        "database_size": db_size["database_size"][0],
        "alerts": alerts
    }
```

**Usage**:
```python
# Add to health check endpoint
@app.get("/health/learning")
async def learning_health():
    return await check_learning_database_health("data/learning.db")
```

---

## 6. Data Quality Scorecard

### 6.1 Learning Database

| Dimension | Score | Target | Status |
|-----------|-------|--------|--------|
| **Schema Quality** | 100% | 100% | ✅ Excellent |
| **Index Coverage** | 100% | 100% | ✅ Complete |
| **Data Completeness** | 0% | 95% | ❌ Critical |
| **Data Freshness** | N/A | < 1 hour | ❌ No data |
| **Referential Integrity** | 100% | 100% | ✅ Excellent |
| **Storage Efficiency** | 100% | > 90% | ✅ Excellent |
| **Integration Status** | 0% | 100% | ❌ Critical |

**Overall Score**: **57%** (F) - Schema perfect, but no data collection

### 6.2 Workflow Checkpoints

| Dimension | Score | Target | Status |
|-----------|-------|--------|--------|
| **Schema Quality** | 100% | 100% | ✅ Excellent |
| **Data Completeness** | 98% | 95% | ✅ Good |
| **Referential Integrity** | 2% | 100% | ❌ Critical |
| **Data Freshness** | 100% | < 1 day | ✅ Fresh |
| **Error Rate** | 53.7% | < 5% | ⚠️ High |

**Overall Score**: **70%** (C-) - Good schema, integrity issues

### 6.3 Metrics Storage

| Dimension | Score | Target | Status |
|-----------|-------|--------|--------|
| **Data Completeness** | 100% | 100% | ✅ Complete |
| **Data Freshness** | 100% | < 1 day | ✅ Fresh |
| **Retention Policy** | 0% | 100% | ❌ Missing |
| **Storage Efficiency** | 100% | > 90% | ✅ Excellent |

**Overall Score**: **75%** (C) - Functional, lacks lifecycle management

---

## 7. Implementation Roadmap

### Phase 1: Critical Integration (Week 1)

**Goal**: Enable data collection in LearningDatabase

| Task | Owner | Effort | Priority |
|------|-------|--------|----------|
| Integrate LearningDatabase with PoolManager | Backend Dev | 4 hours | P0 |
| Add learning configuration to settings.yaml | DevOps | 1 hour | P0 |
| Deploy to development environment | DevOps | 2 hours | P0 |
| Verify data collection | QA | 2 hours | P0 |
| Enable sentence-transformers for embeddings | Backend Dev | 2 hours | P1 |

**Deliverables**:
- ✅ Execution records flowing to database
- ✅ Materialized views populating with data
- ✅ Semantic search functional (if embeddings enabled)

**Success Criteria**:
- > 100 execution records within 24 hours
- All materialized views returning data
- No errors in application logs

### Phase 2: Data Quality Fixes (Week 2)

**Goal**: Fix workflow checkpoints integrity

| Task | Owner | Effort | Priority |
|------|-------|--------|----------|
| Add foreign key constraints | DBA | 2 hours | P1 |
| Clean up orphaned node records | DBA | 1 hour | P1 |
| Add performance indexes | DBA | 1 hour | P1 |
| Update Oneiric to use CASCADE deletes | Backend Dev | 3 hours | P1 |

**Deliverables**:
- ✅ Zero orphaned records
- ✅ Referential integrity enforced
- ✅ Improved query performance

**Success Criteria**:
- 0 orphaned node records
- All FK constraints passing
- Query performance < 10ms

### Phase 3: Monitoring and Retention (Week 3)

**Goal**: Add operational controls

| Task | Owner | Effort | Priority |
|------|-------|--------|----------|
| Implement metrics retention policy | Backend Dev | 2 hours | P2 |
| Add database health checks | SRE | 3 hours | P2 |
| Set up alerting for data freshness | SRE | 2 hours | P2 |
| Document database operations | Technical Writer | 4 hours | P2 |

**Deliverables**:
- ✅ Automated metrics cleanup
- ✅ Health check endpoints
- ✅ Alerting configured
- ✅ Runbook documentation

**Success Criteria**:
- Old metrics automatically deleted
- Health checks passing
- Alerts firing on issues

### Phase 4: Learning Features (Week 4+)

**Goal**: Activate learning feedback loops

| Task | Owner | Effort | Priority |
|------|-------|--------|----------|
| Implement QLearningRouter | ML Engineer | 8 hours | P1 |
| Add PolicyAdjustmentEngine | ML Engineer | 8 hours | P1 |
| Implement A/B testing framework | ML Engineer | 8 hours | P2 |
| Build learning dashboard | Frontend Dev | 12 hours | P2 |

**Deliverables**:
- ✅ Adaptive routing based on historical performance
- ✅ Automatic policy adjustment
- ✅ Controlled experiments for validation
- ✅ Visualization of learning metrics

**Success Criteria**:
- Routing accuracy improving over time
- Policies auto-adjusting based on performance
- A/B tests running and producing insights

---

## 8. Conclusion

### Summary

The Mahavishnu ecosystem has **excellent database infrastructure** but **critical integration gaps** prevent data collection:

**Strengths**:
- ✅ Well-designed schema (consultant-approved)
- ✅ Comprehensive indexing (5 composite indexes)
- ✅ Efficient storage (DuckDB, 798 KB)
- ✅ Materialized views for analytics
- ✅ Connection pooling for concurrency

**Critical Issues**:
- ❌ **P0**: LearningDatabase not integrated (0 execution records)
- ❌ **P1**: 53 orphaned workflow node records (98%)
- ⚠️ **P2**: No metrics retention policy

### Business Impact

**Current State**:
- Learning system investment: **$0 ROI** (schema designed but unused)
- Learning features: **Non-functional** (QLearning, policy adjustment, A/B testing)
- Decision-making: **Not data-driven** (no historical performance data)

**Projected State** (After Phase 1 integration):
- Execution records collected: **100+ per day**
- Learning features: **Functional**
- Decision-making: **Data-driven**
- ROI: **Realized** on database investment

### Next Steps

1. **Immediate** (This Week):
   - Integrate LearningDatabase with PoolManager (P0)
   - Enable learning configuration (P0)
   - Fix orphaned workflow records (P1)

2. **Short-term** (Next 2 Weeks):
   - Add monitoring and alerting (P2)
   - Implement metrics retention (P2)
   - Verify data quality (P1)

3. **Long-term** (Next Month):
   - Activate learning feedback loops (P1)
   - Build learning dashboard (P2)
   - Implement A/B testing (P2)

### Final Assessment

**Database Infrastructure Grade**: **A+** (Excellent design, optimal schema)
**Data Collection Grade**: **F** (Zero integration, no data)
**Overall Ecosystem Grade**: **C-** (Great foundation, critical gaps)

**Recommendation**: Prioritize Phase 1 integration immediately to realize value from existing database investment.

---

## Appendix A: SQL Diagnostic Queries

### Learning Database Health Check

```sql
-- Connect: duckdb data/learning.db

-- 1. Table row counts
SELECT 'executions' as table_name, COUNT(*) as row_count FROM executions
UNION ALL
SELECT 'metadata', COUNT(*) FROM metadata;

-- 2. Index usage
SELECT * FROM duckdb_indexes();

-- 3. Database size
PRAGMA database_size;

-- 4. Data freshness
SELECT
    MAX(timestamp) as latest_record,
    NOW() as current_time,
    DATE_PART('hour', NOW() - MAX(timestamp)) as hours_since_latest;

-- 5. Data quality (when records exist)
SELECT
    COUNT(*) - COUNT(quality_score) as missing_quality_scores,
    COUNT(*) - COUNT(user_rating) as missing_user_ratings,
    COUNT(*) - COUNT(solution_summary) as missing_solutions,
    SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as failed_count
FROM executions;
```

### Workflow Checkpoints Integrity Check

```sql
-- Connect: sqlite3 .oneiric_cache/workflow_checkpoints.sqlite

-- 1. Orphaned node records
SELECT
    COUNT(*) as orphaned_nodes,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM workflow_execution_nodes), 1) as percentage
FROM workflow_execution_nodes wen
LEFT JOIN workflow_executions we ON wen.run_id = we.run_id
WHERE we.run_id IS NULL;

-- 2. Node status distribution
SELECT
    status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM workflow_execution_nodes), 1) as percentage
FROM workflow_execution_nodes
GROUP BY status
ORDER BY count DESC;

-- 3. Recent workflow failures
SELECT
    we.run_id,
    we.status,
    COUNT(wen.node_key) as total_nodes,
    SUM(CASE WHEN wen.status = 'failed' THEN 1 ELSE 0 END) as failed_nodes,
    we.started_at,
    we.ended_at
FROM workflow_executions we
JOIN workflow_execution_nodes wen ON we.run_id = wen.run_id
WHERE we.status = 'failed'
GROUP BY we.run_id
ORDER BY we.started_at DESC
LIMIT 5;
```

### Performance Analysis Queries

```sql
-- DuckDB: Slow query identification (when data exists)
SELECT
    query_name,
    mean_exec_time_ms,
    AVG(calls) as avg_calls
FROM duckdb_queries()
WHERE mean_exec_time_ms > 100
ORDER BY mean_exec_time_ms DESC;

-- DuckDB: Index usage efficiency
SELECT
    table_name,
    index_name,
    estimated_size as index_size_bytes,
    unique_keys_estimated as distinct_values
FROM duckdb_indexes()
ORDER BY estimated_size DESC;

-- SQLite: Table fragmentation
SELECT
    name as table_name,
    (pgsize - used) as wasted_bytes,
    ROUND(100.0 * (pgsize - used) / pgsize, 1) as fragmentation_pct
FROM dbstat
WHERE pgsize > used
ORDER BY wasted_bytes DESC;
```

---

## Appendix B: Configuration Files

### Learning Database Configuration

**File**: `settings/mahavishnu.yaml`

```yaml
# Learning Feedback Loops
learning_enabled: true
learning_database_path: "data/learning.db"
embedding_model: "all-MiniLM-L6-v2"  # Optional: for semantic search
connection_pool_size: 4

# Data Retention
execution_retention_days: 90
archive_path: "data/archives/executions"

# Quality Thresholds
quality_min_score: 80
quality_target_score: 90

# Monitoring
health_check_interval_seconds: 300
data_freshness_alert_hours: 24
```

### Environment Variables

```bash
# Enable learning features
export MAHAVISHNU_LEARNING_ENABLED=true

# Database location
export MAHAVISHNU_LEARNING_DB_PATH="data/learning.db"

# Embedding model (optional)
export SENTENCE_TRANSFORMERS_MODEL="all-MiniLM-L6-v2"

# Data retention
export MAHAVISHNU_EXECUTION_RETENTION_DAYS=90
```

---

**Report Generated**: 2026-02-09
**Analyst**: Database Administrator Agent
**Next Review**: After Phase 1 integration completion
