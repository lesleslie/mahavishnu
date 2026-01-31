"""Worker lifecycle management and orchestration."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..terminal.manager import TerminalManager
from .base import BaseWorker, WorkerResult, WorkerStatus
from .container import ContainerWorker
from .terminal import TerminalAIWorker

logger = logging.getLogger(__name__)


class WorkerManager:
    """Manage worker lifecycle for concurrent task execution.

    Features:
    - Spawn multiple workers of different types
    - Monitor worker progress
    - Collect results with aggregation
    - Handle failures with retries
    - Debug monitor auto-launch

    Args:
        terminal_manager: TerminalManager for terminal session control
        max_concurrent: Maximum number of concurrent workers
        debug_mode: Enable debug monitor auto-launch
        session_buddy_client: Optional Session-Buddy MCP client
    """

    def __init__(
        self,
        terminal_manager: TerminalManager,
        max_concurrent: int = 10,
        debug_mode: bool = False,
        session_buddy_client: Any = None,
    ) -> None:
        """Initialize worker manager.

        Args:
            terminal_manager: TerminalManager instance
            max_concurrent: Maximum concurrent workers (1-100)
            debug_mode: Enable debug monitor
            session_buddy_client: Session-Buddy MCP client
        """
        self.terminal_manager = terminal_manager
        self.max_concurrent = max(1, min(max_concurrent, 100))
        self.debug_mode = debug_mode
        self.session_buddy_client = session_buddy_client
        self._workers: dict[str, BaseWorker] = {}
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._debug_monitor_worker: BaseWorker | None = None

        logger.info(
            f"Initialized WorkerManager "
            f"(max_concurrent={self.max_concurrent}, debug={debug_mode})"
        )

    async def spawn_workers(
        self,
        worker_type: str,
        count: int,
        task_spec: dict[str, Any] | None = None,
    ) -> list[str]:
        """Spawn multiple workers of specified type.

        Args:
            worker_type: Type of worker ("terminal-qwen", "terminal-claude", "container")
            count: Number of workers to spawn
            task_spec: Optional task specification for immediate execution

        Returns:
            List of worker IDs

        Raises:
            ValueError: If worker_type is unknown
        """
        worker_ids = []

        for _ in range(count):
            worker = self._create_worker(worker_type)
            worker_id = await worker.start()
            self._workers[worker_id] = worker
            worker_ids.append(worker_id)

        logger.info(f"Spawned {len(worker_ids)} {worker_type} workers")

        # Launch debug monitor if debug mode enabled
        if self.debug_mode:
            await self._launch_debug_monitor()

        return worker_ids

    def _create_worker(self, worker_type: str) -> BaseWorker:
        """Factory method for worker creation.

        Args:
            worker_type: Type of worker to create

        Returns:
            Configured worker instance

        Raises:
            ValueError: If worker_type is unknown
        """
        if worker_type == "terminal-qwen":
            return TerminalAIWorker(
                self.terminal_manager,
                ai_type="qwen",
                session_buddy_client=self.session_buddy_client,
            )
        elif worker_type == "terminal-claude":
            return TerminalAIWorker(
                self.terminal_manager,
                ai_type="claude",
                session_buddy_client=self.session_buddy_client,
            )
        elif worker_type == "container-executor" or worker_type == "container":
            # Container workers (Phase 3 - now implemented!)
            return ContainerWorker(
                runtime="docker",  # Default to docker
                image="python:3.13-slim",
                session_buddy_client=self.session_buddy_client,
            )
        else:
            raise ValueError(f"Unknown worker type: {worker_type}")

    async def execute_task(
        self,
        worker_id: str,
        task: dict[str, Any],
    ) -> WorkerResult:
        """Execute task on specific worker.

        Args:
            worker_id: Worker ID
            task: Task specification

        Returns:
            WorkerResult with execution results

        Raises:
            ValueError: If worker not found
        """
        worker = self._workers.get(worker_id)
        if not worker:
            raise ValueError(f"Worker not found: {worker_id}")

        async with self._semaphore:
            try:
                logger.info(f"Executing task on worker {worker_id}")
                result = await worker.execute(task)
                logger.info(
                    f"Worker {worker_id} completed: {result.status.value} "
                    f"({result.duration_seconds:.2f}s)"
                )
                return result
            except Exception as e:
                logger.error(f"Worker {worker_id} failed: {e}")
                return WorkerResult(
                    worker_id=worker_id,
                    status=WorkerStatus.FAILED,
                    output=None,
                    error=str(e),
                    exit_code=None,
                    duration_seconds=0,
                    metadata={"exception": type(e).__name__},
                )

    async def execute_batch(
        self,
        worker_ids: list[str],
        tasks: list[dict[str, Any]],
    ) -> dict[str, WorkerResult]:
        """Execute tasks on multiple workers concurrently.

        Args:
            worker_ids: List of worker IDs
            tasks: List of task specs (same length as worker_ids)

        Returns:
            Dictionary mapping worker_id -> WorkerResult

        Raises:
            ValueError: If worker_ids and tasks length mismatch
        """
        if len(worker_ids) != len(tasks):
            raise ValueError("worker_ids and tasks must have same length")

        async def execute_one(worker_id: str, task: dict[str, Any]) -> tuple[str, WorkerResult]:
            result = await self.execute_task(worker_id, task)
            return worker_id, result

        # Execute all tasks concurrently
        coros = [
            execute_one(wid, task)
            for wid, task in zip(worker_ids, tasks)
        ]
        results = await asyncio.gather(*coros)

        logger.info(f"Completed {len(results)} worker tasks")

        return dict(results)

    async def monitor_workers(
        self,
        worker_ids: list[str] | None = None,
        interval: float = 1.0,
    ) -> dict[str, WorkerStatus]:
        """Monitor status of multiple workers.

        Args:
            worker_ids: List of worker IDs (None = all workers)
            interval: Polling interval in seconds

        Returns:
            Dictionary mapping worker_id -> status
        """
        if worker_ids is None:
            worker_ids = list(self._workers.keys())

        statuses = {}

        for wid in worker_ids:
            worker = self._workers.get(wid)
            if worker:
                try:
                    status = await worker.status()
                    statuses[wid] = status
                except Exception as e:
                    logger.warning(f"Failed to get status for {wid}: {e}")
                    statuses[wid] = WorkerStatus.FAILED

        await asyncio.sleep(interval)
        return statuses

    async def collect_results(
        self,
        worker_ids: list[str] | None = None,
    ) -> dict[str, WorkerResult]:
        """Collect results from completed workers.

        Args:
            worker_ids: List of worker IDs (None = all workers)

        Returns:
            Dictionary mapping worker_id -> WorkerResult
        """
        if worker_ids is None:
            worker_ids = list(self._workers.keys())

        results = {}

        for wid in worker_ids:
            worker = self._workers.get(wid)
            if worker:
                try:
                    # Get final output/status
                    progress = await worker.get_progress()

                    # Build result from progress
                    status = WorkerStatus(progress.get("status", "unknown"))
                    results[wid] = WorkerResult(
                        worker_id=wid,
                        status=status,
                        output=progress.get("output_preview"),
                        error=None,
                        exit_code=0 if status == WorkerStatus.COMPLETED else 1,
                        duration_seconds=progress.get("duration_seconds", 0),
                        metadata=progress,
                    )
                except Exception as e:
                    logger.error(f"Failed to collect result from {wid}: {e}")
                    results[wid] = WorkerResult(
                        worker_id=wid,
                        status=WorkerStatus.FAILED,
                        output=None,
                        error=str(e),
                        exit_code=None,
                        duration_seconds=0,
                        metadata={"error": str(e)},
                    )

        return results

    async def close_worker(self, worker_id: str) -> None:
        """Close a specific worker.

        Args:
            worker_id: Worker ID to close
        """
        worker = self._workers.get(worker_id)
        if worker:
            try:
                await worker.stop()
                logger.info(f"Closed worker {worker_id}")
            except Exception as e:
                logger.error(f"Failed to close worker {worker_id}: {e}")
            finally:
                self._workers.pop(worker_id, None)

    async def close_all(self) -> None:
        """Close all active workers."""
        worker_ids = list(self._workers.keys())
        if worker_ids:
            logger.info(f"Closing {len(worker_ids)} workers...")
            tasks = [self.close_worker(wid) for wid in worker_ids]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Close debug monitor
        if self._debug_monitor_worker:
            try:
                await self._debug_monitor_worker.stop()
            except Exception:
                pass
            finally:
                self._debug_monitor_worker = None

    async def _launch_debug_monitor(self) -> None:
        """Launch iTerm2 debug log monitor."""
        if self._debug_monitor_worker:
            return  # Already launched

        try:
            # Get debug log path from logging config
            logger_instance = logging.getLogger()
            log_path = None

            for handler in logger_instance.handlers:
                if hasattr(handler, "baseFilename"):
                    log_path = Path(handler.baseFilename)
                    break

            if not log_path:
                logger.warning("Could not determine debug log path")
                return

            # Import debug monitor worker (if available)
            try:
                from .debug_monitor import DebugMonitorWorker

                self._debug_monitor_worker = DebugMonitorWorker(
                    log_path=log_path,
                    terminal_manager=self.terminal_manager,
                    session_buddy_client=self.session_buddy_client,
                )

                monitor_id = await self._debug_monitor_worker.start()
                logger.info(f"Launched debug monitor: {monitor_id}")

            except ImportError:
                logger.warning("DebugMonitorWorker not yet implemented (Phase 3)")

        except Exception as e:
            logger.error(f"Failed to launch debug monitor: {e}")

    async def list_workers(self) -> list[dict[str, Any]]:
        """List all active workers.

        Returns:
            List of worker information dictionaries
        """
        workers_info = []

        for wid, worker in self._workers.items():
            try:
                status = await worker.status()
                workers_info.append({
                    "worker_id": wid,
                    "worker_type": worker.worker_type,
                    "status": status.value,
                })
            except Exception:
                workers_info.append({
                    "worker_id": wid,
                    "worker_type": worker.worker_type,
                    "status": "unknown",
                })

        return workers_info

    async def health_check(self) -> dict[str, Any]:
        """Get worker system health.

        Returns:
            Dictionary with health status
        """
        workers_list = await self.list_workers()

        return {
            "status": "healthy",
            "workers_active": len(workers_list),
            "max_concurrent": self.max_concurrent,
            "debug_mode": self.debug_mode,
            "debug_monitor_active": self._debug_monitor_worker is not None,
            "workers": workers_list,
        }
