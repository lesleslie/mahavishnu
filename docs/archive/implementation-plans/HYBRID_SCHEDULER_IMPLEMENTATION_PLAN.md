# Hybrid Scheduler Implementation Plan

## Executive Summary

Implement a three-tier hybrid scheduling architecture for Mahavishnu using:
- **APScheduler**: Internal, high-frequency, in-process tasks
- **Oneiric Queue Adapters**: Infrastructure scheduling with cloud backends
- **Prefect**: User-facing workflows with observability

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Mahavishnu Orchestrator                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              MahavishnuScheduler (Unified Interface)        │   │
│  │  • schedule_internal_task()  → APScheduler                 │   │
│  │  • enqueue_workflow()      → Oneiric Queue                 │   │
│  │  • schedule_deployment()   → Prefect Deployment            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                          │        │         │                      │
│         ┌────────────────┘        │         └────────────────┐     │
│         ▼                        ▼                         ▼     │
│  ┌──────────────┐      ┌──────────────┐         ┌──────────────┐ │
│  │ APScheduler  │      │  Oneiric     │         │   Prefect    │ │
│  │              │      │  Queue       │         │              │ │
│  │ • In-process │      │  Adapters    │         │ • Deployments│ │
│  │ • High-freq  │      │  (6 backends)│         │ • UI/observe  │ │
│  │ • Low-latency│      │  • CloudTasks│         │ • Retries    │ │
│  └──────────────┘      │  • Redis     │         │ • DAG orchest│ │
│                       │  • NATS      │         └──────────────┘ │
│                       │  • Kafka     │                          │
│                       └──────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Components

### 1. Core Scheduler Module

**File**: `mahavishnu/core/scheduler.py`

```python
class MahavishnuScheduler:
    """Unified scheduler interface for Mahavishnu."""

    def __init__(self, app: MahavishnuApp):
        self.app = app
        self.apscheduler = AsyncIOScheduler()
        self.oneiric_workflow_bridge = None  # Injected
        self.prefect_client = None  # Optional

    async def start(self):
        """Start all three schedulers."""
        await self._start_apscheduler()
        await self._start_oneiric_queues()
        await self._start_prefect_deployments()

    async def schedule_internal_task(
        self,
        func: Callable,
        trigger_type: Literal["interval", "cron", "date"],
        **trigger_kwargs
    ) -> str:
        """Schedule internal Mahavishnu task via APScheduler."""

    async def enqueue_workflow(
        self,
        workflow_key: str,
        queue_provider: str,
        **enqueue_kwargs
    ) -> dict[str, Any]:
        """Enqueue workflow via Oneiric queue adapter."""

    async def schedule_deployment(
        self,
        flow_name: str,
        schedule_config: ScheduleConfig,
        **deployment_kwargs
    ) -> str:
        """Create Prefect deployment with schedule."""
```

### 2. Task Classification System

**File**: `mahavishnu/core/scheduler_classifier.py`

```python
@dataclass
class TaskCharacteristics:
    """Characteristics for scheduler selection."""
    frequency: str  # "high", "medium", "low"
    visibility: str  # "internal", "user-facing"
    complexity: str  # "simple", "dag", "complex"
    durability: str  # "ephemeral", "persistent"
    infrastructure: str  # "local", "distributed"

def classify_task(
    task_name: str,
    characteristics: TaskCharacteristics
) -> Literal["apscheduler", "oneiric", "prefect"]:
    """Classify task and recommend scheduler."""
```

### 3. Configuration Integration

**File**: `mahavishnu/core/config.py` (extend existing)

```python
class SchedulerSettings(BaseModel):
    """Scheduler configuration."""

    # APScheduler
    apscheduler_enabled: bool = True
    apscheduler_jobstore: str = "memory"  # or "sqlite"

    # Oneiric queues
    oneiric_queue_enabled: bool = True
    default_queue_provider: str = "cloudtasks"  # or "redis", "nats"

    # Prefect
    prefect_deployments_enabled: bool = True
    prefect_server_url: str | None = None

class MahavishnuSettings(BaseSettings):
    """Extended settings."""
    schedulers: SchedulerSettings = Field(
        default_factory=SchedulerSettings
    )
```

---

## Implementation Tasks

### Phase 1: Core Infrastructure (Days 1-2)

- [ ] **Task 1.1**: Create `MahavishnuScheduler` class skeleton
- [ ] **Task 1.2**: Implement APScheduler integration
- [ ] **Task 1.3**: Wire Oneiric WorkflowBridge
- [ ] **Task 1.4**: Add Prefect deployment helper methods
- [ ] **Task 1.5**: Implement lifecycle management (start/stop)

### Phase 2: Internal Tasks (Days 3-4)

- [ ] **Task 2.1**: Health check scheduler job
- [ ] **Task 2.2**: Metrics collection job
- [ ] **Task 2.3**: Cache cleanup job
- [ ] **Task 2.4**: DLQ processing job
- [ ] **Task 2.5**: Secret rotation check job
- [ ] **Task 2.6**: Git polling job (if not already using code_index_service)

### Phase 3: Documentation (Days 5-6)

- [ ] **Task 3.1**: Write scheduler selection guide
- [ ] **Task 3.2**: Create decision matrix
- [ ] **Task 3.3**: Add usage examples
- [ ] **Task 3.4**: Document configuration options
- [ ] **Task 3.5**: Create troubleshooting guide

### Phase 4: Examples & Testing (Days 7-8)

- [ ] **Task 4.1**: Create example configurations
- [ ] **Task 4.2**: Integration tests for each scheduler
- [ ] **Task 4.3**: Performance benchmarks
- [ ] **Task 4.4**: End-to-end workflow examples

---

## File Structure

```
mahavishnu/
├── core/
│   ├── scheduler.py              # Main MahavishnuScheduler class
│   ├── scheduler_classifier.py   # Task classification logic
│   ├── config.py                 # Extended with SchedulerSettings
│   └── app.py                    # Initialize scheduler in MahavishnuApp
│
├── schedulers/
│   ├── __init__.py
│   ├── apscheduler_jobs.py       # Internal job definitions
│   ├── oneiric_helpers.py        # Oneiric queue helpers
│   └── prefect_helpers.py        # Prefect deployment helpers
│
├── docs/
│   ├── SCHEDULER_GUIDE.md        # When to use which scheduler
│   ├── SCHEDULER_DECISION_MATRIX.md  # Interactive decision tree
│   ├── SCHEDULER_EXAMPLES.md     # Usage examples
│   └── SCHEDULER_ARCHITECTURE.md # Architecture diagrams
│
├── examples/
│   ├── scheduler_basic.py        # Simple usage examples
│   ├── scheduler_advanced.py     # Advanced patterns
│   └── scheduler_migration.py    # Migrating from cron
│
└── tests/
    ├── unit/test_scheduler.py
    ├── integration/test_apscheduler.py
    ├── integration/test_oneiric_scheduler.py
    └── integration/test_prefect_scheduler.py
```

---

## Success Criteria

1. ✅ All three schedulers work independently without conflicts
2. ✅ Unified `MahavishnuScheduler` interface
3. ✅ Task classification system recommends correct scheduler 95%+ of time
4. ✅ Comprehensive documentation with decision matrix
5. ✅ 100% test coverage for scheduler selection logic
6. ✅ Performance benchmarks showing <100ms overhead for APScheduler jobs
7. ✅ Example configurations for common use cases

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| APScheduler event loop conflict | Ensure scheduler starts after asyncio loop is running |
| Oneiric queue adapter missing | Graceful fallback to APScheduler if queue unavailable |
| Prefect Server unavailable | Continue with APScheduler + Oneiric, log Prefect errors |
| Job ID collisions | Use prefixing: `apscheduler:`, `oneiric:`, `prefect:` |
| Memory leaks from job accumulation | Implement job limits and automatic cleanup |

---

## Rollout Plan

1. **Week 1**: Implement core infrastructure (Phase 1)
2. **Week 2**: Add internal tasks and docs (Phases 2-3)
3. **Week 3**: Testing and examples (Phase 4)
4. **Week 4**: Production rollout and monitoring

---

## Open Questions

1. Should we persist APScheduler jobs to SQLite for durability?
2. Do we need a unified job ID format across all three schedulers?
3. Should we implement a "fallback chain" (e.g., Prefect → Oneiric → APScheduler)?
4. How do we handle scheduler conflicts for the same workflow?
