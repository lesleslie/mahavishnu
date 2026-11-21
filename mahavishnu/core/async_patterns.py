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

from __future__ import annotations

import asyncio
import builtins
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
import contextvars
import logging
import signal
import threading
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar

from mahavishnu.core.errors import ErrorCode, MahavishnuError, TimeoutError
from mahavishnu.core.resilience import RetryExhaustedError, RetryPolicy, retry_async

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Coroutine
    from types import FrameType, TracebackType

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
) -> AsyncGenerator[None]:
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
    except builtins.TimeoutError:
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
) -> AsyncGenerator[Any]:
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
    async with (
        timeout_context(timeout_seconds, "database_connection"),
        pool.acquire() as conn,
    ):
        try:
            yield conn
        except asyncio.CancelledError:
            # Rollback on cancellation
            try:
                await conn.execute("ROLLBACK")
            except (OSError, RuntimeError) as e:
                logger.debug("Rollback error during cancellation: %s", e)
            raise
        except Exception as e:
            logger.error("Database error: %s", e)
            raise


@asynccontextmanager
async def db_transaction(
    pool: Any,
    timeout_seconds: float = DEFAULT_TIMEOUTS["database_transaction"],
) -> AsyncGenerator[Any]:
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

    async def __aenter__(self) -> Self:
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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Release lock (automatic on transaction commit)."""
        self._locked = False
        logger.debug(f"Released lock on saga {self.saga_id}")
        return False  # Don't suppress exceptions

    @property
    def is_locked(self) -> bool:
        """Check if lock is currently held."""
        return self._locked


async def with_retry[**P, T](
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
    policy = RetryPolicy(
        max_attempts=max_retries + 1,
        initial_delay_seconds=base_delay,
        max_delay_seconds=max_delay,
        backoff_factor=exponential_base,
    )
    try:
        result, _attempts = await retry_async(
            func,  # ty: ignore[invalid-argument-type]
            *args,
            policy=policy,
            operation="async_patterns.with_retry",
            **kwargs,  # ty: ignore[invalid-argument-type]
        )
        return result
    except RetryExhaustedError as exc:
        raise exc.last_exception if exc.last_exception is not None else exc


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


#: How long the interrupt handler waits for the worker thread to publish
#: its event loop before giving up on stopping it. The worker publishes
#: the loop before it starts the coroutine, so this is only ever a
#: scheduling delay -- the bound is there so a worker that never starts
#: cannot hold the CLI open.
_INTERRUPT_LOOP_WAIT_SECONDS: float = 5.0


def run_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from synchronous code.

    ``asyncio.run`` refuses to start a new event loop when one is already
    running in this thread, and raises ``RuntimeError: asyncio.run()
    cannot be called from a running event loop``. That is exactly the
    case for a CLI command invoked from async code — an async test, or
    any in-process async caller — and the crash names neither the cause
    nor the remedy: the command simply exits 1 with a stack trace that
    points at the event loop rather than at the command.

    When a loop is already running, the coroutine is driven to
    completion on its OWN loop in a worker thread. The teardown is the
    same as the synchronous path's: the worker path uses
    ``asyncio.Runner`` — the same machinery ``asyncio.run`` uses — so a
    fresh loop is created and set as the *worker thread's* current
    event loop (so ``get_event_loop()`` works there), pending tasks
    are cancelled, async generators are shut down, the default executor
    is joined, and the loop is closed.

    What the caller gives up: the caller's THREAD is blocked until the
    coroutine finishes. That is what a synchronous helper does, and it
    cannot be otherwise — the caller asked for a value, not for a
    schedule. If the caller's thread is the one running its own loop,
    that loop is stalled for the duration; nothing is scheduled on it,
    and nothing on it is re-entered.

    The one behaviour that differs is SIGINT. On the main thread,
    ``asyncio.run`` installs a handler that cancels the coroutine's
    task, so Ctrl+C unwinds the coroutine. A worker thread cannot
    install one — ``Runner`` guards its handler with a main-thread
    check — so on the worker path the interrupt lands in the CALLER,
    which stops the worker's loop and re-raises. Either way the
    operator's Ctrl+C ends the command; only the shape of the
    unwinding differs.

    That matters more than it sounds, because the caller here is
    usually itself under an ``asyncio.run``: its handler cancels the
    caller's task, and a task blocked in this synchronous wait cannot
    be cancelled. So the default handler is restored for the duration
    of the wait, and the interrupt lands in the caller's thread where
    it can stop the worker's loop. Without that, Ctrl+C under an
    ``asyncio.run`` caller would do nothing at all.

    Args:
        coro: The coroutine to run.

    Returns:
        Whatever the coroutine returns.

    Raises:
        Exception: Whatever the coroutine raises, unchanged.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop is running in this thread: the ordinary path.
        return asyncio.run(coro)

    # A loop IS running in this thread. Drive the coroutine on a fresh
    # loop in a worker thread so the caller's loop is left alone.
    #
    # The caller's CONTEXT is carried over explicitly: a worker thread
    # starts with an empty ``contextvars`` context, and the logging
    # context oneiric binds to a request id lives there. Without the
    # copy, a command driven from async code would log without the
    # context its caller had.
    context = contextvars.copy_context()
    worker_loop: list[asyncio.AbstractEventLoop] = []
    loop_published = threading.Event()

    def _driver() -> T:
        # ``asyncio.Runner`` rather than a hand-rolled loop. It is what
        # ``asyncio.run`` uses internally, so the worker path gets the
        # same lifecycle: the loop is installed as this thread's
        # current event loop, the coroutine runs as a task, and on exit
        # pending tasks are cancelled, async generators are shut down,
        # the default executor is joined, and the loop is closed. A
        # hand-rolled ``new_event_loop()`` + ``run_until_complete`` +
        # ``close()`` skipped all of that -- and left the thread's
        # current event loop unset, so ``get_event_loop()`` in the
        # worker raised ``RuntimeError: There is no current event loop
        # in thread ...`` whenever it was reached outside the running
        # loop.
        #
        # ``Runner`` is safe off the main thread: the SIGINT handler it
        # installs is guarded by a main-thread check, so in a worker it
        # simply does not install one.
        with asyncio.Runner() as runner:
            loop = runner.get_loop()
            worker_loop.append(loop)
            # Published BEFORE the coroutine starts: the interrupt
            # handler needs the loop to stop it, and an interrupt can
            # land at any moment.
            loop_published.set()
            return runner.run(coro)

    def _submit() -> T:
        # Wrapping the call rather than passing ``context.run`` to
        # ``submit`` as a function: ``submit`` binds its result type to
        # the callable it is handed, and a generic callable leaves that
        # type unresolved.
        return context.run(_driver)

    # ``asyncio.run`` -- and ``asyncio.Runner``, which it uses -- replaces
    # the SIGINT handler with one that CANCELS the main task. A task
    # blocked in a synchronous call cannot be cancelled: the cancellation
    # is only delivered when the task yields to the loop, and the wait
    # below is exactly such a call. So under an asyncio Runner, Ctrl+C
    # would do nothing at all -- the task would sit in the wait forever,
    # and a command that runs a server would never stop.
    #
    # Restore the default handler for the duration of the wait, so the
    # interrupt lands in THIS thread, where the handler below can stop
    # the worker's loop. The caller's own handler is put back when the
    # wait is over. Only the main thread may install a handler, and
    # only a caller whose handler is not already the default needs it
    # changed.
    previous_sigint: (
        signal.Handlers | Callable[[int, FrameType | None], Any] | int | None
    ) = None
    sigint_swapped = False
    if threading.current_thread() is threading.main_thread():
        current_sigint = signal.getsignal(signal.SIGINT)
        if current_sigint is not signal.default_int_handler:
            previous_sigint = current_sigint
            signal.signal(signal.SIGINT, signal.default_int_handler)
            sigint_swapped = True

    pool = ThreadPoolExecutor(max_workers=1)
    # The submit is inside the try, so an interrupt that lands between
    # the handler swap above and the wait still runs the finally -- and
    # the finally is what puts the caller's own SIGINT handler back.
    future: Future[T] | None = None
    try:
        future = pool.submit(_submit)
        return future.result()
    except KeyboardInterrupt:
        # The operator interrupted the CALLER's thread, but the
        # coroutine is running on the worker's loop -- so it has to be
        # stopped there. Without this, a command that runs a server
        # (`mahavishnu acp serve`) would keep the server alive on the
        # worker thread and the CLI would wait for it instead of
        # shutting down.
        #
        # Wait for the worker to publish its loop first. The interrupt
        # can land before the worker has created one, and a worker that
        # then runs the coroutine anyway leaves a live thread that
        # ``concurrent.futures`` joins at exit -- the process would hang
        # on the way out instead of shutting down.
        loop_published.wait(timeout=_INTERRUPT_LOOP_WAIT_SECONDS)
        loop = worker_loop[0] if worker_loop else None
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
            # Wait for the worker to wind down, and ignore whatever it
            # reports: the worker is stopping, and its own failure is
            # not what the operator needs to see. The interrupt is
            # re-raised below.
            with suppress(BaseException):
                if future is not None:
                    future.result(timeout=10)
        elif future is not None:
            # No loop was published, so the worker never ran the
            # coroutine -- or it has not started yet. Cancelling stops
            # a worker that has not begun, which is the one case where
            # the shutdown below cannot: ``cancel_futures`` only
            # cancels what has not started, and a worker that HAS
            # started is stopped by the branch above.
            future.cancel()
        raise
    finally:
        if sigint_swapped:
            with suppress(ValueError, TypeError):
                # ``None`` is not a legal handler -- ``signal.signal``
                # raises on it -- and it means SIG_DFL. Mapping it
                # keeps a restore from failing over a value the
                # platform does not actually hand back, and the
                # suppression keeps a failed restore from masking the
                # result the caller is waiting for.
                signal.signal(
                    signal.SIGINT,
                    signal.SIG_DFL if previous_sigint is None else previous_sigint,
                )
        # ``wait=False`` so the caller's thread is not held by a worker
        # that is already stopping.
        pool.shutdown(wait=False, cancel_futures=True)
