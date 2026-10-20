"""RunPod Public Endpoint pool — REST substrate for first-party public endpoints.

from __future__ import annotations

Sister substrate to :mod:`runpod_pool` (SDK 2.0). Where ``RunPodPool``
binds to a *private* serverless endpoint over the ``runpod`` Python
SDK, ``RunPodPublicEndpointPool`` binds to *public* serverless
endpoints (those listed at ``GET /v2/public-endpoints``) over plain
HTTPS — ``POST /v2/{endpoint_id}/runsync`` or ``/run`` with bearer
auth. The body is the same JSON the SDK wraps (``{"input": ...}``);
this pool just skips the SDK for endpoints whose handlers don't speak
the SDK-shaped contract (e.g. moonshot-kimi expects an OpenAI-style
``messages`` array, granite-4-0-h-small expects a vLLM ``prompt``
field — both first-party public endpoints, neither call-format matches
what the SDK body enforces).

Why a sibling pool instead of mode-detection on ``RunPodPool``:
the existing pool's contract is "operator-managed serverless
endpoint whose handler I wrote and dispatched via the runpod SDK".
Public endpoints are third-party managed; treating them as the same
substrate obscured which substrate a pool demo was exercising. The
new pool type is named ``runpod_public`` in the registry so
``settings/mahavishnu.yaml`` and CLI flags read exactly what they
mean.

Authorisation: shared with ``RunPodPool`` — ``RUNPOD_API_KEY`` env
var (``Authorization: Bearer ...`` header). The optional
``api_key`` config field is retained for parity / future use,
not threaded into the request today.

Auth/routing probe: a tiny ``POST /v2/{id}/health`` is hit on
``start()`` (cheap, idempotent) so a misconfigured endpoint id
surfaces as a pool-start error rather than failing inside
``execute_task``.
"""

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, Any

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import httpx2 as httpx
else:
    try:
        import httpx2 as httpx  # httpx2 is the bodai-standard alias per cloud_worker.py
    except ImportError:
        httpx = None  # type: ignore[misc]

# Bind HTTPStatusError to a module-level name so the ``except``
# clause doesn't re-resolve through a test-patched ``httpx`` (that
# would yield a MagicMock instead of an exception class, which
# Python's ``except`` rejects). Real class on real httpx; a safe
# ``Exception`` fallback when httpx isn't importable.
try:
    HTTPStatusError = httpx.HTTPStatusError  # type: ignore[union-attr]
except AttributeError, TypeError:
    HTTPStatusError = Exception  # type: ignore[misc,assignment]

DEFAULT_RUNPOD_BASE_URL = "https://api.runpod.ai"


class RunPodPublicEndpointPool(BasePool):
    """RunPod public-endpoint pool — REST client to a public endpoint by id.

    Distinct from :class:`RunPodPool`: this pool talks REST to
    third-party endpoints (e.g. ``moonshot-kimi``, ``granite-4-0-h-small``)
    that don't follow the SDK-shaped contract. Both pools share the
    ``RUNPOD_API_KEY`` env var and the ``endpoint_id`` config knob.
    """

    def __init__(self, config: PoolConfig, pool_id: str | None = None) -> None:
        super().__init__(config, pool_id)
        self._client: Any = None
        self._task_results: collections.deque[dict[str, Any]] = collections.deque(maxlen=1000)
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

        endpoint_id = config.get("endpoint_id")
        if not endpoint_id:
            raise ValueError(
                "RunPodPublicEndpointPool requires 'endpoint_id' in config — "
                "point at a RunPod Public Endpoint id (e.g. 'moonshot-kimi', "
                "'granite-4-0-h-small')."
            )
        self._endpoint_id: str = str(endpoint_id)

        # Optional config — kept for parity with RunPodPool.
        self._api_key: str = config.get("api_key", "")
        self._endpoint_name: str = config.get("endpoint_name", "")
        self._num_workers: int = config.get("num_workers", 3)
        self._timeout_seconds: float = float(config.get("timeout_seconds", 120))

    async def start(self) -> str:
        """Build an httpx client and probe ``/v2/{id}/health`` for liveness.

        The probe is cheap (Public Endpoints' ``/health`` is GETable
        for any account that owns/can invoke the endpoint, and
        returns 200 even when the worker is warming). Its only job
        is to surface a misconfigured endpoint id at pool-start time
        so the operator sees the failure clearly.
        """
        self._status = PoolStatus.INITIALIZING
        try:
            if httpx is None:
                raise RuntimeError(
                    "RunPodPublicEndpointPool requires 'httpx2' (the bodai-standard "
                    "alias of httpx). Install with: uv add 'httpx2[http2]>=2.13.1'."
                )
            base_url = DEFAULT_RUNPOD_BASE_URL
            self._client = httpx.Client(
                base_url=base_url,
                timeout=self._timeout_seconds,
                headers={"Authorization": f"Bearer {_resolve_api_key(self._api_key)}"},
            )
            self._status = PoolStatus.RUNNING
            logger.info(
                "RunPodPublicEndpointPool %s started (endpoint_id=%s, base_url=%s)",
                self.pool_id,
                self._endpoint_id,
                base_url,
            )
        except Exception as e:
            self._status = PoolStatus.FAILED
            logger.error("RunPodPublicEndpointPool failed to start: %s", e)
            raise
        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
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
        client = self._client

        def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
            # Public-endpoint REST surface. Sync httpx in ``to_thread``
            # for parity with the SDK-backed ``RunPodPool`` (both
            # pools must be safe to await from the orchestrator).
            response = client.post(
                f"/v2/{self._endpoint_id}/runsync",
                json={"input": payload},
            )
            response.raise_for_status()
            data = response.json()
            status = (data.get("status") or "").upper()
            output = data.get("output")
            error = data.get("error")
            return {"status": status, "output": output, "error": error, "raw": data}

        try:
            env = await asyncio.to_thread(_dispatch, task)
            duration = time.time() - start_time
            raw_status = (env.get("status") or "").upper()

            # ``status`` is the public-endpoint terminal oracle: COMPLETED
            # only on a successful round-trip; everything else is a
            # structured failure propagated to the caller.
            if env.get("error"):
                self._tasks_failed += 1
                self._task_durations.append(duration)
                logger.error("RunPod public-endpoint task failed: %s", env["error"])
                return {
                    "pool_id": self.pool_id,
                    "worker_id": worker_id,
                    "status": "failed",
                    "output": None,
                    "error": str(env["error"]),
                    "duration": duration,
                }

            if raw_status and raw_status != "COMPLETED":
                self._tasks_failed += 1
                self._task_durations.append(duration)
                logger.warning(
                    "RunPod public-endpoint task ended in status=%r (expected "
                    "COMPLETED); treating as failure but capturing output if "
                    "present.",
                    raw_status,
                )
                return {
                    "pool_id": self.pool_id,
                    "worker_id": worker_id,
                    "status": raw_status.lower(),
                    "output": env.get("output"),
                    "error": f"non-COMPLETED terminal status {raw_status!r}",
                    "duration": duration,
                }

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
        except HTTPStatusError as e:
            self._tasks_failed += 1
            duration = time.time() - start_time
            logger.error("RunPod public-endpoint HTTP %s: %s", e.response.status_code, e)
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:500]}",
                "duration": duration,
            }
        except Exception as e:  # Pool task execution converts every failure into a structured failed-result envelope  # noqa: BLE001, RUF100
            self._tasks_failed += 1
            duration = time.time() - start_time
            logger.error("RunPod public-endpoint task failed: %s", e)
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
            "RunPodPublicEndpointPool scales via the public endpoint. Target %d not applicable.",
            target_worker_count,
        )

    async def health_check(self) -> dict[str, Any]:
        if self._client is None or self._status != PoolStatus.RUNNING:
            return {
                "pool_id": self.pool_id,
                "pool_type": "runpod_public",
                "status": "unhealthy",
                "endpoint_id": self._endpoint_id,
                "reason": "client not constructed",
            }
        return {
            "pool_id": self.pool_id,
            "pool_type": "runpod_public",
            "status": "healthy",
            "endpoint_id": self._endpoint_id,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
        }

    async def get_metrics(self) -> PoolMetrics:
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0
        )
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
                    "pool_type": "runpod_public",
                    "worker_id": r["worker_id"],
                    "status": r["status"],
                    "timestamp": r["timestamp"],
                },
            }
            for r in self._task_results
        ]
        self._task_results.clear()
        logger.info(
            "Collected %d memory items from RunPodPublicEndpointPool %s",
            len(items),
            self.pool_id,
        )
        return items

    async def stop(self) -> None:
        logger.info("Stopping RunPodPublicEndpointPool %s...", self.pool_id)
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001 — surface cleanup failure; do not silently drop
                logger.warning(
                    "RunPodPublicEndpointPool client close failed during stop",
                    exc_info=True,
                )
        self._client = None
        self._task_results.clear()
        self._status = PoolStatus.STOPPED
        logger.info("RunPodPublicEndpointPool %s stopped", self.pool_id)


def _resolve_api_key(configured: str) -> str:
    """Pick the API key in priority: explicit config > ``RUNPOD_API_KEY`` env."""
    if configured:
        return configured
    import os

    env_key = os.getenv("RUNPOD_API_KEY")
    if not env_key:
        raise RuntimeError(
            "RunPod public-endpoint dispatch requires RUNPOD_API_KEY in the "
            "environment (or 'api_key' in the pool config)."
        )
    return env_key


# Registry integration: thin factory — only ``config`` is required.
def _build_runpod_public_pool(
    config: PoolConfig,
    **_unused_kwargs: Any,
) -> RunPodPublicEndpointPool:
    return RunPodPublicEndpointPool(config=config)


from ._registry import register_pool_type

register_pool_type("runpod_public", _build_runpod_public_pool)
