"""Worker lifecycle management and orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from monitoring.metrics import (
    agent_task_duration_seconds,
    agent_tasks_in_progress,
    agent_tasks_total,
)

from .base import BaseWorker, WorkerResult, WorkerStatus
from .capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
    invalidate_capability,
)
from .registry import get_worker_config

if TYPE_CHECKING:
    from ..core.config import MahavishnuSettings
    from ..terminal.manager import TerminalManager

logger = logging.getLogger(__name__)


def _create_isolated_worker(
    worker_type: str,
    session_buddy_client: Any,
    kwargs: dict[str, Any],
) -> BaseWorker:
    """Create an isolated-execution worker using tiered microVM isolation.

    Tier 1 is the local Apple ``container`` runtime (Apple silicon only);
    when the host cannot run it, fall through to the E2B cloud sandbox
    tier. An explicit ``e2b-sandbox`` worker type skips tier 1 entirely.
    """
    from ..core.errors import AppleContainerUnsupported
    from .e2b_sandbox import E2BSandboxWorker

    if worker_type != "e2b-sandbox":
        try:
            from .apple_container import AppleContainerWorker

            return AppleContainerWorker(
                image=kwargs.get("image", "python:3.13-slim"),
                session_buddy_client=session_buddy_client,
                cpus=kwargs.get("cpus"),
                memory=kwargs.get("memory"),
            )
        except AppleContainerUnsupported as exc:
            logger.info(
                "Apple container tier unavailable (%s); using E2B sandbox tier",
                exc.details.get("reason", "unsupported host"),
            )
    return E2BSandboxWorker(
        template=kwargs.get("template", "base"),
        timeout=kwargs.get("timeout", 300),
        session_buddy_client=session_buddy_client,
    )


class WorkerManager:
    """Manage worker lifecycle for concurrent task execution.

    Features:
    - Spawn multiple workers of different types
    - Submit one-shot prompts to single-task workers
    - Monitor worker progress
    - Collect results with aggregation
    - Handle failures with retries
    - Support for terminal, container, and application workers

    Args:
        terminal_manager: TerminalManager for terminal session control
        max_concurrent: Maximum number of concurrent workers
        session_buddy_client: Optional Session-Buddy MCP client
        mcp_client: Optional MCP client for application workers
        settings: Optional MahavishnuSettings used for capability evaluation
    """

    def __init__(
        self,
        terminal_manager: TerminalManager,
        max_concurrent: int = 10,
        session_buddy_client: Any = None,
        mcp_client: Any = None,
        *,
        settings: MahavishnuSettings | None = None,
    ) -> None:
        """Initialize worker manager.

        Args:
            terminal_manager: TerminalManager instance
            max_concurrent: Maximum concurrent workers (1-100)
            session_buddy_client: Session-Buddy MCP client
            mcp_client: MCP client for application workers
            settings: Optional MahavishnuSettings for capability evaluation
        """
        self.terminal_manager = terminal_manager
        self.max_concurrent = max(1, min(max_concurrent, 100))
        self.session_buddy_client = session_buddy_client
        self.mcp_client = mcp_client
        self.settings = settings
        self._workers: dict[str, BaseWorker] = {}
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        logger.info(f"Initialized WorkerManager (max_concurrent={self.max_concurrent})")

    def list_worker_ids(self) -> list[str]:
        """Return IDs of all currently registered workers."""
        return list(self._workers.keys())

    def _require_ready(self, worker_type: str) -> None:
        """Evaluate capabilities and raise if the worker is not READY.

        Imports lazily to avoid a circular import through core.errors.
        """
        report = evaluate_worker_capabilities(worker_type, settings=self.settings)
        if report.state is not WorkerCapabilityState.READY:
            from ..core.errors import WorkerUnavailableError

            raise WorkerUnavailableError(
                worker_type=worker_type,
                state=report.state.value,
                missing_requirements=report.missing_requirements,
                message=report.safe_reason or "static prerequisites missing",
            )

    async def submit_workers(
        self,
        worker_type: str,
        prompts: list[str],
        *,
        runtime_kwargs: dict[str, Any] | None = None,
    ) -> list[str]:
        """Submit prompts to a one-shot worker, launching one session per prompt.

        Args:
            worker_type: Worker type to use (must be registered and one_shot).
            prompts: One prompt per session to launch.
            runtime_kwargs: Optional kwargs forwarded to the worker factory.

        Returns:
            List of newly-created worker session IDs in the same order as ``prompts``.

        Raises:
            ValueError: If ``worker_type`` is not registered as one_shot.
            WorkerUnavailableError: If capability evaluation rejects the worker.
        """
        cfg = get_worker_config(worker_type)
        if cfg is None or not cfg.one_shot:
            raise ValueError(f"Worker {worker_type!r} is not a one-shot worker")
        self._require_ready(worker_type)

        worker_ids: list[str] = []
        try:
            for prompt in prompts:
                worker = self._create_worker(worker_type, **(runtime_kwargs or {}))
                worker_id = await worker.start(prompt=prompt)
                self._workers[worker_id] = worker
                worker_ids.append(worker_id)
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            for wid in worker_ids:
                await self.close_worker(wid)
            invalidate_capability(worker_type)
            # Capability transition broadcast for the failure is handled by the
            # next _require_ready call, which re-evaluates and emits a
            # transition event if the state changes. We deliberately avoid
            # importing emit_transition here to keep this rollback free of
            # new top-level dependencies.
            raise
        return worker_ids

    async def spawn_workers(
        self,
        worker_type: str,
        count: int,
        task_spec: dict[str, Any] | None = None,
    ) -> list[str]:
        """Spawn multiple workers of specified type.

        Args:
            worker_type: Type of worker ("terminal-qwen" [legacy], "terminal-claude", "terminal-codex", "container")
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

        return worker_ids

    def _create_worker(self, worker_type: str, **kwargs: Any) -> BaseWorker:
        """Factory method for worker creation.

        Args:
            worker_type: Type of worker to create
            **kwargs: Additional parameters for worker (e.g., host for SSH)

        Returns:
            Configured worker instance

        Raises:
            ValueError: If worker_type is unknown
        """
        # Import registry for worker type lookup
        from .registry import WorkerCategory, get_worker_config

        # Get worker config from registry
        config = get_worker_config(worker_type)

        if config is None:
            raise ValueError(f"Unknown worker type: {worker_type}")

        # Create worker based on category
        if config.category == WorkerCategory.CONTAINER:
            return _create_isolated_worker(
                config.worker_type,
                self.session_buddy_client,
                kwargs,
            )

        elif config.category in (
            WorkerCategory.SHELL,
            WorkerCategory.REMOTE,
        ):
            # Use GenericShellWorker for shell/REPL/SSH types
            from .generic_shell import GenericShellWorker

            return GenericShellWorker(
                terminal_manager=self.terminal_manager,
                worker_type=worker_type,
                config=config,
                session_buddy_client=self.session_buddy_client,
                **kwargs,
            )

        elif config.category == WorkerCategory.AI_ASSISTANT:
            # AI assistants: dedicated class for HTTP-API workers (terminal-crow),
            # fall through to GenericShellWorker for shell-launched ones.
            if worker_type == "terminal-crow":
                from .crow import CrowWorker

                return CrowWorker()

            from .generic_shell import GenericShellWorker

            return GenericShellWorker(
                terminal_manager=self.terminal_manager,
                worker_type=worker_type,
                config=config,
                session_buddy_client=self.session_buddy_client,
                **kwargs,
            )

        elif config.category == WorkerCategory.APPLICATION:
            # Application workers via MCP
            from .application import ApplicationWorker

            if self.mcp_client is None:
                raise ValueError(
                    f"Application worker '{worker_type}' requires MCP client. "
                    f"Provide mcp_client parameter to WorkerManager."
                )

            return ApplicationWorker(
                worker_type=worker_type,
                mcp_client=self.mcp_client,
                config=config,
                session_buddy_client=self.session_buddy_client,
                **kwargs,
            )

        elif config.category == WorkerCategory.GATEWAY:
            # Gateway workers (HTTP/RPC integration)
            if worker_type == "gateway-openclaw":
                from .openclaw_gateway import (
                    HTTPOpenClawGatewayClient,
                    OpenClawGatewayConfig,
                    OpenClawGatewayWorker,
                )

                gateway_url = kwargs.get(
                    "gateway_url",
                    os.getenv("OPENCLAW_GATEWAY_URL", "http://localhost:8787"),
                )
                token = kwargs.get("token", os.getenv("OPENCLAW_GATEWAY_TOKEN"))
                rpc_path = kwargs.get(
                    "rpc_path",
                    os.getenv("OPENCLAW_GATEWAY_RPC_PATH", "/rpc"),
                )
                timeout = float(kwargs.get("timeout", config.default_timeout))
                default_method = kwargs.get("default_method", "agent.run")

                gateway_client = HTTPOpenClawGatewayClient(
                    base_url=gateway_url,
                    token=token,
                    rpc_path=rpc_path,
                    timeout=timeout,
                )
                gateway_config = OpenClawGatewayConfig(
                    gateway_url=gateway_url,
                    token=token,
                    default_method=default_method,
                    default_timeout=int(timeout),
                )
                return OpenClawGatewayWorker(
                    gateway_client=gateway_client,
                    config=gateway_config,
                )

            if worker_type == "openhands":
                from .openhands import OpenHandsWorker

                return OpenHandsWorker()

            if worker_type == "a2a":
                from .a2a import A2AAgentConfig, A2AWorker

                agent_configs = kwargs.get("agent_configs")
                if agent_configs is None and self.settings is not None:
                    a2a_settings = getattr(self.settings, "a2a", None)
                    settings_agents = (
                        getattr(a2a_settings, "agents", None) if a2a_settings is not None else None
                    )
                    if isinstance(settings_agents, dict):
                        agent_configs = settings_agents
                    elif settings_agents:
                        agent_configs = {
                            entry.name: A2AAgentConfig(
                                name=entry.name,
                                url=entry.url,
                                description=entry.description,
                                api_key=(
                                    os.getenv(entry.api_key_env) if entry.api_key_env else None
                                ),
                            )
                            for entry in settings_agents
                        }
                return A2AWorker(agent_configs=agent_configs or {})

            raise ValueError(f"Unknown gateway worker type: {worker_type}")

        else:
            # Fallback - try GenericShellWorker
            from .generic_shell import GenericShellWorker

            return GenericShellWorker(
                terminal_manager=self.terminal_manager,
                worker_type=worker_type,
                config=config,
                session_buddy_client=self.session_buddy_client,
                **kwargs,
            )

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

        worker_type = getattr(worker, "worker_type", "unknown")
        adapter = "worker_manager"

        async with self._semaphore:
            agent_tasks_in_progress.labels(agent_type=worker_type, adapter=adapter).inc()
            try:
                logger.info(f"Executing task on worker {worker_id}")
                result = await worker.execute(task)
                agent_tasks_total.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                    status=result.status.value,
                ).inc()
                agent_task_duration_seconds.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                ).observe(result.duration_seconds)
                logger.info(
                    f"Worker {worker_id} completed: {result.status.value} "
                    f"({result.duration_seconds:.2f}s)"
                )
                return result
            except Exception as e:  # noqa: BLE001 - boundary preserves structured backend failure handling
                logger.error(f"Worker {worker_id} failed: {e}")
                failure_result = WorkerResult(
                    worker_id=worker_id,
                    status=WorkerStatus.FAILED,
                    output=None,
                    error=str(e),
                    exit_code=None,
                    duration_seconds=0,
                    metadata={"exception": type(e).__name__},
                )
                agent_tasks_total.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                    status=failure_result.status.value,
                ).inc()
                agent_task_duration_seconds.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                ).observe(failure_result.duration_seconds)
                return failure_result
            finally:
                agent_tasks_in_progress.labels(agent_type=worker_type, adapter=adapter).dec()

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
        coros = [execute_one(wid, task) for wid, task in zip(worker_ids, tasks, strict=False)]
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
                except Exception as e:  # noqa: BLE001 - boundary preserves structured backend failure handling
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
                except Exception as e:  # noqa: BLE001 - boundary preserves structured backend failure handling
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
            except Exception as e:  # noqa: BLE001 - boundary preserves structured backend failure handling
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

    async def list_workers(self) -> list[dict[str, Any]]:
        """List all active workers.

        Returns:
            List of worker information dictionaries
        """
        workers_info = []

        for wid, worker in self._workers.items():
            try:
                status = await worker.status()
                workers_info.append(
                    {
                        "worker_id": wid,
                        "worker_type": worker.worker_type,
                        "status": status.value,
                    }
                )
            except Exception:  # noqa: BLE001 - boundary preserves structured backend failure handling
                workers_info.append(
                    {
                        "worker_id": wid,
                        "worker_type": worker.worker_type,
                        "status": "unknown",
                    }
                )

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
            "workers": workers_list,
        }
