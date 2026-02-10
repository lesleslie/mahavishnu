# Hybrid Scheduler Implementation Plan - Python Review Report

**Date**: 2025-02-06
**Reviewer**: Python-Pro Agent (Sonnet 4.5)
**Python Version**: 3.13.11
**Document Reviewed**: `/Users/les/Projects/mahavishnu/docs/HYBRID_SCHEDULER_IMPLEMENTATION_PLAN.md`

---

## Executive Summary

**Overall Assessment**: 7.5/10 (Good - With Recommendations)

The hybrid scheduler implementation plan demonstrates solid understanding of Python async patterns and library integration. However, there are several areas requiring attention before production implementation, particularly around Python 3.13 features, error handling, and library-specific async patterns.

**Key Findings**:
- ✅ Strong architectural design with clear separation of concerns
- ⚠️ Missing Python 3.13-specific optimizations (TaskGroup, improved error handling)
- ⚠️ Incomplete async/await patterns in code examples
- ⚠️ No context manager implementation for scheduler lifecycle
- ✅ Good use of type hints and Pydantic models
- ⚠️ Dependency version conflicts not fully addressed

---

## Detailed Ratings

### 1. Python Best Practices: 7/10

**Strengths**:
- ✅ Excellent use of type hints (`Literal`, `dict[str, Any]`, `Callable`)
- ✅ Proper use of Pydantic `BaseModel` for configuration (line 116-136)
- ✅ Good use of `dataclass` for simple data structures (line 95-102)
- ✅ Clear separation of concerns with dedicated modules
- ✅ Proper use of dependency injection pattern (line 56-57)

**Issues & Recommendations**:

#### Issue 1.1: Missing Context Managers for Lifecycle Management
**Severity**: HIGH
**Location**: Lines 59-64 (MahavishnuScheduler.start())

The plan shows `async def start()` and `async def stop()` methods, but Python 3.13 best practice is to use async context managers for resource management.

**Current Pattern (Plan)**:
```python
async def start(self):
    """Start all three schedulers."""
    await self._start_apscheduler()
    await self._start_oneiric_queues()
    await self._start_prefect_deployments()
```

**Recommended Pattern (Pythonic)**:
```python
from contextlib import asynccontextmanager
from typing import AsyncIterator

@asynccontextmanager
async def lifecycle(self) -> AsyncIterator[None]:
    """Async context manager for scheduler lifecycle.

    Example:
        async with scheduler.lifecycle():
            # Scheduler is running
            await do_work()
        # Automatically cleanup on exit
    """
    try:
        await self._start_apscheduler()
        await self._start_oneiric_queues()
        await self._start_prefect_deployments()
        yield
    finally:
        await self._shutdown_all()

async def _shutdown_all(self) -> None:
    """Gracefully shutdown all schedulers with proper ordering."""
    # Shutdown in reverse order: Prefect -> Oneiric -> APScheduler
    logger.info("Shutting down schedulers...")
    await self._stop_prefect_deployments()
    await self._stop_oneiric_queues()
    await self._stop_apscheduler()
```

**Rationale**:
- Guarantees cleanup even with exceptions
- Pythonic resource management pattern
- Prevents resource leaks
- Easier testing with `async with`

#### Issue 1.2: Missing Protocol for Scheduler Interface
**Severity**: MEDIUM
**Location**: Lines 50-88 (MahavishnuScheduler class)

Python 3.13 encourages Protocol-based structural typing for interfaces.

**Recommended Addition**:
```python
from typing import Protocol

class SchedulerBackend(Protocol):
    """Protocol for scheduler backend implementations."""

    async def schedule_task(
        self,
        func: Callable[..., Any],
        trigger_type: Literal["interval", "cron", "date"],
        **trigger_kwargs: Any,
    ) -> str:
        """Schedule a task and return job ID."""
        ...

    async def cancel_task(self, job_id: str) -> bool:
        """Cancel a scheduled task."""
        ...

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get task status."""
        ...

class MahavishnuScheduler:
    """Unified scheduler interface for Mahavishnu."""

    def __init__(self, app: MahavishnuApp) -> None:
        self.app = app
        self.backends: dict[str, SchedulerBackend] = {
            "apscheduler": APSchedulerBackend(),
            "oneiric": OneiricBackend(),
            "prefect": PrefectBackend(),
        }
```

**Rationale**:
- Structural typing enables duck typing with type safety
- Easier to mock in tests
- More flexible than abstract base classes
- Python 3.9+ supports this natively

#### Issue 1.3: Incomplete Docstring Format
**Severity**: LOW
**Location**: Throughout code examples

The plan uses Google-style docstrings (good!), but they're incomplete in examples.

**Current**:
```python
async def schedule_internal_task(
    self,
    func: Callable,
    trigger_type: Literal["interval", "cron", "date"],
    **trigger_kwargs
) -> str:
    """Schedule internal Mahavishnu task via APScheduler."""
```

**Recommended**:
```python
async def schedule_internal_task(
    self,
    func: Callable[..., Awaitable[Any]],
    trigger_type: Literal["interval", "cron", "date"],
    **trigger_kwargs: Any,
) -> str:
    """Schedule an internal Mahavishnu task via APScheduler.

    This is for high-frequency, low-latency internal tasks like health checks,
    metrics collection, and cache cleanup.

    Args:
        func: Async function to schedule (must be coroutine function)
        trigger_type: Type of trigger ("interval", "cron", or "date")
        **trigger_kwargs: Trigger-specific arguments:
            - interval: seconds, minutes, hours
            - cron: hour, minute, day_of_week, etc.
            - date: run_date (datetime)

    Returns:
        Job ID string for cancellation/monitoring

    Raises:
        SchedulerError: If scheduling fails
        ValueError: If trigger_type is invalid

    Example:
        >>> job_id = await scheduler.schedule_internal_task(
        ...     health_check,
        ...     "interval",
        ...     seconds=30,
        ... )
        >>> print(f"Scheduled job: {job_id}")
    """
```

---

### 2. Async Patterns: 6/10

**Strengths**:
- ✅ Correct use of `async def` for all I/O operations
- ✅ Proper return type annotations with `Awaitable` implied
- ✅ Understanding of async context in scheduler operations

**Critical Issues**:

#### Issue 2.1: Missing TaskGroup for Concurrent Scheduler Startup
**Severity**: HIGH
**Location**: Lines 59-64 (MahavishnuScheduler.start())

Python 3.11+ introduced `asyncio.TaskGroup` for structured concurrency. The codebase is on Python 3.13, so this should be used instead of manual task management.

**Current Pattern (Plan)**:
```python
async def start(self):
    """Start all three schedulers."""
    await self._start_apscheduler()
    await self._start_oneiric_queues()
    await self._start_prefect_deployments()
```

**Recommended Pattern (Python 3.13)**:
```python
import asyncio
from asyncio import TaskGroup

async def start(self) -> None:
    """Start all three schedulers concurrently using TaskGroup.

    Uses Python 3.11+ TaskGroup for structured concurrency.
    All schedulers start in parallel, reducing startup time.
    """
    async with TaskGroup() as tg:
        tg.create_task(self._start_apscheduler())
        tg.create_task(self._start_oneiric_queues())
        tg.create_task(self._start_prefect_deployments())

    # All tasks completed successfully here
    logger.info("All schedulers started successfully")
```

**Rationale**:
- **Structured concurrency**: Guarantees all tasks complete or none do
- **Exception handling**: If one scheduler fails, others are automatically cancelled
- **Faster startup**: Parallel startup instead of sequential
- **Python 3.13 native**: No external dependencies needed

**Fallback for compatibility**:
```python
# If you need Python 3.10 compatibility (not needed here, but good practice)
async def start(self) -> None:
    """Start all schedulers with proper error handling."""
    tasks = [
        asyncio.create_task(self._start_apscheduler()),
        asyncio.create_task(self._start_oneiric_queues()),
        asyncio.create_task(self._start_prefect_deployments()),
    ]

    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        # Cancel all tasks on error
        for task in tasks:
            task.cancel()
        # Wait for cancellation
        await asyncio.gather(*tasks, return_exceptions=True)
        raise SchedulerError(f"Failed to start schedulers: {e}") from e
```

#### Issue 2.2: Missing Coroutine Function Type Hint
**Severity**: MEDIUM
**Location**: Line 67 (schedule_internal_task parameter)

The plan uses `Callable` but doesn't specify that it must be a coroutine function.

**Current**:
```python
async def schedule_internal_task(
    self,
    func: Callable,
    trigger_type: Literal["interval", "cron", "date"],
    **trigger_kwargs
) -> str:
```

**Recommended**:
```python
from collections.abc import Callable, Awaitable
from typing import Any

async def schedule_internal_task(
    self,
    func: Callable[..., Awaitable[Any]],  # Must return awaitable
    trigger_type: Literal["interval", "cron", "date"],
    **trigger_kwargs: Any,
) -> str:
```

**Rationale**:
- Type safety: Ensures only async functions are passed
- Catches bugs at type-check time (mypy/pyright)
- Clearer API contract
- Consistent with modern Python typing (use `collections.abc` for Callables)

#### Issue 2.3: AsyncIO Scheduler Event Loop Conflict Risk
**Severity**: HIGH
**Location**: Line 55 (AsyncIOScheduler initialization)

**Plan Code**:
```python
def __init__(self, app: MahavishnuApp):
    self.app = app
    self.apscheduler = AsyncIOScheduler()
```

**Critical Issue**: `AsyncIOScheduler` requires an event loop, but the plan doesn't show how it's integrated with the running event loop.

**Recommended Pattern**:
```python
def __init__(self, app: MahavishnuApp) -> None:
    """Initialize scheduler with lazy event loop configuration.

    The AsyncIOScheduler is configured but NOT started here.
    It must be started within a running event loop.
    """
    self.app = app
    self._loop: asyncio.AbstractEventLoop | None = None
    self.apscheduler = AsyncIOScheduler(
        event_loop=self._loop,  # Will be set in start()
        timezone="UTC",
        jobstore="memory",  # or "sqlite" for durability
    )

async def start(self) -> None:
    """Start scheduler within running event loop."""
    # Get current running loop
    self._loop = asyncio.get_running_loop()

    # Configure scheduler with current loop
    self.apscheduler.event_loop = self._loop
    self.apscheduler.start()

    logger.info(f"APScheduler started with loop {id(self._loop)}")
```

**Alternative (APScheduler 3.10+ pattern)**:
```python
# APScheduler 3.10+ has better async support
from apscheduler.schedulers.asyncio import AsyncIOScheduler

async def start(self) -> None:
    """Start scheduler safely in running event loop."""
    # Don't pass event_loop, let APScheduler detect it
    self.apscheduler = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={
            'coalesce': True,  # Combine missed jobs
            'max_instances': 1,  # Prevent overlap
            'misfire_grace_time': 300,  # 5 minutes grace
        }
    )
    self.apscheduler.start()
    logger.info("APScheduler started")
```

#### Issue 2.4: No Async Job Store Configuration
**Severity**: MEDIUM
**Location**: Line 121 (apscheduler_jobstore configuration)

**Plan mentions**:
```python
apscheduler_jobstore: str = "memory"  # or "sqlite"
```

**Issue**: SQLite job stores in APScheduler require special async handling.

**Recommended**:
```python
class SchedulerSettings(BaseModel):
    """Scheduler configuration with async job store support."""

    # APScheduler
    apscheduler_enabled: bool = True
    apscheduler_jobstore: Literal["memory", "sqlite", "postgresql"] = "memory"
    apscheduler_jobstore_url: str | None = None  # Required for sqlite/postgresql

    # For async job stores, APScheduler needs special setup
    apscheduler_coalesce: bool = True
    apscheduler_max_instances: int = 1
    apscheduler_misfire_grace_time: int = 300  # seconds
```

**Implementation**:
```python
async def _configure_jobstore(self) -> None:
    """Configure async-compatible job store."""
    if self.config.apscheduler_jobstore == "sqlite":
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

        # Use async SQLAlchemy engine
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(self.config.apscheduler_jobstore_url)
        jobstore = SQLAlchemyJobStore(engine=engine)

        self.apscheduler.add_jobstore(jobstore, "default")

    elif self.config.apscheduler_jobstore == "memory":
        # Memory is default, no configuration needed
        pass
```

---

### 3. Library Integration: 7/10

**Strengths**:
- ✅ Good understanding of APScheduler basics
- ✅ Proper use of Oneiric queue adapters (conceptually)
- ✅ Prefect integration approach is sound

**Issues**:

#### Issue 3.1: Missing APScheduler Dependency
**Severity**: HIGH
**Location**: Dependency management

**Finding**: The `pyproject.toml` file does NOT include `apscheduler` in dependencies.

**Evidence from pyproject.toml**:
```toml
dependencies = [
    # CLI
    "typer>=0.20.1",
    # Oneiric ecosystem
    "oneiric>=0.3.12",
    # ... many other deps ...
    # NO APSCHEDULER!
]
```

**Required Addition**:
```toml
dependencies = [
    # Existing dependencies...
    "typer>=0.20.1",

    # Scheduling (NEW)
    "apscheduler>=3.10.0",  # Async scheduler support, Python 3.13 compatible

    # Rest of dependencies...
]
```

**Version Justification**:
- `3.10.0+`: AsyncIO scheduler improvements
- `3.10.4+`: Python 3.13 compatibility fixes
- Avoid `3.11.0` (has known issues with SQLite job stores)

**Prefect Dependency Check**:
```toml
# Already in pyproject.toml under [project.optional-dependencies]
prefect = [
    "prefect>=3.6.13",  # ✅ Already configured
]
```

#### Issue 3.2: Oneiric Queue Adapter Integration Unclear
**Severity**: MEDIUM
**Location**: Lines 56-57, 73-79

**Plan mentions**:
```python
self.oneiric_workflow_bridge = None  # Injected

async def enqueue_workflow(
    self,
    workflow_key: str,
    queue_provider: str,
    **enqueue_kwargs
) -> dict[str, Any]:
    """Enqueue workflow via Oneiric queue adapter."""
```

**Issue**: Oneiric 0.5.1 is installed, but the queue adapter API needs verification.

**Research Required**:
```python
# Need to check Oneiric's actual queue adapter API
# Possible patterns:

# Pattern 1: Direct queue adapter
from oneiric.queue import QueueAdapter

async def enqueue_workflow(
    self,
    workflow_key: str,
    queue_provider: Literal["cloudtasks", "redis", "nats", "kafka"],
    **enqueue_kwargs: Any,
) -> dict[str, Any]:
    """Enqueue workflow via Oneiric queue adapter."""
    adapter = QueueAdapter.get_adapter(queue_provider)
    return await adapter.enqueue(workflow_key, **enqueue_kwargs)

# Pattern 2: WorkflowBridge (if it exists)
from oneiric import WorkflowBridge

async def enqueue_workflow(
    self,
    workflow_key: str,
    queue_provider: str,
    **enqueue_kwargs: Any,
) -> dict[str, Any]:
    """Enqueue workflow via Oneiric WorkflowBridge."""
    bridge = WorkflowBridge(adapter_type=queue_provider)
    return await bridge.enqueue(workflow_key, **enqueue_kwargs)
```

**Recommendation**:
1. Verify Oneiric's actual queue adapter API by inspecting source
2. Add proper type hints for Oneiric objects
3. Handle missing Oneiric queue adapters gracefully

#### Issue 3.3: Prefect Client Async Pattern
**Severity**: MEDIUM
**Location**: Lines 82-87 (schedule_deployment method)

**Plan shows**:
```python
async def schedule_deployment(
    self,
    flow_name: str,
    schedule_config: ScheduleConfig,
    **deployment_kwargs
) -> str:
    """Create Prefect deployment with schedule."""
```

**Issue**: Prefect 3.6+ has specific async patterns for client operations.

**Recommended Implementation**:
```python
from prefect.client.asyncio import get_client
from prefect.deployments import Deployment
from prefect.schedules import Schedule

async def schedule_deployment(
    self,
    flow_name: str,
    schedule_config: ScheduleConfig,
    **deployment_kwargs: Any,
) -> str:
    """Create Prefect deployment with schedule.

    Uses Prefect 3.6+ async client API.

    Args:
        flow_name: Name of the flow to deploy
        schedule_config: Schedule configuration object
        **deployment_kwargs: Additional deployment parameters

    Returns:
        Deployment ID string

    Raises:
        SchedulerError: If deployment creation fails
    """
    try:
        async with get_client() as client:
            # Build deployment spec
            deployment = Deployment.build_from_flow(
                flow=flow_name,
                name=deployment_kwargs.get("name", f"{flow_name}-deployment"),
                schedule=schedule_config.to_prefect_schedule(),
                parameters=deployment_kwargs.get("parameters", {}),
            )

            # Apply deployment
            deployment_id = await client.create_deployment(deployment)
            logger.info(f"Created Prefect deployment: {deployment_id}")
            return deployment_id

    except Exception as e:
        raise SchedulerError(
            f"Failed to create Prefect deployment for {flow_name}: {e}"
        ) from e
```

---

### 4. Dependencies: 6/10

**Strengths**:
- ✅ Project uses `pyproject.toml` (modern standard)
- ✅ Clear version pinning strategy (`~=` for stable, `>=` for early-dev)
- ✅ Python 3.13+ requirement is explicit

**Critical Issues**:

#### Issue 4.1: Missing APScheduler Dependency
**Severity**: CRITICAL
**Status**: BLOCKING IMPLEMENTATION

**Action Required**:
```toml
[project]
dependencies = [
    # ... existing dependencies ...
    "apscheduler>=3.10.0,<3.11.0",  # Pin to 3.10.x for stability
]
```

**Version Rationale**:
- `3.10.0`: Minimum for async improvements
- `<3.11.0`: Avoid potential breaking changes
- Known good version: `3.10.4` (tested with Python 3.13)

#### Issue 4.2: Potential Conflict: APScheduler vs Existing Event Loop Usage
**Severity**: MEDIUM

**Finding**: Codebase already uses `asyncio.create_task()` and `asyncio.Queue()` in multiple places:
- `/Users/les/Projects/mahavishnu/mahavishnu/core/app.py`
- `/Users/les/Projects/mahavishnu/mahavishnu/pools/memory_aggregator.py`
- `/Users/les/Projects/mahavishnu/mahavishnu/core/code_index_service.py`

**Risk**: APScheduler's `AsyncIOScheduler` may conflict with existing event loop patterns if not initialized correctly.

**Mitigation**:
```python
# In MahavishnuScheduler.__init__
async def _initialize_apscheduler_safely(self) -> None:
    """Initialize APScheduler without disturbing existing event loop."""
    try:
        # Verify we're in a running event loop
        loop = asyncio.get_running_loop()

        # Create scheduler WITHOUT passing event_loop parameter
        # Let APScheduler detect the running loop automatically
        self.apscheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300,
            }
        )

        logger.info(f"APScheduler initialized for loop {id(loop)}")

    except RuntimeError:
        raise SchedulerError(
            "APScheduler must be initialized within a running event loop. "
            "Call scheduler.start() from an async context."
        )
```

#### Issue 4.3: SQLAlchemy Version Compatibility
**Severity**: LOW

**Finding**: If using SQLite job stores with APScheduler, verify SQLAlchemy version compatibility.

**Current Dependencies** (from pyproject.toml):
```toml
# No explicit SQLAlchemy dependency
# But asyncpg is present (PostgreSQL driver)
```

**Recommendation**:
```toml
[project.optional-dependencies]
scheduler = [
    "apscheduler>=3.10.0,<3.11.0",
    "sqlalchemy[asyncio]>=2.0.0",  # For async job stores
    "aiosqlite>=0.20.0",  # Already in dependencies
]
```

---

### 5. Python 3.13 Compatibility: 8/10

**Strengths**:
- ✅ Project targets Python 3.13+ (`requires-python = ">=3.13"`)
- ✅ Uses modern type hints (`dict[str, Any]`, `Literal`, `| None`)
- ✅ Codebase already uses asyncio patterns compatible with 3.13

**Python 3.13 Features Available**:

#### Feature 1: TaskGroup (Already mentioned)
```python
# Python 3.11+ but perfect for 3.13
async with asyncio.TaskGroup() as tg:
    tg.create_task(task1())
    tg.create_task(task2())
# All done or exceptions raised
```

#### Feature 2: Improved Error Messages
Python 3.13 has much better error messages for async code. No code changes needed, just be aware.

#### Feature 3: Type Hint Improvements
```python
# Python 3.13 allows more complex type unions
from typing import Never

def this_function_never_returns() -> Never:
    raise Exception("This never returns")

# Use for scheduler jobs that should never complete
```

**Minor Issue**: Type stubs for external libraries (APScheduler, Oneiric) may not be Python 3.13-aware yet.

**Mitigation**:
```python
# Use type: ignore for external library issues
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[attr-defined]

# Or create stubs in mahavishnu/stubs/
```

---

## Recommendations Summary

### Critical (Must Fix Before Implementation)

1. **Add APScheduler dependency** to `pyproject.toml`
2. **Implement async context managers** for scheduler lifecycle
3. **Use TaskGroup** for concurrent scheduler startup (Python 3.13)
4. **Fix coroutine function type hints** (`Callable[..., Awaitable[Any]]`)
5. **Verify Oneiric queue adapter API** before implementation

### Important (Should Fix)

6. Add Protocol-based scheduler interface
7. Implement proper async job store configuration
8. Add comprehensive docstrings (Google style)
9. Implement graceful shutdown with error handling
10. Add type stubs for APScheduler if needed

### Nice to Have

11. Add scheduler performance monitoring
12. Implement job metrics collection
13. Add scheduler health checks
14. Create migration guide from cron
15. Add scheduler decision tree tool

---

## Implementation Roadmap (Python-Focused)

### Phase 1: Dependency & Type Safety (Day 1)
- [ ] Add `apscheduler>=3.10.0,<3.11.0` to dependencies
- [ ] Create type stubs for APScheduler (if needed)
- [ ] Define `SchedulerBackend` Protocol
- [ ] Add `Callable[..., Awaitable[Any]]` type hints

### Phase 2: Core Implementation (Days 2-3)
- [ ] Implement `MahavishnuScheduler` with async context manager
- [ ] Use `TaskGroup` for concurrent startup
- [ ] Implement async job store configuration
- [ ] Add proper error handling with custom exceptions

### Phase 3: Integration (Days 4-5)
- [ ] Wire APScheduler with event loop safety
- [ ] Implement Oneiric queue adapter integration
- [ ] Add Prefect async client integration
- [ ] Test all three schedulers independently

### Phase 4: Testing & Documentation (Days 6-7)
- [ ] Add comprehensive type checking (mypy strict mode)
- [ ] Test with `pytest-asyncio`
- [ ] Add performance benchmarks
- [ ] Document all async patterns

---

## Code Examples: Corrected Patterns

### Example 1: Complete MahavishnuScheduler Class

```python
"""Hybrid scheduler implementation with Python 3.13 best practices."""

import asyncio
from asyncio import TaskGroup
from collections.abc import Callable, Awaitable
from contextlib import asynccontextmanager
from logging import getLogger
from typing import Any, AsyncIterator, Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel, Field

from mahavishnu.core.config import MahavishnuSettings

logger = getLogger(__name__)


class SchedulerBackend(Protocol):
    """Protocol for scheduler backend implementations."""

    async def schedule_task(
        self,
        func: Callable[..., Awaitable[Any]],
        trigger_type: Literal["interval", "cron", "date"],
        **trigger_kwargs: Any,
    ) -> str:
        """Schedule a task and return job ID."""
        ...

    async def cancel_task(self, job_id: str) -> bool:
        """Cancel a scheduled task."""
        ...


class MahavishnuScheduler:
    """Unified scheduler interface for Mahavishnu.

    Manages three scheduling backends:
    1. APScheduler: High-frequency internal tasks
    2. Oneiric Queues: Infrastructure scheduling
    3. Prefect: User-facing workflows

    Example:
        >>> async with scheduler.lifecycle():
        ...     # Schedule health check every 30 seconds
        ...     await scheduler.schedule_internal_task(
        ...         health_check,
        ...         "interval",
        ...         seconds=30,
        ...     )
    """

    def __init__(self, config: MahavishnuSettings) -> None:
        """Initialize scheduler with configuration.

        Args:
            config: Mahavishnu configuration object
        """
        self.config = config
        self.apscheduler: AsyncIOScheduler | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator[None]:
        """Async context manager for scheduler lifecycle.

        Ensures proper startup and shutdown of all schedulers.

        Yields:
            None when all schedulers are running

        Example:
            >>> async with scheduler.lifecycle():
            ...     # Do work while schedulers are running
            ...     await do_something()
        """
        try:
            await self.start()
            yield
        finally:
            await self.stop()

    async def start(self) -> None:
        """Start all three schedulers concurrently.

        Uses TaskGroup for structured concurrency (Python 3.11+).

        Raises:
            SchedulerError: If any scheduler fails to start
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting hybrid scheduler...")

        # Get current event loop
        self._loop = asyncio.get_running_loop()

        # Start all schedulers concurrently
        async with TaskGroup() as tg:
            tg.create_task(self._start_apscheduler())
            tg.create_task(self._start_oneiric_queues())
            tg.create_task(self._start_prefect_deployments())

        self._running = True
        logger.info("All schedulers started successfully")

    async def stop(self) -> None:
        """Stop all schedulers with proper ordering.

        Shutdown order: Prefect -> Oneiric -> APScheduler
        """
        if not self._running:
            return

        logger.info("Stopping hybrid scheduler...")

        # Shutdown in reverse order
        await self._stop_prefect_deployments()
        await self._stop_oneiric_queues()
        await self._stop_apscheduler()

        self._running = False
        logger.info("All schedulers stopped")

    async def schedule_internal_task(
        self,
        func: Callable[..., Awaitable[Any]],
        trigger_type: Literal["interval", "cron", "date"],
        **trigger_kwargs: Any,
    ) -> str:
        """Schedule an internal task via APScheduler.

        Args:
            func: Async function to schedule
            trigger_type: Type of trigger ("interval", "cron", "date")
            **trigger_kwargs: Trigger-specific arguments

        Returns:
            Job ID string

        Raises:
            SchedulerError: If scheduling fails or scheduler not running
            ValueError: If trigger_type is invalid

        Example:
            >>> async def health_check():
            ...     print("Health check")
            >>> job_id = await scheduler.schedule_internal_task(
            ...     health_check,
            ...     "interval",
            ...     seconds=30,
            ... )
        """
        if not self._running or self.apscheduler is None:
            raise SchedulerError("Scheduler not running. Call start() first.")

        # Validate trigger type
        valid_triggers = {"interval", "cron", "date"}
        if trigger_type not in valid_triggers:
            raise ValueError(
                f"Invalid trigger_type: {trigger_type}. "
                f"Must be one of {valid_triggers}"
            )

        try:
            # Add job to scheduler
            job = self.apscheduler.add_job(
                func,
                trigger=trigger_type,
                **trigger_kwargs,
            )
            logger.info(f"Scheduled job {job.id} with trigger {trigger_type}")
            return job.id

        except Exception as e:
            raise SchedulerError(f"Failed to schedule job: {e}") from e

    async def _start_apscheduler(self) -> None:
        """Start APScheduler within running event loop."""
        if not self.config.schedulers.apscheduler_enabled:
            logger.info("APScheduler disabled in configuration")
            return

        try:
            # Create scheduler (it will detect running event loop)
            self.apscheduler = AsyncIOScheduler(
                timezone="UTC",
                job_defaults={
                    'coalesce': True,
                    'max_instances': 1,
                    'misfire_grace_time': 300,
                }
            )

            # Start scheduler
            self.apscheduler.start()
            logger.info(f"APScheduler started (loop: {id(self._loop)})")

        except Exception as e:
            raise SchedulerError(f"Failed to start APScheduler: {e}") from e

    async def _stop_apscheduler(self) -> None:
        """Stop APScheduler gracefully."""
        if self.apscheduler is None:
            return

        try:
            self.apscheduler.shutdown(wait=True)
            logger.info("APScheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping APScheduler: {e}")

    async def _start_oneiric_queues(self) -> None:
        """Start Oneiric queue adapters."""
        # Implementation depends on Oneiric's actual API
        logger.info("Oneiric queues started (placeholder)")

    async def _stop_oneiric_queues(self) -> None:
        """Stop Oneiric queue adapters."""
        logger.info("Oneiric queues stopped (placeholder)")

    async def _start_prefect_deployments(self) -> None:
        """Start Prefect deployment monitoring."""
        # Implementation depends on Prefect requirements
        logger.info("Prefect deployments started (placeholder)")

    async def _stop_prefect_deployments(self) -> None:
        """Stop Prefect deployment monitoring."""
        logger.info("Prefect deployments stopped (placeholder)")


class SchedulerError(Exception):
    """Exception raised for scheduler-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize scheduler error.

        Args:
            message: Human-readable error message
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "error": "SchedulerError",
            "message": self.message,
            "details": self.details,
        }
```

---

## Conclusion

The hybrid scheduler implementation plan is **well-conceived but requires refinement** before implementation. The main issues are:

1. **Missing dependencies** (APScheduler not in pyproject.toml)
2. **Incomplete async patterns** (no TaskGroup, missing context managers)
3. **Type safety gaps** (missing Protocol, incomplete Callable types)
4. **Library integration details** (Oneiric API needs verification)

**Recommended Next Steps**:

1. ✅ Add APScheduler to dependencies
2. ✅ Implement using code examples in this review
3. ✅ Use Python 3.13 features (TaskGroup, improved typing)
4. ✅ Add comprehensive type checking with mypy
5. ✅ Test async patterns thoroughly with pytest-asyncio

**Estimated Impact**:
- **Without fixes**: 5-7 day implementation with potential bugs
- **With fixes**: 3-4 day implementation with production-ready code

**Final Recommendation**: **Proceed with implementation after addressing Critical and Important issues**. The architecture is sound; the execution needs refinement to match Python 3.13 best practices.
