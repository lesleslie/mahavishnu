"""
Async patterns for Mahavishnu Task Orchestration.

This module provides async utilities including:
- Timeout handling with asyncio.timeout()
- Async context managers for DB connections
- Cancellation handling
- Saga distributed locks with SELECT FOR UPDATE

Created: 2026-02-18
Version: 3.1
Related: 4-Agent Opus Review P0 issue - async timeout handling
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TypeVar, Callable, Any, AsyncGenerator, ParamSpec

from mahavishnu.core.errors import MahavishnuError, ErrorCode, TimeoutError

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


# Default timeouts for different operations
DEFAULT_TIMEOUTS = {
    "database_query": 30.0,
    "database_transaction": 60.0,
    "api_call": 30.0,
    "webhook_processing": 10.0,
    "embedding_generation": 60.0,
    "nlp_parsing": 30.0,
    "file_operation": 60.0,
}


@asynccontextmanager
async def timeout_context(
    seconds: float,
    operation: str = "operation",
) -> AsyncGenerator[None, None]:
    """
    Async context manager with timeout handling.

    Usage:
        async with timeout_context(30.0, "database_query"):
            result = await db.execute(query)

    Args:
        seconds: Maximum time allowed for the operation
        operation: Name of operation for error messages

    Yields:
        None

    Raises:
        TimeoutError: If operation exceeds timeout
    """
    try:
        async with asyncio.timeout(seconds):
            yield
    except asyncio.TimeoutError:
        logger.error(f"{operation} timed out after {seconds}s")
        raise TimeoutError(
            f"{operation} timed out after {seconds}s",
            details={"operation": operation, "timeout_seconds": seconds},
        )
    except asyncio.CancelledError:
        logger.info(f"{operation} was cancelled")
        raise


@asynccontextmanager
async def db_connection(
    pool: Any,
    timeout_seconds: float = DEFAULT_TIMEOUTS["database_query"],
) -> AsyncGenerator[Any, None]:
    """
    Async context manager for database connections with timeout.

    Usage:
        async with db_connection(pool, timeout_seconds=30.0) as conn:
            result = await conn.execute(query)

    Args:
        pool: Database connection pool
        timeout_seconds: Maximum time for acquiring connection

    Yields:
        Database connection

    Raises:
        TimeoutError: If connection acquisition times out
        MahavishnuError: If database error occurs
    """
    async with timeout_context(timeout_seconds, "database_connection"):
        async with pool.acquire() as conn:
            try:
                yield conn
            except asyncio.CancelledError:
                # Rollback on cancellation
                try:
                    await conn.execute("ROLLBACK")
                except Exception:
                    pass  # Ignore rollback errors during cancellation
                raise
            except Exception as e:
                logger.error(f"Database error: {e}")
                raise


@asynccontextmanager
async def db_transaction(
    pool: Any,
    timeout_seconds: float = DEFAULT_TIMEOUTS["database_transaction"],
) -> AsyncGenerator[Any, None]:
    """
    Async context manager for database transactions with automatic commit/rollback.

    Usage:
        async with db_transaction(pool) as conn:
            await conn.execute("INSERT INTO tasks ...")
            # Auto-commits on success, auto-rollbacks on error

    Args:
        pool: Database connection pool
        timeout_seconds: Maximum time for transaction

    Yields:
        Database connection with active transaction
    """
    async with db_connection(pool, timeout_seconds) as conn:
        try:
            async with conn.transaction():
                yield conn
        except asyncio.CancelledError:
            logger.info("Transaction cancelled, rolling back")
            raise


class SagaLock:
    """
    Distributed lock for saga crash safety using SELECT FOR UPDATE.

    This ensures that only one worker can process a saga at a time,
    preventing race conditions and duplicate processing after crashes.

    Usage:
        async with SagaLock(db, saga_id) as lock:
            # Only one worker can execute this at a time
            await process_saga_step()

    The lock is held for the duration of the context manager and
    released automatically when the context exits (via transaction commit).
    """

    def __init__(self, db: Any, saga_id: str, timeout_seconds: float = 30.0) -> None:
        """
        Initialize saga lock.

        Args:
            db: Database connection or pool
            saga_id: Unique saga identifier
            timeout_seconds: Lock acquisition timeout
        """
        self.db = db
        self.saga_id = saga_id
        self.timeout_seconds = timeout_seconds
        self._locked = False

    async def __aenter__(self) -> "SagaLock":
        """Acquire lock on saga row using SELECT FOR UPDATE."""
        async with timeout_context(self.timeout_seconds, "saga_lock"):
            row = await self.db.fetch_one(
                "SELECT saga_id, status, current_step_index FROM saga_log "
                "WHERE saga_id = $1 FOR UPDATE",
                self.saga_id,
            )
            if row is None:
                raise MahavishnuError(
                    f"Saga {self.saga_id} not found",
                    ErrorCode.VALIDATION_ERROR,
                    recovery=[
                        "Verify saga_id is correct",
                        "Check if saga was deleted",
                        "Create a new saga if needed",
                    ],
                )
            self._locked = True
            logger.debug(f"Acquired lock on saga {self.saga_id}")
            return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """Release lock (automatic on transaction commit)."""
        self._locked = False
        logger.debug(f"Released lock on saga {self.saga_id}")
        return False  # Don't suppress exceptions

    @property
    def is_locked(self) -> bool:
        """Check if lock is currently held."""
        return self._locked


async def with_retry(
    func: Callable[P, T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """
    Execute async function with exponential backoff retry.

    Usage:
        result = await with_retry(
            fetch_external_data,
            max_retries=3,
            url="https://api.example.com/data"
        )

    Args:
        func: Async function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Base for exponential backoff
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result of successful function call

    Raises:
        Exception: The last exception if all retries fail
    """
    last_exception = None
    delay = base_delay

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * exponential_base, max_delay)

    logger.error(f"All {max_retries + 1} attempts failed")
    raise last_exception


async def run_with_timeout(
    coro: Any,
    timeout_seconds: float,
    operation: str = "operation",
) -> Any:
    """
    Run coroutine with timeout.

    Usage:
        result = await run_with_timeout(
            fetch_data(),
            timeout_seconds=30.0,
            operation="data_fetch"
        )

    Args:
        coro: Coroutine to execute
        timeout_seconds: Maximum time allowed
        operation: Operation name for error messages

    Returns:
        Result of coroutine

    Raises:
        TimeoutError: If timeout exceeded
    """
    async with timeout_context(timeout_seconds, operation):
        return await coro


class AsyncTaskManager:
    """
    Manager for tracking and cancelling async tasks.

    Usage:
        manager = AsyncTaskManager()

        # Start tracked tasks
        task1 = manager.create_task(process_webhook(data))
        task2 = manager.create_task(update_database())

        # Wait for all to complete
        await manager.wait_all()

        # Or cancel all on error
        await manager.cancel_all()
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._tasks: set[asyncio.Task] = set()

    def create_task(
        self,
        coro: Any,
        name: str | None = None,
    ) -> asyncio.Task:
        """Create and track a task."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_all(self, timeout: float | None = None) -> list[Any]:
        """Wait for all tasks to complete."""
        if not self._tasks:
            return []

        if timeout:
            async with asyncio.timeout(timeout):
                results = await asyncio.gather(*self._tasks, return_exceptions=True)
        else:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)

        return results

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Cancel all tracked tasks."""
        for task in self._tasks:
            task.cancel()

        # Wait for cancellation to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    @property
    def active_count(self) -> int:
        """Number of active tasks."""
        return len(self._tasks)

    @property
    def is_empty(self) -> bool:
        """Check if no active tasks."""
        return len(self._tasks) == 0
