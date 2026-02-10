# Database Validation - Quick Start Guide

## Overview

This guide helps you validate database health and data quality across the Mahavishnu ecosystem.

## Quick Validation

### Run Automated Validation

```bash
# Text output (default)
python3 scripts/validate_databases.py

# JSON output (for CI/CD)
python3 scripts/validate_databases.py --output-format json

# Markdown output (for documentation)
python3 scripts/validate_databases.py --output-format markdown
```

### Exit Codes

- `0`: All checks passed (HEALTHY)
- `1`: Critical issues found (P0)
- `2`: High priority issues found (P1)
- `3`: Medium priority issues found (P2)

## Current Status (2026-02-09)

**Overall Status**: ❌ CRITICAL (Exit Code: 1)

### Issues Summary

| Severity | Count | Status |
|----------|-------|--------|
| **P0** (Critical) | 2 | ❌ Must fix immediately |
| **P1** (High) | 2 | ⚠️ Fix this week |
| **P2** (Medium) | 2 | ⚠️ Fix soon |

### Critical Issues (P0)

1. **No execution records in learning database**
   - **Impact**: Learning system non-functional
   - **Fix**: Integrate LearningDatabase with PoolManager
   - **File**: See Phase 1 Integration Guide below

2. **DuckDB/pandas dependency issue** (Minor)
   - **Impact**: Validation script cannot get detailed metrics
   - **Fix**: `pip install pandas` (optional, for detailed metrics)

### High Priority Issues (P1)

1. **53 orphaned workflow node records (98.1%)**
   - **Impact**: Cannot trace workflow execution history
   - **Fix**: See Workflow Checkpoints Cleanup below

2. **53.7% workflow node failure rate**
   - **Impact**: Poor workflow reliability
   - **Fix**: Investigate common failure patterns

## Phase 1: Fix Learning Database Integration (P0)

### Step 1: Enable Learning in Configuration

**File**: `settings/mahavishnu.yaml`

```yaml
# Add these lines:
learning_enabled: true
learning_database_path: "data/learning.db"
embedding_model: "all-MiniLM-L6-v2"  # Optional
connection_pool_size: 4
```

### Step 2: Integrate with PoolManager

**File**: `mahavishnu/pools/manager.py`

Add execution recording:

```python
from mahavishnu.learning import LearningDatabase, ExecutionRecord

class PoolManager:
    def __init__(self, settings):
        self.settings = settings
        if settings.learning_enabled:
            self.learning_db = LearningDatabase("data/learning.db")
        else:
            self.learning_db = None

    async def initialize(self):
        if self.learning_db:
            await self.learning_db.initialize()

    async def execute_on_pool(self, pool_id, task, metadata=None):
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

### Step 3: Verify Integration

```bash
# After running application, check for data
duckdb data/learning.db "SELECT COUNT(*) FROM executions;"

# Expected: > 0 records
# If still 0, check logs for errors
```

## Phase 2: Fix Workflow Checkpoints (P1)

### Cleanup Orphaned Records

**File**: `.oneiric_cache/workflow_checkpoints.sqlite`

```sql
-- Step 1: Delete orphaned nodes
DELETE FROM workflow_execution_nodes
WHERE run_id NOT IN (SELECT run_id FROM workflow_executions);

-- Step 2: Add foreign key constraint
PRAGMA foreign_keys = OFF;

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

INSERT INTO workflow_execution_nodes_new
SELECT * FROM workflow_execution_nodes
WHERE run_id IN (SELECT run_id FROM workflow_executions);

DROP TABLE workflow_execution_nodes;
ALTER TABLE workflow_execution_nodes_new RENAME TO workflow_execution_nodes;

PRAGMA foreign_keys = ON;

-- Step 3: Add indexes
CREATE INDEX idx_workflow_nodes_run_id
ON workflow_execution_nodes(run_id, status);

CREATE INDEX idx_workflow_executions_status
ON workflow_executions(status, started_at DESC);
```

### Run Cleanup Script

```bash
# Save SQL to file and run
sqlite3 .oneiric_cache/workflow_checkpoints.sqlite < cleanup_workflow.sql
```

## Phase 3: Implement Metrics Retention (P2)

**File**: `scripts/cleanup_metrics.py` (create new)

```python
from pathlib import Path
from datetime import datetime, timedelta
import re

def cleanup_old_metrics(metrics_dir: Path, keep_days: int = 30):
    """Clean up old metrics snapshots."""
    cutoff = datetime.now() - timedelta(days=keep_days)
    deleted = 0

    for file in metrics_dir.glob("metrics_*.json"):
        if file.is_symlink():
            continue  # Don't delete symlinks

        match = re.match(r"metrics_(\d{8})_", file.name)
        if match:
            file_date = datetime.strptime(match.group(1), "%Y%m%d")
            if file_date < cutoff:
                file.unlink()
                deleted += 1
                print(f"Deleted {file.name}")

    print(f"Total deleted: {deleted} files")

if __name__ == "__main__":
    cleanup_old_metrics(Path("data/metrics"), keep_days=30)
```

```bash
# Run cleanup
python3 scripts/cleanup_metrics.py

# Add to cron for daily cleanup
# 0 2 * * * cd /path/to/mahavishnu && python3 scripts/cleanup_metrics.py
```

## Monitoring

### Set Up Health Checks

Add to your monitoring/health check endpoint:

```python
from scripts.validate_databases import DatabaseValidator

@app.get("/health/database")
async def database_health():
    validator = DatabaseValidator(Path.cwd())
    results = validator.validate_all()
    return {
        "status": results["summary"]["overall_status"],
        "issues": results["summary"]["total_issues"],
        "by_severity": results["summary"]["severity_breakdown"]
    }
```

### Alert on Issues

Configure alerts for:

1. **P0 Issues**: Page immediately
2. **P1 Issues**: Email within 1 hour
3. **P2 Issues**: Email daily digest

## Validation Schedule

### Recommended Frequency

- **Real-time**: Health check endpoint (always available)
- **Hourly**: Automated validation script (CI/CD)
- **Daily**: Full validation report (email digest)
- **Weekly**: Manual review of data quality trends

### CI/CD Integration

Add to your CI pipeline:

```yaml
# .github/workflows/database-validation.yml
name: Database Validation

on:
  schedule:
    - cron: '0 * * * *'  # Every hour
  workflow_dispatch:  # Manual trigger

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Run validation
        run: |
          python3 scripts/validate_databases.py --output-format json > results.json
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: validation-results
          path: results.json
      - name: Check for critical issues
        run: |
          python3 scripts/validate_databases.py
          # Exit code 1 = P0 issues, fails CI
```

## Manual SQL Queries

### Learning Database

```sql
-- Connect: duckdb data/learning.db

-- Check row counts
SELECT 'executions' as table_name, COUNT(*) as row_count FROM executions
UNION ALL
SELECT 'metadata', COUNT(*) FROM metadata;

-- Check data freshness
SELECT MAX(timestamp) as latest_record,
       DATE_PART('hour', NOW() - MAX(timestamp)) as hours_old
FROM executions;

-- Check data quality
SELECT COUNT(*) - COUNT(quality_score) as missing_quality,
       COUNT(*) - COUNT(user_rating) as missing_ratings,
       SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as failed
FROM executions;
```

### Workflow Checkpoints

```sql
-- Connect: sqlite3 .oneiric_cache/workflow_checkpoints.sqlite

-- Check orphaned records
SELECT COUNT(*) as orphaned_nodes
FROM workflow_execution_nodes wen
LEFT JOIN workflow_executions we ON wen.run_id = we.run_id
WHERE we.run_id IS NULL;

-- Check failure rate
SELECT status, COUNT(*) as count,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM workflow_execution_nodes), 1) as percentage
FROM workflow_execution_nodes
GROUP BY status;
```

## Troubleshooting

### Learning Database Empty

**Symptoms**: `executions` table has 0 rows

**Diagnosis**:
```bash
# Check if learning is enabled
grep learning_enabled settings/mahavishnu.yaml

# Check for integration
grep -r "store_execution" mahavishnu/ --include="*.py" | grep -v test
```

**Solutions**:
1. Enable `learning_enabled: true` in configuration
2. Integrate LearningDatabase with PoolManager (see Phase 1)
3. Verify no errors in application logs

### High Workflow Failure Rate

**Symptoms**: > 10% nodes failing

**Diagnosis**:
```sql
SELECT error, COUNT(*) as count
FROM workflow_execution_nodes
WHERE status = 'failed'
GROUP BY error
ORDER BY count DESC
LIMIT 5;
```

**Solutions**:
1. Fix common error patterns
2. Add retry logic with exponential backoff
3. Improve error handling and logging

### Orphaned Records

**Symptoms**: Nodes without parent executions

**Diagnosis**:
```sql
-- Find orphaned nodes
SELECT wen.run_id, wen.node_key, wen.status
FROM workflow_execution_nodes wen
LEFT JOIN workflow_executions we ON wen.run_id = we.run_id
WHERE we.run_id IS NULL
LIMIT 10;
```

**Solutions**:
1. Delete orphaned records (see Phase 2)
2. Add foreign key constraints
3. Fix transaction management in Oneiric

## Resources

- **Full Report**: `DATABASE_VALIDATION_REPORT.md`
- **SQL Script**: `scripts/validate_databases.sql`
- **Python Script**: `scripts/validate_databases.py`
- **Learning Database**: `data/learning.db`
- **Workflow Checkpoints**: `.oneiric_cache/workflow_checkpoints.sqlite`

## Support

For issues or questions:
1. Check the full validation report for detailed analysis
2. Review database schemas in `mahavishnu/learning/database.py`
3. Consult the database administrator agent for assistance

---

**Last Updated**: 2026-02-09
**Validation Status**: ❌ CRITICAL - 6 issues found (2 P0, 2 P1, 2 P2)
