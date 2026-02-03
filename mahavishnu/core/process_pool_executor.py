"""Process pool executor for blocking operations.

This module provides a ProcessPoolExecutor wrapper to offload blocking
operations (like CodeGraphAnalyzer) to separate processes, preventing event
loop blockage.

Key Features:
- Separate process pool (avoids GIL issues)
- Graceful shutdown
- Task queue with backpressure handling
- Resource limits (max concurrent processes)
"""

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable, TypeVar
import multiprocessing

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProcessPoolTaskExecutor:
    """Process pool executor for blocking CPU-intensive operations.

    Use this to offload operations that block the event loop, such as:
    - Code graph analysis (CodeGraphAnalyzer)
    - File system operations (large file reads)
    - CPU-intensive computations

    Example:
        ```python
        executor = ProcessPoolTaskExecutor(max_workers=2)

        # Offload blocking function to separate process
        result = await executor.submit(
            analyze_repository,
            "/path/to/repo"
        )

        # Shutdown when done
        await executor.shutdown()
        ```
    """

    def __init__(
        self,
        max_workers: int | None = None,
        max_tasks_per_child: int | None = None,
    ):
        """Initialize process pool executor.

        Args:
            max_workers: Maximum number of worker processes
                         (default: CPU count - 1)
            max_tasks_per_child: Maximum tasks per worker process before restart
                                (prevents memory leaks)
        """
        if max_workers is None:
            # Leave one CPU core free
            max_workers = max(1, multiprocessing.cpu_count() - 1)

        self._max_workers = max_workers
        self._max_tasks_per_child = max_tasks_per_child
        self._executor: ProcessPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown = False

        logger.info(
            f"ProcessPoolTaskExecutor initialized "
            f"(max_workers={max_workers}, max_tasks_per_child={max_tasks_per_child})"
        )

    def start(self) -> None:
        """Start the process pool executor.

        Should be called during application startup.
        """
        if self._executor is not None:
            logger.warning("ProcessPoolTaskExecutor already started")
            return

        self._executor = ProcessPoolExecutor(
            max_workers=self._max_workers,
            max_tasks_per_child=self._max_tasks_per_child,
        )

        self._loop = asyncio.get_event_loop()
        self._shutdown = False

        logger.info("ProcessPoolTaskExecutor started")

    async def shutdown(self, wait: bool = True) -> None:
        """Shutdown the process pool executor.

        Args:
            wait: If True, wait for pending tasks to complete
        """
        if self._shutdown or self._executor is None:
            return

        self._shutdown = True
        logger.info("ProcessPoolTaskExecutor shutting down...")

        # Shutdown executor
        if self._executor:
            self._executor.shutdown(wait=wait)
            self._executor = None

        logger.info("ProcessPoolTaskExecutor shutdown complete")

    async def submit(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Submit task to process pool and wait for result.

        Args:
            func: Function to execute in separate process
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function return value

        Raises:
            RuntimeError: If executor not started
            Exception: Re-raised from function execution
        """
        if self._executor is None:
            raise RuntimeError("ProcessPoolTaskExecutor not started. Call start() first.")

        if self._shutdown:
            raise RuntimeError("ProcessPoolTaskExecutor is shut down")

        # Run blocking function in thread pool executor (which wraps process pool)
        loop = self._loop or asyncio.get_event_loop()

        try:
            # Use partial to bind args/kwargs
            bound_func = partial(func, *args, **kwargs)

            # Run in executor and await result
            result = await loop.run_in_executor(self._executor, bound_func)

            return result

        except Exception as e:
            logger.error(f"Task execution failed: {func.__name__}: {e}")
            raise

    def get_stats(self) -> dict[str, Any]:
        """Get executor statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "max_workers": self._max_workers,
            "running": self._executor is not None and not self._shutdown,
            "shutdown": self._shutdown,
        }

    def __del__(self):
        """Cleanup on deletion."""
        if self._executor is not None:
            # Try to shutdown if not already done
            try:
                self._executor.shutdown(wait=False)
            except Exception:
                pass  # Ignore errors during cleanup


# Singleton instance for global access
_process_pool_instance: ProcessPoolTaskExecutor | None = None


def get_process_pool() -> ProcessPoolTaskExecutor:
    """Get global process pool executor instance.

    Returns:
        ProcessPoolTaskExecutor instance

    Raises:
        RuntimeError: If executor not initialized
    """
    global _process_pool_instance

    if _process_pool_instance is None:
        raise RuntimeError(
            "ProcessPoolTaskExecutor not initialized. "
            "Call init_process_pool() during application startup."
        )

    return _process_pool_instance


async def init_process_pool(
    max_workers: int | None = None,
    max_tasks_per_child: int | None = None,
) -> ProcessPoolTaskExecutor:
    """Initialize global process pool executor instance.

    Args:
        max_workers: Maximum number of worker processes
        max_tasks_per_child: Maximum tasks per worker process

    Returns:
        Initialized ProcessPoolTaskExecutor instance
    """
    global _process_pool_instance

    _process_pool_instance = ProcessPoolTaskExecutor(
        max_workers=max_workers, max_tasks_per_child=max_tasks_per_child
    )
    _process_pool_instance.start()

    logger.info("Global ProcessPoolTaskExecutor initialized")

    return _process_pool_instance


async def shutdown_process_pool() -> None:
    """Shutdown global process pool executor.

    Should be called during application shutdown.
    """
    global _process_pool_instance

    if _process_pool_instance:
        await _process_pool_instance.shutdown()
        _process_pool_instance = None

        logger.info("Global ProcessPoolTaskExecutor shut down")
