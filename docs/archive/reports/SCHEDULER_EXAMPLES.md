# Mahavishnu Scheduler Configuration Examples

This file provides practical examples for all three schedulers in common scenarios.

---

## 🚀 Quick Start

### 1. Initialize Scheduler in MahavishnuApp

**`mahavishnu/core/app.py`** (add to `MahavishnuApp.__init__`):

```python
from .scheduler import MahavishnuScheduler

class MahavishnuApp:
    def __init__(self, config: MahavishnuSettings | None = None):
        # ... existing initialization...

        # Initialize scheduler
        self.scheduler = MahavishnuScheduler(self)

    async def start_schedulers(self) -> None:
        """Start all three schedulers."""
        await self.scheduler.start()
```

### 2. Use Scheduler Lifecycle

```python
# In your startup code
async with app.scheduler.lifecycle():
    # Schedulers are running
    # Your application logic here

    # Schedule a task
    await app.scheduler.schedule_internal_task(
        my_task,
        trigger_type="interval",
        seconds=60,
    )

    # Schedulers auto-cleanup on exit
```

---

## 📋 Example 1: Internal Task Scheduling (APScheduler)

### Scenario: Health Check Every 30 Seconds

```python
# mahavishnu/core/scheduler.py

async def health_check_job():
    """Internal health check - runs in Mahavishnu process."""
    try:
        is_healthy = await app.is_healthy()
        logger.info("health_check_completed", healthy=is_healthy)

        if app.observability:
            app.observability.record_health_check(is_healthy)

    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        raise

# In app initialization
await scheduler.schedule_internal_task(
    health_check_job,
    trigger_type="interval",
    seconds=30,
    id="mahavishnu-health-check",
)
```

### Scenario: Cache Cleanup Every Hour

```python
async def cleanup_cache_job():
    """Clean up old cache entries."""
    logger.info("starting_cache_cleanup")

    try:
        # Your cache cleanup logic
        await app.cache.cleanup_expired()

        logger.info("cache_cleanup_complete",
                    entries_deleted=42)
    except Exception as e:
        logger.error("cache_cleanup_failed", error=str(e))
        raise

await scheduler.schedule_internal_task(
    cleanup_cache_job,
    trigger_type="cron",
    hour="*",  # Every hour
    id="mahavishnu-cache-cleanup",
)
```

### Scenario: Daily Metrics Collection

```python
async def collect_metrics_job():
    """Collect and report internal metrics."""
    logger.debug("collecting_metrics")

    # Pool metrics
    if app.pool_manager:
        pool_stats = await app.pool_manager.get_stats()
        logger.info("pool_metrics", **pool_stats)

    # Memory aggregation
    if app.memory_aggregator:
        memory_stats = await app.memory_aggregator.get_stats()
        logger.info("memory_metrics", **memory_stats)

    # Observability
    if app.observability:
        app.observability.record_metrics(
            pool_stats=pool_stats,
            memory_stats=memory_stats,
        )

await scheduler.schedule_internal_task(
    collect_metrics_job,
    trigger_type="interval",
    seconds=60,
    id="mahavishnu-metrics",
)
```

---

## 🌐 Example 2: Infrastructure Scheduling (Oneiric)

### Scenario: Secret Rotation via Google Cloud Tasks

```yaml
# oneiric.yaml
adapters:
  queue:
    selection:
      default: "cloudtasks"
    provider_settings:
      cloudtasks:
        project: "my-project"
        location: "us-central1"
        queue: "mahavishnu-workflows"
```

```python
# Enqueue secret rotation
result = await scheduler.enqueue_workflow(
    workflow_key="rotate_secrets",
    queue_provider="cloudtasks",
    metadata={
        "schedule_time": "2026-02-07T02:00:00Z",
        "rotation_type": "jwt",
    },
    context={
        "secret_ids": ["jwt_secret", "api_key"],
    },
)

print(f"Task enqueued: {result['task_name']}")
# Output: Task enqueued: projects/PROJECT/locations/us-central1/queues/.../tasks/TASK_ID
```

### Scenario: Daily Backup via Redis Queue

```yaml
# oneiric.yaml
adapters:
  queue:
    provider_settings:
      redis:
        host: "localhost"
        port: 6379
        db: 0
        stream_name: "mahavishnu-workflows"
```

```python
result = await scheduler.enqueue_workflow(
    workflow_key="daily_backup",
    queue_provider="redis_streams",
    context={
        "repos": ["/path/to/repo1", "/path/to/repo2"],
        "backup_type": "full",
    },
    metadata={
        "priority": "high",
        "retention_days": 30,
    },
)
```

---

## 🎯 Example 3: User-Facing Workflows (Prefect)

### Scenario: Daily Code Quality Sweep

**`mahavishnu/workflows/code_sweep.py`**:

```python
from prefect import flow, task
from mahavishnu.core import MahavishnuApp

app = MahavishnuApp()

@flow(name="daily-code-sweep")
async def daily_sweep():
    """Sweep all repos for code quality issues."""
    repos = app.get_repos()

    results = []
    for repo in repos:
        result = await app.execute_workflow(
            task={"type": "code_sweep"},
            adapter_name="prefect",
            repos=[repo],
        )
        results.append(result)

    return results

# Deploy with schedule
from prefect.deployments import Deployment
from prefect.schedules import CronSchedule

deployment = Deployment.build(
    flow=daily_sweep,
    name="daily-sweep-prod",
    schedule=CronSchedule(cron="0 2 * * *"),  # Daily at 2 AM
    work_pool_name="mahavishnu-pool",
    tags=["production", "maintenance"],
)
await deployment.apply()
```

### Scenario: Weekly Dependency Audit

```python
@flow(name="weekly-dependency-audit")
async def dependency_audit():
    """Audit dependencies across all Python repos."""
    repos = app.get_repos(tag="python")

    results = []
    for repo in repos:
        result = await app.execute_workflow(
            task={"type": "dependency_audit"},
            adapter_name="prefect",
            repos=[repo],
        )
        results.append(result)

    # Aggregate results
    summary = aggregate_dependency_results(results)
    return summary

deployment = Deployment.build(
    flow=dependency_audit,
    name="dep-audit-prod",
    schedule=CronSchedule(cron="0 9 * * 1"),  # 9 AM Mondays
    work_pool_name="mahavishnu-pool",
)
await deployment.apply()
```

### Scenario: On-Demand ML Pipeline

```python
@flow(name="ml-pipeline")
async def ml_pipeline(
    dataset_path: str,
    model_name: str,
):
    """Train and evaluate ML model."""
    # Step 1: Preprocess
    data = await preprocess_dataset(dataset_path)

    # Step 2: Train
    model = await train_model(data, model_name)

    # Step 3: Evaluate
    metrics = await evaluate_model(model, data)

    return metrics

# Deploy without schedule (manual trigger only)
deployment = Deployment.build(
    flow=ml_pipeline,
    name="ml-pipeline-prod",
    work_pool_name="mahavishnu-pool",
    tags=["ml", "experimental"],
)
await deployment.apply()

# Trigger manually via:
# await ml_pipeline("dataset.csv", "model-v1")
```

---

## 🔧 Configuration Examples

### Full Mahavishnu Configuration

**`settings/mahavishnu.yaml`**:

```yaml
# Mahavishnu configuration
server_name: "Mahavishnu Orchestrator"

# Scheduling configuration
schedulers:
  # APScheduler (internal tasks)
  apscheduler_enabled: true
  apscheduler_jobstore: "memory"  # or "sqlite"

  # Oneiric queues (infrastructure)
  oneiric_queue_enabled: true
  default_queue_provider: "cloudtasks"

  # Prefect (user workflows)
  prefect_deployments_enabled: true
  prefect_server_url: "http://localhost:4200"

# Oneiric queue backend configuration
adapters:
  queue:
    selection:
      default: "cloudtasks"
    provider_settings:
      cloudtasks:
        project: "my-project"
        location: "us-central1"
        queue: "mahavishnu-workflows"
        schedule_offset_seconds: 0

      redis:
        host: "localhost"
        port: 6379
        db: 0
        stream_name: "mahavishnu-workflows"

      nats:
        url: "nats://localhost:4222"
        stream_name: "mahavishnu-workflows"
        subject: "workflows"

# Prefect configuration
prefect:
  api_url: "http://localhost:4200/api"
  work_pool_name: "mahavishnu-pool"
```

---

## 📊 Monitoring & Observability

### Adding Metrics to Scheduled Jobs

```python
# In scheduler.py
async def _health_check_job(self):
    """Health check with metrics."""
    start_time = time.time()

    try:
        is_healthy = await self.app.is_healthy()

        # Record metrics
        if self.app.observability:
            duration = time.time() - start_time
            self.app.observability.record_scheduled_job(
                job_name="health_check",
                duration_seconds=duration,
                success=is_healthy,
            )

        logger.info("health_check_completed",
                    healthy=is_healthy,
                    duration=duration)

    except Exception as e:
        logger.error("health_check_failed", error=str(e))

        # Record failure
        if self.app.observability:
            self.app.observability.record_scheduled_job(
                job_name="health_check",
                duration_seconds=time.time() - start_time,
                success=False,
                error=str(e),
            )
        raise
```

### Dashboard Queries (Grafana)

**APScheduler Job Status:**
```promql
# Number of successful health checks
rate(successful_health_checks_total[5m])

# Health check duration
avg_health_check_duration_seconds
```

**Oneiric Queue Depth:**
```promql
# Cloud Tasks queue depth
cloudtasks_queue_depth

# Redis Streams queue depth
redis_streams_queue_depth
```

**Prefect Flow Runs:**
```promql
# Prefect flow runs in last hour
prefect_flow_run_states_total{state_name="running"}

# Prefect flow success rate
rate(prefect_flow_run_succeeded_total[1h]) / rate(prefect_flow_run_finished_total[1h])
```

---

## 🚨 Error Handling Patterns

### Retry Logic for Scheduled Jobs

```python
async def robust_scheduled_task():
    """Task with retry logic."""
    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            # Do work
            result = await some_external_api_call()
            return result

        except TemporaryAPIError as e:
            retry_count += 1
            if retry_count >= max_retries:
                raise
            logger.warning("api_call_failed_retrying",
                        attempt=retry_count,
                        error=str(e))
            await asyncio.sleep(2 ** retry_count)  # Exponential backoff
```

### Dead Letter Queue Integration

```python
async def dlq_aware_scheduled_task():
    """Task with DLQ fallback."""
    try:
        result = await risky_operation()
        return result

    except Exception as exc:
        logger.error("operation_failed", error=str(exc))

        # Send to dead letter queue
        await app.dead_letter_queue.add(
            task="dlq_aware_scheduled_task",
            error=str(exc),
            context={"retry_count": 3},
        )
        raise
```

---

## 🧪 Testing Scheduled Tasks

### Test with Manual Triggering

```python
import pytest
from mahavishnu.core import MahavishnuScheduler

@pytest.mark.asyncio
async def test_scheduled_health_check():
    """Test health check scheduling."""
    app = MahavishnuApp()
    scheduler = MahavishnuScheduler(app)

    # Start scheduler
    await scheduler.start()

    try:
        # Manually trigger the job
        await scheduler._health_check_job()
        # Assert it ran successfully

    finally:
        await scheduler.stop()
```

### Test Schedule Configuration

```python
@pytest.mark.asyncio
async def test_schedule_internal_task():
    """Test scheduling an internal task."""
    app = MahavishnuApp()
    scheduler = MahavishnuScheduler(app)

    await scheduler.start()

    try:
        # Schedule a test job
        job_id = await scheduler.schedule_internal_task(
            lambda: print("test"),
            trigger_type="interval",
            seconds=1,
            id="test-job",
        )

        # Verify job exists
        job = scheduler._apscheduler.get_job(job_id)
        assert job is not None

    finally:
        await scheduler.stop()
```

---

## 📚 See Also

- **Selection Guide:** `docs/SCHEDULER_SELECTION_GUIDE.md`
- **Decision Matrix:** `docs/SCHEDULER_DECISION_MATRIX.md`
- **Implementation Plan:** `docs/HYBRID_SCHEDULER_IMPLEMENTATION_PLAN.md`
- **API Reference:** `mahavishnu/core/scheduler.py`
