# ADR 007: Implement Saga Coordinator for Distributed Transactions

**Status**: Accepted
**Date**: 2026-02-18
**Context**: Task Orchestration Master Plan v3.0
**Related**: ADR-006 (Storage Simplification), ADR-008 (Zero-Downtime Migration)

---

## Context

Creating a task in the Task Orchestration System involves multiple storage operations across different systems:

### Original Problem (v2.0 - 4-System Architecture)

```
Saga: Create Task (4 steps)

Step 1: Create task in PostgreSQL
  ✓ Success → Continue
  ✗ Failure → Rollback (nothing to undo)

Step 2: Store embedding in Akosha
  ✓ Success → Continue
  ✗ Failure → Compensate: Delete task from PostgreSQL

Step 3: Store context in Session-Buddy
  ✓ Success → Continue
  ✗ Failure → Compensate: Delete from Akosha, Delete from PostgreSQL

Step 4: Create worktree (if applicable)
  ✓ Success → Complete
  ✗ Failure → Compensate: Delete from Session-Buddy, Akosha, PostgreSQL
```

### Problems with Naive Saga Implementation

During the 5-agent review council, the Architecture Reviewer identified **missing saga coordinator** as a **P0 critical issue**:

- **No Persistent Saga State**: Saga progress tracked only in memory
- **No Crash Recovery**: If process crashes mid-saga, no way to recover
- **No Retry Logic**: Transient failures cause immediate rollback
- **No Idempotency**: Retrying saga steps causes duplicate operations
- **No Monitoring**: Can't observe saga health or failure rates

### Architecture Reviewer Feedback

**Score**: 4.2/5.0 (APPROVED WITH RECOMMENDATIONS)

> "The saga pattern is mentioned but not fully specified. You need a persistent saga coordinator with crash recovery, retry logic with exponential backoff, circuit breakers, and idempotent step execution. Without these, distributed transactions will fail in production."

---

## Decision

Implement a **persistent Saga Coordinator** with the following features:

### Core Components

#### 1. Saga Coordinator Class

```python
from mahavishnu.core.saga import SagaCoordinator, SagaStep, SagaResult
from mahavishnu.core.storage import PostgreSQLDB

class SagaCoordinator:
    """
    Persistent saga coordinator with crash recovery.

    Features:
    - Persistent saga log in PostgreSQL
    - Crash recovery on restart
    - Exponential backoff retry
    - Circuit breaker for failing steps
    - Idempotent step execution
    """

    def __init__(self, db: PostgreSQLDB):
        self.db = db
        self.max_retries = 3
        self.base_backoff = 1.0  # seconds
        self.circuit_breaker_threshold = 5  # failures before opening

    async def execute_saga(
        self,
        saga_id: str,
        steps: list[SagaStep],
        initial_state: dict[str, Any],
    ) -> SagaResult:
        """
        Execute saga with crash recovery and retry logic.

        Args:
            saga_id: Unique saga identifier
            steps: List of saga steps to execute
            initial_state: Initial state for saga

        Returns:
            SagaResult with final status and state

        Raises:
            SagaExecutionError: If saga fails after all retries
        """
        # Load or create saga state from PostgreSQL
        saga_state = await self._load_or_create_saga(saga_id, steps, initial_state)

        # Resume from last completed step (crash recovery)
        start_index = saga_state.current_step_index

        # Execute remaining steps
        for i in range(start_index, len(steps)):
            step = steps[i]

            # Execute step with retry logic
            try:
                result = await self._execute_step_with_retry(
                    step=step,
                    state=saga_state.state,
                    saga_id=saga_id,
                )

                # Update saga state
                saga_state.state.update(result)
                saga_state.completed_steps.append(i)
                saga_state.current_step_index = i + 1

                # Persist saga state to PostgreSQL
                await self._persist_saga_state(saga_state)

            except Exception as e:
                # Step failed after retries - compensate
                await self._compensate(saga_state, failure_reason=str(e))

                raise SagaExecutionError(
                    f"Saga {saga_id} failed at step {i}: {e}",
                    saga_id=saga_id,
                    failed_step=i,
                    state=saga_state.state,
                )

        # All steps completed successfully
        saga_state.status = SagaStatus.COMPLETED
        await self._persist_saga_state(saga_state)

        return SagaResult(
            saga_id=saga_id,
            status=SagaStatus.COMPLETED,
            state=saga_state.state,
        )
```

#### 2. Saga Step Definition

```python
from pydantic import BaseModel
from typing import Callable, Awaitable

class SagaStep(BaseModel):
    """
    Single step in a saga transaction.

    Each step has:
    - execute: The main operation
    - compensate: Rollback operation (called if saga fails)
    - idempotency_key: Unique key for idempotent execution
    """

    name: str
    execute: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    compensate: Callable[[dict[str, Any]], Awaitable[None]]
    idempotency_key: str

    class Config:
        arbitrary_types_allowed = True


# Example: Create task in PostgreSQL
async def execute_create_task_postgresql(state: dict[str, Any]) -> dict[str, Any]:
    """Create task in PostgreSQL."""
    task = await db.create_task(
        title=state["title"],
        description=state["description"],
        repository=state["repository"],
        priority=state["priority"],
    )
    return {"task_id": task.id, "task": task}


async def compensate_create_task_postgresql(state: dict[str, Any]) -> None:
    """Delete task from PostgreSQL (compensating transaction)."""
    if "task_id" in state:
        await db.delete_task(state["task_id"])


create_task_step = SagaStep(
    name="create_task_postgresql",
    execute=execute_create_task_postgresql,
    compensate=compensate_create_task_postgresql,
    idempotency_key="task_postgresql",
)
```

#### 3. Saga Log Schema (PostgreSQL)

```sql
-- Saga log table (persistent saga state)
CREATE TABLE saga_log (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL UNIQUE,
    saga_type VARCHAR(100) NOT NULL,  -- e.g., 'create_task', 'import_github_issue'
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, failed, compensating
    current_step_index INT NOT NULL DEFAULT 0,
    completed_steps INT[] DEFAULT '{}',  -- Array of completed step indices
    state JSONB NOT NULL DEFAULT '{}',  -- Saga state (flexible schema)
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
);

CREATE INDEX idx_saga_log_saga_id ON saga_log(saga_id);
CREATE INDEX idx_saga_log_status ON saga_log(status);
CREATE INDEX idx_saga_log_created_at ON saga_log(created_at);

-- Idempotency tracking (prevent duplicate step execution)
CREATE TABLE saga_idempotency (
    id BIGSERIAL PRIMARY KEY,
    saga_id UUID NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(saga_id, step_name, idempotency_key),
);

CREATE INDEX idx_saga_idempotency_lookup ON saga_idempotency(saga_id, step_name, idempotency_key);
```

#### 4. Retry Logic with Exponential Backoff

```python
import asyncio
from datetime import timedelta

async def _execute_step_with_retry(
    self,
    step: SagaStep,
    state: dict[str, Any],
    saga_id: str,
) -> dict[str, Any]:
    """
    Execute step with exponential backoff retry.

    Retry strategy:
    - Attempt 1: Immediate
    - Attempt 2: Wait 1 second
    - Attempt 3: Wait 2 seconds
    - Attempt 4+: Circuit breaker opens
    """
    # Check idempotency (skip if already executed)
    if await self._was_step_executed(saga_id, step):
        logger.info(f"Step {step.name} already executed, skipping")
        return state.get(step.name + "_result", {})

    # Check circuit breaker
    if await self._is_circuit_breaker_open(step):
        raise SagaExecutionError(
            f"Circuit breaker open for step {step.name}, refusing to execute"
        )

    # Execute with retry
    last_error = None
    for attempt in range(self.max_retries):
        try:
            result = await step.execute(state)

            # Mark step as executed (idempotency)
            await self._mark_step_executed(saga_id, step)

            # Reset circuit breaker on success
            await self._reset_circuit_breaker(step)

            return result

        except Exception as e:
            last_error = e
            logger.warning(
                f"Step {step.name} failed (attempt {attempt + 1}/{self.max_retries}): {e}"
            )

            # Exponential backoff
            backoff = self.base_backoff * (2 ** attempt)
            await asyncio.sleep(backoff)

    # All retries failed
    await self._increment_circuit_breaker_failure(step)

    raise SagaExecutionError(
        f"Step {step.name} failed after {self.max_retries} retries: {last_error}"
    )
```

#### 5. Crash Recovery

```python
async def _load_or_create_saga(
    self,
    saga_id: str,
    steps: list[SagaStep],
    initial_state: dict[str, Any],
) -> SagaState:
    """
    Load existing saga state (crash recovery) or create new saga.

    Crash Recovery Logic:
    1. Check if saga exists in database
    2. If exists, load state and resume from current_step_index
    3. If not exists, create new saga
    """
    # Try to load existing saga
    row = await self.db.fetch_one(
        "SELECT * FROM saga_log WHERE saga_id = $1",
        saga_id,
    )

    if row:
        # Saga exists - resume from where we left off
        logger.info(f"Resuming saga {saga_id} from step {row['current_step_index']}")

        return SagaState(
            saga_id=saga_id,
            saga_type=row["saga_type"],
            status=SagaStatus(row["status"]),
            current_step_index=row["current_step_index"],
            completed_steps=row["completed_steps"],
            state=row["state"],
            error_message=row.get("error_message"),
            retry_count=row["retry_count"],
        )
    else:
        # Create new saga
        logger.info(f"Creating new saga {saga_id}")

        new_saga = SagaState(
            saga_id=saga_id,
            saga_type=steps[0].name.split("_")[0],  # Infer type from first step
            status=SagaStatus.PENDING,
            current_step_index=0,
            completed_steps=[],
            state=initial_state,
            retry_count=0,
        )

        await self._persist_saga_state(new_saga)

        return new_saga
```

#### 6. Compensation Logic

```python
async def _compensate(
    self,
    saga_state: SagaState,
    failure_reason: str,
) -> None:
    """
    Compensate completed steps (rollback).

    Compensation executes in REVERSE order of completed steps.
    Each compensation step is retried with exponential backoff.
    """
    logger.error(
        f"Saga {saga_state.saga_id} failed, compensating {len(saga_state.completed_steps)} steps"
    )

    # Update saga status to compensating
    saga_state.status = SagaStatus.COMPENSATING
    saga_state.error_message = failure_reason
    await self._persist_saga_state(saga_state)

    # Compensate in reverse order
    for step_index in reversed(saga_state.completed_steps):
        step = self.steps[step_index]

        try:
            logger.info(f"Compensating step {step.name}")

            # Retry compensation with exponential backoff
            for attempt in range(self.max_retries):
                try:
                    await step.compensate(saga_state.state)
                    break  # Success
                except Exception as e:
                    logger.warning(
                        f"Compensation {step.name} failed (attempt {attempt + 1}): {e}"
                    )
                    if attempt == self.max_retries - 1:
                        raise  # All retries failed

                    backoff = self.base_backoff * (2 ** attempt)
                    await asyncio.sleep(backoff)

        except Exception as e:
            logger.error(f"Failed to compensate step {step.name}: {e}")
            # Continue compensating other steps (best effort)

    # Mark saga as failed
    saga_state.status = SagaStatus.FAILED
    await self._persist_saga_state(saga_state)
```

### Simplified Saga for 2-System Architecture (v3.0)

```
Saga: Create Task (2 steps - simplified from 4 steps)

Step 1: Create task in PostgreSQL
  ✓ Success → Continue
  ✗ Failure → Rollback (nothing to undo)

Step 2: Store context in Session-Buddy (best-effort)
  ✓ Success → Complete
  ✗ Failure → Complete anyway (best-effort, no compensation)
```

**Key Change**: Session-Buddy is best-effort, so no compensation needed if it fails.

---

## Alternatives Considered

### Alternative 1: No Saga Coordinator (REJECTED)

**Pros**:
- Simpler implementation
- Less code

**Cons**:
- **No crash recovery** (process crash = lost transactions)
- **No retry logic** (transient failures cause immediate rollback)
- **No idempotency** (retries cause duplicate operations)
- **Production nightmare** (unreliable)

**Decision**: Unacceptable for production system. Must have saga coordinator.

### Alternative 2: In-Memory Saga State (REJECTED)

**Pros**:
- Faster (no database I/O)
- Simpler implementation

**Cons**:
- **Lost on crash** (no persistence)
- **No horizontal scaling** (state tied to single process)
- **No observability** (can't query saga history)

**Decision**: Persistence is required for production reliability.

### Alternative 3: Persistent Saga Coordinator (ACCEPTED)

**Pros**:
- **Crash recovery** (resume from where we left off)
- **Retry logic** (handle transient failures)
- **Idempotency** (safe to retry)
- **Observability** (query saga history)
- **Circuit breaker** (prevent cascade failures)

**Cons**:
- More complex implementation
- Additional database I/O overhead
- Adds 1 week to Phase 1 timeline

**Decision**: Required for production reliability.

---

## Consequences

### Positive Impacts

1. **Crash Recovery**: Process crashes don't lose transaction progress
2. **Retry Logic**: Transient failures (network blips, DB locks) are retried automatically
3. **Idempotency**: Safe to retry saga steps without duplicate operations
4. **Observability**: Can query saga history for debugging
5. **Circuit Breaker**: Failing steps don't cause infinite retry loops
6. **Production Ready**: Handles real-world failure scenarios

### Negative Impacts

1. **Complexity**: More complex than simple transaction
2. **Timeline**: Adds 1 week to Phase 1 implementation
3. **Database Overhead**: Additional saga log table and queries
4. **Debugging**: Saga failures can be harder to debug than simple errors

### Risks

1. **Saga Log Becomes Bottleneck**: High saga volume could slow down system
   - **Severity**: Low
   - **Mitigation**: Partition saga_log by created_at
   - **Mitigation**: Archive old saga records

2. **Compensation Failures**: What if compensation itself fails?
   - **Severity**: Medium
   - **Mitigation**: Retry compensation with exponential backoff
   - **Mitigation**: Alert on compensation failures (manual intervention)

3. **Orphaned Sagas**: Sagas stuck in COMPENSATING state
   - **Severity**: Medium
   - **Mitigation**: Background job to detect and clean up orphaned sagas
   - **Mitigation**: Alert on sagas > 1 hour in COMPENSATING state

---

## Implementation Timeline

**Phase 1, Week 2**: Implement Saga Coordinator (7 days)

- **Day 1-2**: Core saga coordinator class and state management
- **Day 3-4**: Retry logic with exponential backoff and circuit breaker
- **Day 5**: Idempotency tracking and crash recovery
- **Day 6**: Compensation logic and error handling
- **Day 7**: Testing (unit tests, integration tests, crash recovery tests)

---

## Monitoring

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Saga metrics
saga_total = Counter(
    'saga_total',
    'Total sagas executed',
    ['saga_type', 'status']
)

saga_duration_seconds = Histogram(
    'saga_duration_seconds',
    'Saga execution duration',
    ['saga_type'],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0]
)

saga_step_retries_total = Counter(
    'saga_step_retries_total',
    'Total saga step retries',
    ['saga_type', 'step_name']
)

saga_compensations_total = Counter(
    'saga_compensations_total',
    'Total saga compensations',
    ['saga_type']
)

active_sagas = Gauge(
    'active_sagas',
    'Number of active sagas',
    ['saga_type', 'status']
)
```

### Grafana Dashboard

- **Saga Success Rate**: Percentage of sagas that complete successfully
- **Saga Duration**: p50, p95, p99 duration by saga type
- **Step Retry Rate**: Retry rate by step name
- **Compensation Rate**: Percentage of sagas that require compensation
- **Active Sagas**: Current active sagas by status

---

## Related Decisions

- **ADR-006: Storage Simplification**: Simplified saga from 4 steps to 2 steps
- **ADR-008: Zero-Downtime Migration**: Migration strategy uses saga pattern

---

## References

- Saga Pattern: https://microservices.io/patterns/data/saga.html
- Architecture Reviewer Report (2026-02-18): Score 4.2/5.0, identified missing saga coordinator as P0
- Master Plan v3.0: `/docs/TASK_ORCHESTRATION_MASTER_PLAN_V3.md`

---

**END OF ADR-002**
