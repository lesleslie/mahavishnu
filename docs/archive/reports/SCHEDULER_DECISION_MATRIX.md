# Scheduler Decision Matrix

## 🎯 Interactive Decision Tree

Answer the questions below to find the right scheduler for your task.

---

## Step 1: Task Visibility

### **Question**: Is this task user-facing?

**Consider:**
- Will users want to see this in a dashboard?
- Does it need observability (UI, graphs, history)?
- Will users trigger it manually?

#### YES → Use **Prefect**

```python
from prefect import flow
from prefect.deployments import Deployment
from prefect.schedules import CronSchedule

@flow(name="user-workflow")
async def user_workflow():
    # Your workflow logic
    pass

# Deploy with schedule
deployment = Deployment.build(
    flow=user_workflow,
    name="user-workflow-prod",
    schedule=CronSchedule(cron="0 2 * * *"),  # Daily at 2 AM
)
await deployment.apply()
```

**Use Cases:**
- Daily code quality sweep
- Weekly dependency audit
- ML pipeline runs
- Report generation

---

#### NO → Continue to Step 2

---

## Step 2: Infrastructure Requirements

### **Question**: Does this task require distributed execution?

**Consider:**
- Must it run on multiple machines?
- Does it need to survive app restarts?
- Is it infrastructure-related (backups, rotations)?

#### YES → Use **Oneiric Queue Adapter**

```python
result = await scheduler.enqueue_workflow(
    workflow_key="my_workflow",
    queue_provider="cloudtasks",  # or "redis", "nats", "kafka", "rabbitmq"
    context={"repos": ["/path/to/repo"]},
    metadata={"schedule_time": "2026-02-07T02:00:00Z"},
)
```

**Queue Backend Selection:**

| Backend | Use When | Schedule Support |
|---------|----------|-----------------|
| **CloudTasks** | Need serverless scheduling | ✅ Built-in cron |
| **Redis Streams** | Simple queue, fast | ❌ External scheduler |
| **NATS JetStream** | Cloud-native, durable | ❌ External scheduler |
| **Kafka** | High-throughput, logs | ❌ External scheduler |
| **RabbitMQ** | Enterprise, reliable | ❌ External scheduler |

**Use Cases:**
- Secret rotation (every 90 days)
- Database backups (daily)
- Log aggregation (hourly)
- Security scans (weekly)

---

#### NO → Continue to Step 3

---

## Step 3: Execution Frequency

### **Question**: How often does this task run?

#### **High Frequency** (< 1 minute) → Use **APScheduler**

```python
# Health check every 30 seconds
await scheduler.schedule_internal_task(
    health_check,
    trigger_type="interval",
    seconds=30,
    id="health-check",
)
```

**Use Cases:**
- Health checks (every 30s)
- Heartbeat monitoring (every 10s)
- Cache warming (every 45s)

#### **Medium Frequency** (1-60 minutes) → Use **APScheduler**

```python
# Metrics collection every minute
await scheduler.schedule_internal_task(
    collect_metrics,
    trigger_type="interval",
    seconds=60,
    id="metrics",
)

# Cache cleanup every hour
await scheduler.schedule_internal_task(
    cleanup_cache,
    trigger_type="cron",
    hour="*",
    id="cache-cleanup",
)
```

#### **Low Frequency** (> 1 hour) → Evaluate further

Continue to Step 4...

---

## Step 4: Task Complexity

### **Question**: Is this a complex workflow?

**Consider:**
- Does it have multiple steps with dependencies?
- Does it need DAG orchestration?
- Does it coordinate across multiple repos?

#### YES → Use **Prefect**

```python
@flow(name="complex-etl")
async def complex_etl():
    # Step 1: Extract
    data = await extract_step()
    # Step 2: Transform (depends on Step 1)
    transformed = await transform_step(data)
    # Step 3: Load (depends on Step 2)
    await load_step(transformed)

deployment = Deployment.build(
    flow=complex_etl,
    name="complex-etl-prod",
    schedule=CronSchedule(cron="0 6 * * 1"),  # 6 AM Mondays
)
await deployment.apply()
```

---

#### NO → Use **APScheduler**

```python
# Simple internal task
await scheduler.schedule_internal_task(
    simple_task,
    trigger_type="cron",
    hour="2",
    minute="0",
    id="simple-task",
)
```

---

## 📊 Quick Reference Table

| Task Type | Frequency | Visibility | Complexity | Scheduler |
|------------|-----------|------------|------------|-----------|
| Health checks | 30s | Internal | Simple | **APScheduler** |
| Metrics collection | 1m | Internal | Simple | **APScheduler** |
| Cache cleanup | 1h | Internal | Simple | **APScheduler** |
| DLQ processing | 5m | Internal | Simple | **APScheduler** |
| Secret rotation | 90d | Internal | Simple | **Oneiric** |
| Database backup | Daily | Internal | Simple | **Oneiric** |
| Log aggregation | Hourly | Internal | Simple | **Oneiric** |
| Code sweep | Daily | User | DAG | **Prefect** |
| Dependency audit | Weekly | User | DAG | **Prefect** |
| ML pipeline | Ad-hoc | User | Complex | **Prefect** |
| ETL workflow | Scheduled | User | Complex | **Prefect** |

---

## 🎯 Real-World Examples

### **Example 1: Health Monitoring**

```python
# Runs every 30 seconds, internal only
await scheduler.schedule_internal_task(
    check_system_health,
    trigger_type="interval",
    seconds=30,
    id="health-check",
)
```

**Rationale:**
- High frequency (30s)
- Internal visibility
- Simple execution
- **Scheduler: APScheduler** ✅

---

### **Example 2: Daily Backup**

```python
# Runs daily at 2 AM, survives restarts
result = await scheduler.enqueue_workflow(
    "daily_backup",
    queue_provider="cloudtasks",
    metadata={"schedule_time": "2026-02-07T02:00:00Z"},
    context={"repos": all_repos},
)
```

**Rationale:**
- Low frequency (daily)
- Must survive restarts
- Infrastructure task
- **Scheduler: Oneiric (CloudTasks)** ✅

---

### **Example 3: User Code Sweep**

```python
@flow(name="daily-code-sweep")
async def code_sweep():
    repos = app.get_repos()
    return await app.execute_workflow(
        task={"type": "code_sweep"},
        repos=repos,
    )

deployment = Deployment.build(
    flow=code_sweep,
    name="code-sweep-prod",
    schedule=CronSchedule(cron="0 2 * * *"),
)
await deployment.apply()
```

**Rationale:**
- User-facing (visible in Prefect UI)
- DAG orchestration (multiple repos)
- Needs observability
- **Scheduler: Prefect** ✅

---

## 🔄 Decision Flowchart (Visual)

```
                    START
                      │
          ┌─────────────┴─────────────┐
          │   Is task user-visible?    │
          └─────────────┬─────────────┘
                        │
           ┌────────────┴────────────┐
           │ YES                       │ NO
           ▼                           ▼
      Use Prefect           ┌──────────┴──────────┐
                          │   Needs distributed? │
                          └──────────┬──────────┘
                                     │
                          ┌────────────┴────────────┐
                          │ YES                       │ NO
                          ▼                           ▼
                     Use Oneiric              ┌──────────┴──────────┐
                                             │   Frequency?         │
                                             ├─────────────────────┤
                                             │ < 1min                │
                                             │ 1min - 1hr            │
                                             │ > 1hr                │
                                             ▼                       ▼
                                          APScheduler           Evaluate Complexity
```

---

## ✅ Validation Checklist

Before scheduling a task, verify:

### **APScheduler Tasks:**
- [ ] Runs in same process as Mahavishnu
- [ ] No external dependencies required
- [ ] Fast execution (< 5 seconds)
- [ ] Can be lost if Mahavishnu crashes

### **Oneiric Queue Tasks:**
- [ ] Needs queue backend (Redis/CloudTasks/etc.)
- [ ] Must survive app restarts
- [ ] Infrastructure-related
- [ ] Fire-and-forget acceptable

### **Prefect Tasks:**
- [ ] User needs visibility
- [ ] Requires observability
- [ ] Complex workflow/DAG
- [ ] Needs retry logic

---

## 🚫 Common Mistakes

### ❌ **Don't Use Prefect For:**
- Simple health checks (overkill)
- High-frequency checks (< 1 minute)
- Internal maintenance tasks
- Tasks without observability needs

### ❌ **Don't Use APScheduler For:**
- User-facing workflows (no UI)
- Long-running tasks (> 5 minutes)
- Tasks needing distributed execution
- Tasks requiring durability

### ❌ **Don't Use Oneiric For:**
- High-frequency tasks (< 1 minute)
- Tasks requiring observability
- User-visible workflows
- Simple in-process tasks

---

## 📚 Related Documentation

- **Selection Guide:** `docs/SCHEDULER_SELECTION_GUIDE.md`
- **Implementation Plan:** `docs/HYBRID_SCHEDULER_IMPLEMENTATION_PLAN.md`
- **Committee Review:** `docs/SCHEDULER_COMMITTEE_REVIEW.md`
- **API Reference:** `mahavishnu/core/scheduler.py`
