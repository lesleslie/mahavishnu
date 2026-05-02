"""RunPod Flash worker pool.

Executes GPU tasks on RunPod serverless infrastructure via the runpod-flash SDK.
Workers scale automatically from 0 to N — no persistent worker management needed.

Cold start: 30-60s on first invocation. Subsequent calls: 2-3s.
Do not use for latency-sensitive routing; prefer for VISION/REASONING batch work.
"""

import asyncio
import collections
import logging
import time
from typing import Any

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

logger = logging.getLogger(__name__)

try:
    from runpod_flash import Endpoint, GpuType
except ImportError:
    Endpoint = None  # type: ignore[assignment]
    GpuType = None  # type: ignore[assignment]


class RunPodPool(BasePool):
    """RunPod serverless GPU pool backed by runpod-flash.

    Each pool maps to one Flash endpoint (one GPU type, one set of dependencies).
    Spawn separate pools for different hardware configs (e.g. RTX 4090 vs A100).

    Cold-start note: First invocation takes 30-60s while RunPod provisions
    the worker. Subsequent calls within the keep-alive window take 2-3s.
    """

    def __init__(self, config: PoolConfig, pool_id: str | None = None) -> None:
        super().__init__(config, pool_id)
        self._endpoint: Any = None
        self._task_results: collections.deque[dict[str, Any]] = collections.deque(maxlen=1000)
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

        self._api_key: str = config.get("api_key", "")
        self._gpu_type: str = config.get("gpu_type", "NVIDIA_GEFORCE_RTX_4090")
        self._endpoint_name: str = config.get("endpoint_name", "mahavishnu-worker")
        self._dependencies: list[str] = config.get("dependencies", [])
        self._num_workers: int = config.get("num_workers", 3)

    async def start(self) -> str:
        self._status = PoolStatus.INITIALIZING
        try:
            self._endpoint = self._build_endpoint()
            self._status = PoolStatus.RUNNING
            logger.info(
                "RunPodPool %s started (endpoint=%s, gpu=%s)",
                self.pool_id, self._endpoint_name, self._gpu_type,
            )
        except Exception as e:
            self._status = PoolStatus.FAILED
            logger.error("RunPodPool failed to start: %s", e)
            raise
        return self.pool_id

    def _build_endpoint(self) -> Any:
        if Endpoint is None:
            raise RuntimeError(
                "RunPodPool requires 'runpod-flash'. Install with: uv add runpod-flash"
            )

        gpu = getattr(GpuType, self._gpu_type, None)
        if gpu is None:
            raise ValueError(
                f"Unknown GpuType: {self._gpu_type}. "
                f"Valid values: {[g.name for g in GpuType]}"
            )

        deps = self._dependencies

        @Endpoint(
            name=self._endpoint_name,
            gpu=gpu,
            workers=self._num_workers,
            dependencies=deps,
        )
        def _run_task(task_payload: dict) -> dict:
            # Override _build_endpoint in a subclass to provide a real GPU handler.
            raise NotImplementedError(
                "RunPodPool._run_task is a stub. "
                "Subclass RunPodPool and override _build_endpoint to register a real handler."
            )

        return _run_task

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if self._endpoint is None:
            return {
                "pool_id": self.pool_id,
                "worker_id": "none",
                "status": "failed",
                "output": None,
                "error": "Pool not started — call start() first",
                "duration": 0.0,
            }

        start_time = time.time()
        worker_id = f"{self._endpoint_name}-{int(start_time)}"

        try:
            output = await self._endpoint(task)
            duration = time.time() - start_time
            self._tasks_completed += 1
            self._task_durations.append(duration)
            self._task_results.append({
                "worker_id": worker_id,
                "output": output,
                "status": "completed",
                "timestamp": start_time,
            })
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "completed",
                "output": output,
                "error": None,
                "duration": duration,
            }

        except TimeoutError as e:
            self._tasks_failed += 1
            duration = time.time() - start_time
            logger.error("RunPod task timed out after %.1fs: %s", duration, e)
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "timeout",
                "output": None,
                "error": str(e),
                "duration": duration,
            }

        except Exception as e:
            self._tasks_failed += 1
            duration = time.time() - start_time
            logger.error("RunPod task failed: %s", e)
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": str(e),
                "duration": duration,
            }

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        results = await asyncio.gather(*(self.execute_task(t) for t in tasks))
        return {str(i): r for i, r in enumerate(results)}

    async def scale(self, target_worker_count: int) -> None:
        logger.info(
            "RunPodPool scales automatically via Flash. Target %d not applicable.",
            target_worker_count,
        )

    async def health_check(self) -> dict[str, Any]:
        if self._endpoint is None or self._status != PoolStatus.RUNNING:
            return {
                "pool_id": self.pool_id,
                "pool_type": "runpod",
                "status": "unhealthy",
                "endpoint": self._endpoint_name,
                "reason": "endpoint not registered",
            }
        return {
            "pool_id": self.pool_id,
            "pool_type": "runpod",
            "status": "healthy",
            "endpoint": self._endpoint_name,
            "gpu_type": self._gpu_type,
            "workers_configured": self._num_workers,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
        }

    async def get_metrics(self) -> PoolMetrics:
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations)
            if self._task_durations else 0.0
        )
        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=self._num_workers if self._status == PoolStatus.RUNNING else 0,
            total_workers=self._num_workers,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            avg_task_duration=avg_duration,
            memory_usage_mb=0.0,
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        items = [
            {
                "content": str(r.get("output", "")),
                "metadata": {
                    "type": "pool_worker_execution",
                    "pool_id": self.pool_id,
                    "pool_type": "runpod",
                    "worker_id": r["worker_id"],
                    "status": r["status"],
                    "timestamp": r["timestamp"],
                },
            }
            for r in self._task_results
        ]
        self._task_results.clear()
        logger.info("Collected %d memory items from RunPodPool %s", len(items), self.pool_id)
        return items

    async def stop(self) -> None:
        logger.info("Stopping RunPodPool %s...", self.pool_id)
        self._endpoint = None
        self._task_results.clear()
        self._status = PoolStatus.STOPPED
        logger.info("RunPodPool %s stopped", self.pool_id)
