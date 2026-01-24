# ADR 003: Error Handling and Resilience Strategy

## Status
**Accepted**

## Context
Mahavishnu operates across multiple repositories and external services (LLM providers, Git hosts, CI systems). Failures are inevitable. The system must handle failures gracefully without data corruption or cascading failures.

### Failure Modes to Address

1. **Transient Failures:** Network timeouts, rate limits, temporary API errors
2. **Permanent Failures:** Invalid repositories, authentication failures, missing dependencies
3. **Partial Failures:** 3/10 repos fail, 7 succeed
4. **Cascading Failures:** One adapter failure affects others
5. **Catastrophic Failures:** System crash, data corruption

### Options Considered

#### Option 1: Fail Fast
- **Pros:** Simple, errors are visible immediately
- **Cons:** Wastes work on partial failures, poor user experience, no resilience

#### Option 2: Manual Retry
- **Pros:** Developer control
- **Cons:** Error-prone, inconsistent, not scalable

#### Option 3: Comprehensive Resilience Patterns (CHOSEN)
- **Pros:**
  - Automatic retry with exponential backoff
  - Circuit breaker prevents cascading failures
  - Dead letter queue for manual inspection
  - Graceful degradation for partial failures
  - Structured error reporting
- **Cons:**
  - Increased complexity
  - More code to maintain
  - Need to tune parameters

## Decision
Implement comprehensive resilience patterns including retry logic, circuit breakers, dead letter queues, and graceful degradation.

### Retry Logic with Exponential Backoff

```python
import asyncio
import random
from typing import Callable, TypeVar

T = TypeVar('T')

async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (
        asyncio.TimeoutError,
        ConnectionError,
        TemporaryFailure,
    ),
    **kwargs,
) -> T:
    """Retry function with exponential backoff and jitter.

    Args:
        func: Async function to retry
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Add random jitter to prevent thundering herd
        retryable_exceptions: Exceptions that trigger retry

    Returns:
        Result from successful function call

    Raises:
        Last exception if all retries exhausted
    """
    last_exception = None

    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)

        except retryable_exceptions as e:
            last_exception = e

            if attempt == max_attempts - 1:
                # Last attempt, raise
                raise

            # Calculate delay with exponential backoff
            delay = min(base_delay * (2 ** attempt), max_delay)

            # Add jitter to prevent thundering herd
            if jitter:
                delay += random.uniform(0, 1)

            logger.warning(
                "retry_attempt",
                function=func.__name__,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                delay_seconds=delay,
                error=str(e),
            )

            await asyncio.sleep(delay)

        except Exception as e:
            # Non-retryable exception, raise immediately
            raise

    # Should never reach here, but just in case
    if last_exception:
        raise last_exception
```

### Circuit Breaker Pattern

```python
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered

class CircuitBreaker:
    """Circuit breaker to prevent cascading failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        success_threshold: int = 2,
    ):
        """
        Args:
            failure_threshold: Consecutive failures to open circuit
            timeout_seconds: Seconds before attempting recovery
            success_threshold: Consecutive successes to close circuit
        """
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.success_threshold = success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.opened_at: Optional[datetime] = None

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: Function to execute

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        if self.state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info("circuit_breaker_half_open")
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open. Opened at {self.opened_at}"
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.opened_at:
            return False

        elapsed = datetime.now() - self.opened_at
        return elapsed >= timedelta(seconds=self.timeout_seconds)

    def _on_success(self):
        """Handle successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1

            if self.success_count >= self.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.opened_at = None
                logger.info("circuit_breaker_closed")

        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            # Failed in half-open, reopen circuit
            self.state = CircuitState.OPEN
            self.opened_at = datetime.now()
            self.success_count = 0
            logger.warning("circuit_breaker_reopened", failure_count=self.failure_count)

        elif self.failure_count >= self.failure_threshold:
            # Open circuit
            self.state = CircuitState.OPEN
            self.opened_at = datetime.now()
            logger.warning(
                "circuit_breaker_opened",
                failure_count=self.failure_count,
                threshold=self.failure_threshold,
            )
```

### Dead Letter Queue

```python
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
import uuid

@dataclass
class DeadLetterEntry:
    """Entry in dead letter queue."""
    id: str
    workflow_id: str
    task: dict[str, Any]
    repos: list[str]
    adapter: str
    error: str
    error_type: str
    timestamp: str
    metadata: dict[str, Any]

class DeadLetterQueue:
    """Dead letter queue for failed workflows."""

    def __init__(self, queue_dir: Path = Path(".mahavishnu") / "dead_letter"):
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    async def enqueue(
        self,
        workflow_id: str,
        task: dict[str, Any],
        repos: list[str],
        adapter: str,
        error: Exception,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add failed workflow to dead letter queue.

        Args:
            workflow_id: Workflow identifier
            task: Task that failed
            repos: Repositories being processed
            adapter: Adapter being used
            error: Exception that occurred
            metadata: Additional metadata

        Returns:
            Entry ID
        """
        entry = DeadLetterEntry(
            id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            task=task,
            repos=repos,
            adapter=adapter,
            error=str(error),
            error_type=type(error).__name__,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
        )

        # Save to file
        entry_path = self.queue_dir / f"{entry.id}.json"
        with open(entry_path, "w") as f:
            json.dump(asdict(entry), f, indent=2, default=str)

        logger.error(
            "dead_letter_enqueue",
            entry_id=entry.id,
            workflow_id=workflow_id,
            error=str(error),
        )

        return entry.id

    async def list_entries(self) -> list[DeadLetterEntry]:
        """List all entries in dead letter queue."""
        entries = []

        for entry_file in self.queue_dir.glob("*.json"):
            with open(entry_file, "r") as f:
                data = json.load(f)
                entries.append(DeadLetterEntry(**data))

        return sorted(entries, key=lambda e: e.timestamp, reverse=True)

    async def replay(self, entry_id: str) -> dict[str, Any]:
        """Replay a dead letter entry.

        Args:
            entry_id: Entry ID to replay

        Returns:
            Replay result
        """
        entry_path = self.queue_dir / f"{entry_id}.json"

        if not entry_path.exists():
            raise ValueError(f"Entry not found: {entry_id}")

        with open(entry_path, "r") as f:
            data = json.load(f)
            entry = DeadLetterEntry(**data)

        # Remove from queue
        entry_path.unlink()

        # Re-execute workflow
        from ..core.app import MahavishnuApp

        app = MahavishnuApp()
        result = await app.execute_workflow(
            task=entry.task,
            repos=entry.repos,
            adapter_name=entry.adapter,
        )

        logger.info(
            "dead_letter_replay",
            entry_id=entry_id,
            workflow_id=entry.workflow_id,
            status=result.get("status"),
        )

        return result
```

### Graceful Degradation

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class PartialResult:
    """Result from partial workflow execution."""
    status: str  # "partial", "success", "failure"
    total_repos: int
    successful_repos: list[str]
    failed_repos: list[tuple[str, str]]  # (repo, error)
    execution_time_seconds: float
    metadata: dict[str, Any]

async def execute_with_graceful_degradation(
    task: dict[str, Any],
    repos: list[str],
    adapter: OrchestratorAdapter,
) -> PartialResult:
    """Execute workflow with graceful degradation on partial failures.

    Continues processing remaining repos even if some fail.
    Returns detailed results showing successes and failures.

    Args:
        task: Task to execute
        repos: Repositories to process
        adapter: Adapter to use

    Returns:
        PartialResult with detailed breakdown
    """
    import time
    from asyncio import gather, return_exceptions

    start_time = time.time()
    successful_repos = []
    failed_repos = []

    # Process all repos, continuing on failures
    tasks = [_process_single_repo(adapter, task, repo) for repo in repos]
    results = await gather(*tasks, return_exceptions=True)

    for repo, result in zip(repos, results):
        if isinstance(result, Exception):
            failed_repos.append((repo, str(result)))
            logger.error(
                "repo_processing_failed",
                repo=repo,
                error=str(result),
                error_type=type(result).__name__,
            )
        else:
            successful_repos.append(repo)
            logger.info("repo_processing_success", repo=repo)

    execution_time = time.time() - start_time

    # Determine overall status
    if failed_repos and not successful_repos:
        status = "failure"
    elif successful_repos and not failed_repos:
        status = "success"
    else:
        status = "partial"

    return PartialResult(
        status=status,
        total_repos=len(repos),
        successful_repos=successful_repos,
        failed_repos=failed_repos,
        execution_time_seconds=execution_time,
        metadata={
            "task": task,
            "adapter": adapter.__class__.__name__,
        },
    )

async def _process_single_repo(
    adapter: OrchestratorAdapter,
    task: dict[str, Any],
    repo: str,
) -> Any:
    """Process a single repository with error isolation."""
    try:
        return await adapter.execute(task, [repo])
    except Exception as e:
        # Return exception to be handled by graceful degradation
        return e
```

## Consequences

### Positive
- System is resilient to transient failures
- Cascading failures are prevented by circuit breakers
- Failed workflows can be inspected and replayed via dead letter queue
- Partial failures don't waste work on successful repos
- Clear error reporting with structured logging

### Negative
- Increased complexity in error handling logic
- More code paths to test and maintain
- Need to tune retry/backoff parameters
- Dead letter queue requires management

### Risks
- **Risk:** Retry storms overwhelming services
  **Mitigation:** Exponential backoff with jitter, circuit breakers

- **Risk:** Dead letter queue grows unbounded
  **Mitigation:** Monitor queue size, alert on threshold, auto-archive old entries

- **Risk:** Tuning parameters are environment-specific
  **Mitigation:** Make parameters configurable via Oneiric, document recommended values

## Implementation

### Phase 1: Retry Logic (Week 3, Day 1-2)
- [ ] Implement `retry_with_backoff()` function
- [ ] Add retry decorators for common operations
- [ ] Configure retryable exceptions
- [ ] Add metrics for retry attempts

### Phase 2: Circuit Breaker (Week 3, Day 3-4)
- [ ] Implement `CircuitBreaker` class
- [ ] Add circuit breakers to all adapters
- [ ] Add metrics for circuit state changes
- [ ] Add alerting for circuit breaker opens

### Phase 3: Dead Letter Queue (Week 3, Day 5)
- [ ] Implement `DeadLetterQueue` class
- [ ] Add enqueue on workflow failure
- [ ] Implement replay CLI command
- [ ] Add metrics for queue size

### Phase 4: Graceful Degradation (Week 3, Day 6-7)
- [ ] Implement `execute_with_graceful_degradation()`
- [ ] Update adapters to use partial results
- [ ] Add CLI commands for dead letter management
- [ ] Add integration tests for failure scenarios

## References
- [Microsoft Resilience Patterns](https://docs.microsoft.com/en-us/azure/architecture/patterns/category/resiliency)
- [AWS Circuit Breaker Pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/implementing-circuit-breaker-pattern.html)
- [Google SRE Book: Error Propagation](https://sre.google/sre-book/addressing-cascading-failures/)
