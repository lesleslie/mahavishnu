# ORB Learning Backend - Quick Start Guide

**Version**: 0.1.0
**Date**: 2026-02-09

---

## Overview

The ORB Learning backend provides database storage, data models, and telemetry capture for learning analytics in the Bodhisattva ecosystem.

## Installation

### Dependencies

```bash
# Install DuckDB (database)
pip install duckdb

# Install sentence-transformers (requires Python 3.10-3.12)
pip install sentence-transformers
```

**Note**: If using Python 3.13, use Python 3.12 environment for sentence-transformers.

### Initialize Database

```bash
# Run migration script to create database schema
python scripts/migrate_learning_db.py upgrade

# Validate installation
python scripts/migrate_learning_db.py validate
```

---

## Usage

### 1. Execution Records

Create and store execution records:

```python
from mahavishnu.learning import ExecutionRecord, LearningDatabase
from datetime import UTC, datetime

# Initialize database
db = LearningDatabase(database_path="data/learning.db")
await db.initialize()

# Create execution record
execution = ExecutionRecord(
    task_type="refactor",
    task_description="Optimize database queries",
    repo="mahavishnu",
    file_count=3,
    estimated_tokens=2500,
    model_tier="medium",
    pool_type="mahavishnu",
    swarm_topology=None,
    routing_confidence=0.85,
    complexity_score=65,
    success=True,
    duration_seconds=45.2,
    quality_score=92,
    cost_estimate=0.003,
    actual_cost=0.0032,
)

# Store in database
await db.store_execution(execution)

# Close database
await db.close()
```

### 2. Semantic Search

Find similar past executions:

```python
# Find similar executions
similar = await db.find_similar_executions(
    task_description="Optimize slow queries",
    repo="mahavishnu",
    limit=5,
    days_back=90,
    threshold=0.7,
)

for result in similar:
    print(f"Task: {result['task_type']}")
    print(f"Similarity: {result['similarity']:.2f}")
    print(f"Solution: {result.get('solution_summary', 'N/A')}")
```

### 3. Performance Analytics

Get tier and pool performance metrics:

```python
# Get tier performance (from materialized view)
tier_perf = await db.get_tier_performance(
    repo="mahavishnu",
    days_back=30,
)

for metric in tier_perf:
    print(f"Tier: {metric['model_tier']}")
    print(f"Avg Duration: {metric['avg_duration']:.2f}s")
    print(f"Success Rate: {metric['successful_count']}/{metric['total_executions']}")

# Get pool performance
pool_perf = await db.get_pool_performance(
    repo="mahavishnu",
    days_back=7,
)

for metric in pool_perf:
    print(f"Pool: {metric['pool_type']}")
    print(f"Success Rate: {metric['success_rate']:.1%}")
```

### 4. Solution Patterns

Get top solution patterns by success rate:

```python
patterns = await db.get_solution_patterns(
    repo="mahavishnu",
    min_usage=5,
    limit=10,
)

for pattern in patterns:
    print(f"Solution: {pattern['solution_summary']}")
    print(f"Success Rate: {pattern['success_rate']:.1%}")
    print(f"Usage: {pattern['usage_count']} times")
```

---

## Telemetry Integration

### Model Router Integration

Add telemetry capture to `Mahavishnu/core/model_router.py`:

```python
from mahavishnu.learning.execution import TelemetryCapture

# Initialize telemetry
telemetry = TelemetryCapture(message_bus=self.message_bus)
await telemetry.initialize()

# In route_task() method:
async def route_task(self, task: dict[str, Any], ...):
    routing = await self._analyze_and_route(task)

    # Capture routing decision
    await telemetry.capture_routing_decision({
        "task_id": task.get("task_id", str(uuid4())),
        "routing": routing,
        "timestamp": datetime.now(UTC),
        "task_data": task,
    })

    return routing
```

### Pool Manager Integration

Add telemetry capture to `Mahavishnu/pools/manager.py`:

```python
# In execute_on_pool() method:
async def execute_on_pool(self, pool_id: str, task: dict[str, ...]):
    task_id = str(uuid4())

    # Capture execution start
    await telemetry.capture_pool_execution_start({
        "pool_id": pool_id,
        "task_id": task_id,
        "timestamp": datetime.now(UTC),
    })

    result = await pool.execute(task)

    # Capture execution outcome
    await telemetry.capture_execution_outcome({
        "task_id": task_id,
        "success": result.get("success", False),
        "duration_seconds": result.get("duration", 0.0),
        "quality_score": result.get("quality_score"),
        "actual_cost": result.get("cost", 0.0),
        "pool_id": pool_id,
    })

    return result
```

---

## Database Schema

### Executions Table

```sql
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
```

### Composite Indexes

```sql
CREATE INDEX idx_executions_repo_task
ON executions (repo, task_type, timestamp DESC);

CREATE INDEX idx_executions_tier_success
ON executions (model_tier, success, timestamp DESC);

CREATE INDEX idx_executions_pool_duration
ON executions (pool_type, success, duration_seconds);

CREATE INDEX idx_executions_quality_trend
ON executions (repo, quality_score, timestamp DESC);
```

### Materialized Views

```sql
-- Tier performance dashboard
CREATE VIEW tier_performance_mv AS
SELECT
    repo, model_tier, task_type,
    DATE_TRUNC('day', timestamp) as date,
    COUNT(*) as total_executions,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_count,
    AVG(duration_seconds) as avg_duration,
    AVG(actual_cost) as avg_cost,
    AVG(quality_score) as avg_quality
FROM executions
WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY repo, model_tier, task_type, DATE_TRUNC('day', timestamp);

-- Pool performance comparison
CREATE VIEW pool_performance_mv AS
SELECT
    pool_type, repo,
    DATE_TRUNC('hour', timestamp) as hour,
    COUNT(*) as total_tasks,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_tasks,
    AVG(duration_seconds) as avg_duration,
    AVG(actual_cost) as avg_cost
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY pool_type, repo, DATE_TRUNC('hour', timestamp);

-- Solution pattern stats
CREATE VIEW solution_patterns_mv AS
SELECT
    solution_summary, repo,
    COUNT(*) as usage_count,
    SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
FROM executions
WHERE solution_summary IS NOT NULL
GROUP BY solution_summary, repo
HAVING COUNT(*) >= 5;
```

---

## Migration Commands

```bash
# Upgrade to latest schema
python scripts/migrate_learning_db.py upgrade

# Validate current schema
python scripts/migrate_learning_db.py validate

# Downgrade (drop all tables)
python scripts/migrate_learning_db.py downgrade

# Reset (delete and recreate)
python scripts/migrate_learning_db.py reset

# Custom database path
python scripts/migrate_learning_db.py upgrade --db-path /path/to/db

# Enable verbose logging
python scripts/migrate_learning_db.py upgrade -v
```

---

## Testing

### Run Unit Tests

```bash
# Test all learning modules
pytest tests/unit/test_learning/ -v

# Test specific module
pytest tests/unit/test_learning/test_models.py -v

# Run with coverage
pytest tests/unit/test_learning/ --cov=mahavishnu/learning --cov-report=html
```

### Test Coverage

- **Models**: 100% (19/19 tests passing)
- **Database**: 100% (with mocks)
- **Telemetry**: 100% (with mocks)

---

## Performance Benchmarks

### Query Performance (Projected)

| Query | 1K Records | 100K Records | 1M Records |
|-------|-----------|--------------|------------|
| Similar Executions | 5ms | 50ms | 200ms |
| Tier Performance | 5ms | 10ms | 20ms |
| Top Patterns | 10ms | 20ms | 50ms |

### Storage Projections (Compressed)

| Scale | Executions/Day | Yearly Storage |
|-------|----------------|----------------|
| Solo Dev | 1K | 121 MB |
| Small Team | 10K | 1.2 GB |
| Production | 100K | 12 GB |

---

## API Reference

### LearningDatabase

```python
class LearningDatabase:
    async def initialize(self) -> None:
        """Initialize database schema and connection pool."""

    async def store_execution(self, execution: ExecutionRecord) -> None:
        """Store execution record with embedding."""

    async def find_similar_executions(
        self,
        task_description: str,
        repo: str | None = None,
        limit: int = 10,
        days_back: int = 90,
        threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Find semantically similar executions."""

    async def get_tier_performance(
        self,
        repo: str | None = None,
        days_back: int = 30,
    ) -> list[dict[str, Any]]:
        """Get tier performance metrics."""

    async def get_pool_performance(
        self,
        repo: str | None = None,
        days_back: int = 7,
    ) -> list[dict[str, Any]]:
        """Get pool performance metrics."""

    async def get_solution_patterns(
        self,
        repo: str | None = None,
        min_usage: int = 5,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get top solution patterns."""

    async def close(self) -> None:
        """Close database connection pool."""
```

### ExecutionRecord

```python
class ExecutionRecord(BaseModel):
    task_id: UUID
    timestamp: datetime
    task_type: str
    task_description: str
    repo: str
    file_count: int
    estimated_tokens: int
    model_tier: str
    pool_type: str
    swarm_topology: str | None
    routing_confidence: float  # 0.0-1.0
    complexity_score: int  # 0-100
    success: bool
    duration_seconds: float
    quality_score: int | None  # 0-100
    cost_estimate: float
    actual_cost: float
    error_type: ErrorType | None
    error_message: str | None
    user_accepted: bool | None
    user_rating: int | None  # 1-5
    peak_memory_mb: float | None
    cpu_time_seconds: float | None
    solution_summary: str | None
    metadata: dict[str, Any]

    def calculate_embedding_content(self) -> str:
        """Generate content for embedding generation."""

    def calculate_prediction_error(self) -> dict[str, float]:
        """Calculate prediction accuracy metrics."""
```

### TelemetryCapture

```python
class TelemetryCapture:
    async def initialize(self) -> None:
        """Initialize telemetry and subscribe to events."""

    async def capture_routing_decision(self, data: dict[str, Any]) -> None:
        """Capture model routing decision."""

    async def capture_execution_outcome(self, data: dict[str, Any]) -> None:
        """Capture task execution outcome."""

    async def capture_pool_execution_start(self, data: dict[str, Any]) -> None:
        """Capture pool execution start event."""

    async def capture_pool_execution_complete(self, data: dict[str, Any]) -> None:
        """Capture pool execution completion event."""

    async def shutdown(self) -> None:
        """Shutdown telemetry and cleanup resources."""
```

---

## Troubleshooting

### ImportError: No module named 'duckdb'

```bash
pip install duckdb
```

### ImportError: No module named 'sentence_transformers'

```bash
# Use Python 3.10-3.12 environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install sentence-transformers
```

### Database initialization failed

```bash
# Check data directory exists
mkdir -p data

# Validate database
python scripts/migrate_learning_db.py validate

# Reset if needed
python scripts/migrate_learning_db.py reset
```

### Slow queries

```bash
# Check indexes exist
python -c "
import duckdb
conn = duckdb.connect('data/learning.db')
indexes = conn.execute(\"SELECT indexname FROM pg_indexes\").fetchall()
print('Indexes:', indexes)
"

# Re-run migration to create indexes
python scripts/migrate_learning_db.py upgrade
```

---

## Next Steps

1. **Integrate telemetry** into model router and pool manager
2. **Initialize database** in production environment
3. **Monitor performance** metrics and query latency
4. **Implement Phase 2** (Knowledge Synthesis)

---

## Support

For issues or questions:
- Check `/PHASE1_LEARNING_BACKEND_COMPLETE.md` for implementation details
- Review inline docstrings and type hints
- Run unit tests to verify installation

---

**Version**: 0.1.0
**Last Updated**: 2026-02-09
