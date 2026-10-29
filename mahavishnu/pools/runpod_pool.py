"""RunPod serverless GPU pool — runpod SDK 2.0 thin client.

from __future__ import annotations

Executes GPU tasks against a pre-existing RunPod serverless endpoint by
id (one GPU type, one dependency set per endpoint — handler logic and
hardware config are operator-managed in the RunPod console or via the
SDK's endpoint-create call).

Cold start: 30-60s on first invocation. Subsequent calls: 2-3s.
Do not use for latency-sensitive routing; prefer for VISION / REASONING
batch work.

Migration: 2026-10-17 moved off ``runpod-flash`` → ``runpod`` SDK 2.0,
which merged the Flash API. The legacy @Endpoint decorator used to
register a worker function in this codebase; SDK 2.0 makes
``runpod.Endpoint(endpoint_id)`` a *client* handle — handler logic now
lives in the RunPod endpoint config. ``_build_endpoint()`` has been
removed; configure workers via the RunPod console or
``runpod.serverless.start({...})`` in a dedicated handler repo.

Status truth (2026-10-17 hardening): ``req.output()`` is the
authoritative terminal oracle — it returns on COMPLETED and raises on
FAILED. ``req.status()`` is a non-blocking snapshot that can return
IN_QUEUE/IN_PROGRESS mid-flight and is NEVER used to infer the job's
terminal state. The pool only consults ``.status()`` AFTER ``.output()``
has settled, and only for telemetry: a non-COMPLETED status at that
point triggers a warning (defensive against SDK contract drift) but
the caller still receives ``status="completed"`` because ``.output()``
returned. Failed jobs are caught by the ``except Exception`` branch
when ``.output()`` raises.

Authorisation: SDK 2.0 reads ``RUNPOD_API_KEY`` from the environment.
The ``api_key`` config field is retained for backward compatibility
but unused at dispatch time.
"""

import asyncio
import collections
import importlib
import logging
import time
from typing import Any

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

logger = logging.getLogger(__name__)

# The ``runpod`` SDK 2.0 is an OPTIONAL dependency — deliberately NOT a
# project dependency. The ``gpu`` dependency group was emptied on
# 2026-10-24 because the SDK pins ``boto3`` versions that conflict with
# oneiric's ``aiobotocore`` floor; operators who want the RunPod
# provider install it themselves (``uv pip install "runpod>=2.0.0rc1"``).
#
# The module is therefore resolved dynamically: this file imports cleanly
# with or without the SDK, and static analysis does not demand a package
# that is intentionally absent from the dependency graph. ``runpod``
# stays a module-level name so a stub can be injected (tests, operators)
# without touching the import machinery.
runpod: Any
try:
    runpod = importlib.import_module("runpod")
except ImportError:
    runpod = None


class RunPodPool(BasePool):
    """RunPod serverless GPU pool — thin client to a pre-configured endpoint.

    Each pool binds to one RunPod serverless endpoint id. Spawn separate
    pools for different endpoint configs (e.g. RTX 4090 vs A100).

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

        # Required: the runpod serverless endpoint id this pool points at.
        endpoint_id = config.get("endpoint_id")
        if not endpoint_id:
            raise ValueError(
                "RunPodPool requires 'endpoint_id' in config — point at a "
                "pre-existing RunPod serverless endpoint id (GPU type, "
                "dependencies, and handler are configured server-side)."
            )
        self._endpoint_id: str = str(endpoint_id)

        # Optional metadata — informational only; the endpoint's actual
        # GPU type / dependencies live in the RunPod console, not here.
        self._api_key: str = config.get("api_key", "")
        self._gpu_type: str = config.get("gpu_type", "")
        self._endpoint_name: str = config.get("endpoint_name", "")
        self._dependencies: list[str] = config.get("dependencies", [])
        self._num_workers: int = config.get("num_workers", 3)

    async def start(self) -> str:
        """Construct the ``runpod.Endpoint`` client handle.

        The endpoint itself is created out-of-band (console or
        ``runpod.serverless.start({...})``); here we just bind the id.
        """
        self._status = PoolStatus.INITIALIZING
        try:
            if runpod is None:
                raise RuntimeError(
                    "RunPodPool requires the 'runpod' SDK 2.0+. "
                    "Install with: uv pip install 'runpod>=2.0.0rc1'"
                )
            self._endpoint = runpod.Endpoint(self._endpoint_id)
            self._status = PoolStatus.RUNNING
            logger.info(
                "RunPodPool %s started (endpoint_id=%s)",
                self.pool_id,
                self._endpoint_id,
            )
        except Exception as e:
            self._status = PoolStatus.FAILED
            logger.error("RunPodPool failed to start: %s", e)
            raise
        return self.pool_id

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
        worker_id = f"{self._endpoint_id}-{int(start_time)}"

        # The runpod SDK is sync (no ``async def`` in Endpoint.run /
        # .status / .output) and .output() blocks until completion.
        # Wrap the whole blocking round-trip in ``asyncio.to_thread`` so
        # the orchestrator's event loop is not stalled while polling
        # RunPod. Touching ``_endpoint`` after the ``await`` is not
        # thread-safe — read once on the main coroutine before the
        # ``to_thread`` call.
        endpoint = self._endpoint

        def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
            req = endpoint.run(payload)
            # ``req.id`` is the canonical job id; ``req.job_id`` is the
            # documented alternative in some SDK versions. Read both
            # so the pool survives minor SDK revisions.
            job_id = getattr(req, "id", None) or getattr(req, "job_id", None)
            # ``req.output()`` is the terminal oracle: it blocks until
            # the job reaches a terminal state and returns the output
            # on COMPLETED, raising an exception on FAILED.
            # ``req.status()`` is a non-blocking snapshot — it can
            # return IN_QUEUE/IN_PROGRESS at any moment — so it is
            # *never* used for state inference. The pool only consults
            # ``.status()`` AFTER ``.output()`` has settled, and only
            # for log/telemetry. ``.output()`` returning without
            # raising is the sole source of truth for "the job
            # completed".
            final_output = req.output()
            final_status = req.status()
            return {"id": job_id, "status": final_status, "output": final_output}

        try:
            env = await asyncio.to_thread(_dispatch, task)
            duration = time.time() - start_time

            # ``.output()`` returned without raising → the SDK has
            # confirmed the job reached a terminal-COMPLETED state.
            # ``env["status"]`` is captured for telemetry; if it ever
            # diverges from COMPLETED (SDK contract drift, new
            # status names) we log a warning and forward the raw
            # value — the caller still gets "completed" because
            # ``.output()`` is the source of truth.
            raw_status = (env.get("status") or "").upper()
            if raw_status and raw_status != "COMPLETED":
                logger.warning(
                    "RunPod job %s reached terminal state but SDK reports "
                    "status=%r (expected COMPLETED). Treating as completed "
                    "because .output() returned; verify SDK contract "
                    "compatibility.",
                    env.get("id"),
                    raw_status,
                )

            self._tasks_completed += 1
            self._task_durations.append(duration)
            self._task_results.append(
                {
                    "worker_id": worker_id,
                    "output": env.get("output"),
                    "status": "completed",
                    "timestamp": start_time,
                }
            )
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "completed",
                "output": env.get("output"),
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
        except Exception as e:  # Pool task execution converts every failure into a structured failed-result envelope  # noqa: BLE001, RUF100
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
        # The runpod serverless endpoint scales itself; this pool's
        # worker count is always "1" (one logical endpoint handle).
        logger.info(
            "RunPodPool scales via the serverless endpoint. Target %d not applicable.",
            target_worker_count,
        )

    async def health_check(self) -> dict[str, Any]:
        if self._endpoint is None or self._status != PoolStatus.RUNNING:
            return {
                "pool_id": self.pool_id,
                "pool_type": "runpod",
                "status": "unhealthy",
                "endpoint_id": self._endpoint_id,
                "reason": "endpoint client not constructed",
            }
        return {
            "pool_id": self.pool_id,
            "pool_type": "runpod",
            "status": "healthy",
            "endpoint_id": self._endpoint_id,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
        }

    async def get_metrics(self) -> PoolMetrics:
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0
        )
        # The serverless endpoint is one logical unit from this pool's
        # perspective — active == 1 when RUNNING, 0 otherwise.
        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=1 if self._status == PoolStatus.RUNNING else 0,
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


# Registry integration: thin factory — only ``config`` is required. ``runpod``
# SDK is lazy-imported in ``__init__`` so a missing install fails fast at
# pool-construction time rather than at module import.
def _build_runpod_pool(
    config: PoolConfig,
    **_unused_kwargs: Any,
) -> RunPodPool:
    return RunPodPool(config=config)


from ._registry import register_pool_type

register_pool_type("runpod", _build_runpod_pool)
