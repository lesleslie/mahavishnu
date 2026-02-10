# Mahavishnu Scheduler Selection Guide

## 🎯 Quick Reference: Which Scheduler Should I Use?

Use this **decision tree** to choose the right scheduler for your task:

```
Need to schedule a task?
        │
        ▼
   ┌─────────────────┐
   │ User-visible?    │──── Yes → Use Prefect
   │ (UI, retries,    │            (Deployment + CronSchedule)
   │  observability) │
   └────────┬────────┘
            │ No
            ▼
   ┌─────────────────┐
   │ Infrastructure?  │──── Yes → Use Oneiric Queue
   │ (cloud backend,  │            (CloudTasks, Redis, NATS)
   │  distributed)    │
   └────────┬────────┘
            │ No
            ▼
   ┌─────────────────┐
   │ High-frequency?  │──── Yes → Use APScheduler
   │ (< 1 min interval)│            (In-process, fast)
   └────────┬────────┘
            │ No
            ▼
         Use APScheduler
      (Default fallback)
```

---

## 📊 Detailed Comparison

### **APScheduler** - Internal Mahavishnu Tasks

**Best For:**
- ✅ High-frequency tasks (< 1 minute intervals)
- ✅ Health checks, metrics collection
- ✅ Cache cleanup, maintenance jobs
- ✅ Tied to app lifecycle (stops when Mahavishnu stops)
- ✅ No external infrastructure needed
- ✅ Fast execution (< 100ms overhead)
- ✅ Offline development/testing

**Use Cases:**
```python
# Health check every 30 seconds
await scheduler.schedule_internal_task(
    health_check,
    trigger_type="interval",
    seconds=30,
    id="health-check",
)

# Cache cleanup hourly
await scheduler.schedule_internal_task(
    cleanup_cache,
    trigger_type="cron",
    hour="*",  # Every hour
    id="cache-cleanup",
)
```

**When NOT to use:**
- ❌ User-facing workflows (no UI/observability)
- ❌ Long-running tasks (> 5 minutes)
- ❌ Tasks requiring distributed execution
- ❌ Tasks that must survive app restarts

---

### **Oneiric Queue Adapters** - Infrastructure Scheduling

**Best For:**
- ✅ Infrastructure tasks (backups, rotations)
- ✅ Distributed execution across machines
- ✅ Cloud-based scheduling (Google Cloud Tasks)
- ✅ Fire-and-forget tasks
- ✅ Tasks surviving app restarts
- ✅ Queue backends: Redis, NATS, Kafka, RabbitMQ

**Available Backends:**

| Backend | Best For | Features |
|---------|----------|----------|
| **CloudTasks** | Serverless scheduling | Built-in cron, pay-per-use |
| **Redis Streams** | Simple queue | Fast, lightweight |
| **NATS JetStream** | Cloud-native | Durable, scalable |
| **Kafka** | High-throughput | Distributed logs |
| **RabbitMQ** | Enterprise | Reliable, feature-rich |

**Use Cases:**
```python
# Schedule secret rotation via Google Cloud Tasks
result = await scheduler.enqueue_workflow(
    "rotate_secrets",
    queue_provider="cloudtasks",
    metadata={"schedule_time": "2026-02-07T02:00:00Z"},
)

# Enqueue backup job to Redis
result = await scheduler.enqueue_workflow(
    "daily_backup",
    queue_provider="redis",
    context={"repos": ["/path/to/repo"]},
)
```

**When NOT to use:**
- ❌ High-frequency tasks (< 1 minute) - use APScheduler instead
- ❌ User-visible workflows - use Prefect instead
- ❌ Tasks requiring observability/UI

---

### **Prefect** - User-Facing Workflows

**Best For:**
- ✅ User-visible workflows with UI dashboard
- ✅ Complex DAG orchestration
- ✅ Workflows requiring retries and state tracking
- ✅ Cross-repo coordination
- ✅ Production-grade observability
- ✅ Long-running workflows (minutes to hours)

**Features:**
- 🎨 Prefect UI/Cloud dashboard
- 🔄 Automatic retry with exponential backoff
- 📊 State tracking and history
- 🚀 Distributed execution via agents
- 📈 OpenTelemetry observability

**Use Cases:**
```python
# Create Prefect deployment with schedule
from prefect import flow
from prefect.deployments import Deployment

@flow(name="daily-code-sweep")
async def daily_sweep():
    repos = app.get_repos()
    result = await app.execute_workflow(
        task={"type": "code_sweep"},
        adapter_name="prefect",
        repos=repos,
    )
    return result

# Deploy with daily 2 AM schedule
deployment = Deployment.build(
    flow=daily_sweep,
    name="daily-sweep-prod",
    schedule=CronSchedule(cron="0 2 * * *"),
    work_pool_name="mahavishnu-pool",
)
await deployment.apply()
```

**When NOT to use:**
- ❌ Simple internal tasks - overkill
- ❌ High-frequency checks (< 1 minute) - use APScheduler
- ❌ Tasks without observability needs

---

## 🎯 Task Classification Examples

### **Example 1: Health Check**

**Characteristics:**
- Frequency: High (every 30s)
- Visibility: Internal
- Complexity: Simple
- Durability: Ephemeral
- Infrastructure: Local

**Decision:** APScheduler ✅

```python
await scheduler.schedule_internal_task(
    health_check,
    trigger_type="interval",
    seconds=30,
)
```

---

### **Example 2: Daily Code Sweep**

**Characteristics:**
- Frequency: Low (daily)
- Visibility: User-facing
- Complexity: DAG (multiple repos)
- Durability: Persistent
- Infrastructure: Distributed
- Requires observability: Yes
- Requires UI: Yes

**Decision:** Prefect ✅

```python
deployment = Deployment.build(
    flow=daily_sweep,
    name="daily-sweep",
    schedule=CronSchedule(cron="0 2 * * *"),
)
await deployment.apply()
```

---

### **Example 3: Secret Rotation**

**Characteristics:**
- Frequency: Low (every 90 days)
- Visibility: Internal
- Complexity: Simple
- Durability: Persistent
- Infrastructure: Distributed (must survive restarts)

**Decision:** Oneiric (CloudTasks) ✅

```python
await scheduler.enqueue_workflow(
    "rotate_secrets",
    queue_provider="cloudtasks",
    metadata={"schedule_time": "2026-02-07T02:00:00Z"},
)
```

---

## 📋 Decision Checklist

Use this checklist to classify your task:

```
□ Task runs more frequently than once per minute?
  └─ Yes → Use APScheduler

□ Task needs to be visible in Prefect UI?
  └─ Yes → Use Prefect

□ Task requires complex retry logic/state tracking?
  └─ Yes → Use Prefect

□ Task must survive Mahavishnu restarts?
  └─ Yes → Use Oneiric Queue

□ Task is infrastructure-related (backups, rotations)?
  └─ Yes → Use Oneiric Queue

□ Task is simple, fast, and internal?
  └─ Yes → Use APScheduler

□ Task coordinates across multiple repositories?
  └─ Yes → Use Prefect
```

---

## 🔄 Migration Guide

### **From Cron to Mahavishnu Schedulers**

**Old (Cron):**
```bash
# crontab
*/30 * * * * /path/to/health_check.sh
0 * * * * /path/to/collect_metrics.sh
```

**New (Mahavishnu):**
```python
# health_check every 30s
await scheduler.schedule_internal_task(
    health_check,
    trigger_type="interval",
    seconds=30,
)

# metrics every hour
await scheduler.schedule_internal_task(
    collect_metrics,
    trigger_type="cron",
    hour="*",
)
```

---

## 🚀 Best Practices

### **1. Always Use Lifecycle Manager**

```python
async with scheduler.lifecycle():
    # Schedulers are running
    # Do your work here
    pass
# Automatically cleaned up
```

### **2. Add Unique Job IDs**

```python
await scheduler.schedule_internal_task(
    my_task,
    trigger_type="interval",
    seconds=60,
    id="my-unique-task-id",  # Prevents duplicates
)
```

### **3. Handle Errors in Scheduled Jobs**

```python
async def my_scheduled_task():
    try:
        # Do work
        pass
    except Exception as e:
        logger.error("task_failed", error=str(e))
        # Optionally send alert
```

### **4. Use Task Classification for Complex Tasks**

```python
characteristics = TaskCharacteristics(
    frequency="low",
    visibility="user-facing",
    complexity="dag",
    durability="persistent",
    infrastructure="distributed",
)

scheduler = classify_task("my_workflow", characteristics)
# Returns: "prefect"
```

---

## 📖 See Also

- **Scheduler Architecture:** `docs/HYBRID_SCHEDULER_IMPLEMENTATION_PLAN.md`
- **Committee Review:** `docs/SCHEDULER_COMMITTEE_REVIEW.md`
- **Code Reference:** `mahavishnu/core/scheduler.py`
- **Decision Matrix:** `docs/SCHEDULER_DECISION_MATRIX.md`
