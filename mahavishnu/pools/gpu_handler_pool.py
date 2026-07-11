"""GPU handler pool — concrete RunPodPool subclass for vision and ML inference.

Override _build_endpoint() to register a real GPU handler function.
Automatically routes VISION and ML_INFERENCE task categories to RunPod.

Usage:
    config = PoolConfig(
        name="gpu-vision",
        pool_type="runpod",
        extra_config={
            "api_key": os.environ["RUNPOD_API_KEY"],
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-vision",
            "dependencies": ["torch", "Pillow", "transformers"],
        },
    )
    pool = GpuHandlerPool(config)
    await pool.start()
    result = await pool.execute_task({"category": "vision", "image_url": "..."})
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .runpod_pool import RunPodPool

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Optional dependency — imported only for static analysis. The runtime
    # `else` branch below handles the install / no-install cases.
    from runpod_flash import Endpoint, GpuType
else:
    try:
        from runpod_flash import Endpoint, GpuType
    except ImportError:
        Endpoint = None  # type: ignore[misc]
        GpuType = None  # type: ignore[misc]

# Task categories that should be routed to GPU pools
GPU_TASK_CATEGORIES: frozenset[str] = frozenset({"vision", "ml_inference", "embedding"})


class GpuHandlerPool(RunPodPool):
    """Concrete RunPodPool with a real GPU handler for vision and ML inference tasks.

    Adds category-aware pre-routing: tasks whose ``category`` key matches
    ``GPU_TASK_CATEGORIES`` are accepted; others are rejected with a clear error
    so the caller can fall back to a CPU pool.
    """

    def _build_endpoint(self) -> Any:
        if Endpoint is None:
            raise RuntimeError(
                "GpuHandlerPool requires 'runpod-flash'. Install with: uv add runpod-flash"
            )

        gpu = getattr(GpuType, self._gpu_type, None)
        if gpu is None:
            raise ValueError(
                f"Unknown GpuType: {self._gpu_type}. Valid values: {[g.name for g in GpuType]}"
            )

        deps = self._dependencies

        @Endpoint(
            name=self._endpoint_name,
            gpu=gpu,
            workers=self._num_workers,
            dependencies=deps,
        )
        def _gpu_handler(task_payload: dict) -> dict:
            """Real GPU handler — executed remotely on RunPod workers.

            Dispatches by ``task_payload["category"]``:
            - ``vision``       → run vision model inference
            - ``ml_inference`` → run generic ML inference
            - ``embedding``    → generate vector embeddings

            Add provider-specific logic (transformers, torch, etc.) here.
            The function runs in the RunPod worker context, not locally.
            """
            category = task_payload.get("category", "")
            prompt = task_payload.get("prompt", "")
            image_url = task_payload.get("image_url")

            if category == "vision":
                # Example: describe an image using a local vision model
                # In production, load model once outside the handler (module-level)
                return {
                    "category": "vision",
                    "result": f"[vision handler] processed image_url={image_url!r} prompt={prompt!r}",
                    "model": "placeholder-vision-model",
                }

            if category == "ml_inference":
                return {
                    "category": "ml_inference",
                    "result": f"[ml_inference handler] processed prompt={prompt!r}",
                    "model": "placeholder-inference-model",
                }

            if category == "embedding":
                return {
                    "category": "embedding",
                    "result": [],
                    "model": "placeholder-embedding-model",
                }

            return {
                "category": category or "unknown",
                "result": None,
                "error": f"GpuHandlerPool does not handle category={category!r}",
            }

        return _gpu_handler

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        category = task.get("category", "")
        if category and category not in GPU_TASK_CATEGORIES:
            return {
                "pool_id": self.pool_id,
                "worker_id": "none",
                "status": "rejected",
                "output": None,
                "error": (
                    f"GpuHandlerPool only handles {sorted(GPU_TASK_CATEGORIES)}, "
                    f"got category={category!r}. Route to a CPU pool instead."
                ),
                "duration": 0.0,
            }
        return await super().execute_task(task)
