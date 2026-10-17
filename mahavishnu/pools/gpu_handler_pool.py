"""GPU handler pool — concrete RunPodPool subclass for vision and ML inference.

Pre-routes VISION / ML_INFERENCE / EMBEDDING task categories to the GPU
pool; rejects other categories so the caller can fall back to a CPU
pool.

Usage (post runpod SDK 2.0 migration):
    config = PoolConfig(
        name="gpu-vision",
        pool_type="runpod",
        extra_config={
            "endpoint_id": os.environ["RUNPOD_ENDPOINT_ID"],
            "endpoint_name": "mahavishnu-vision",        # informational only
            "dependencies": ["torch", "Pillow"],          # informational only
        },
    )
    pool = GpuHandlerPool(config)
    await pool.start()
    result = await pool.execute_task(
        {"category": "vision", "image_url": "...", "prompt": "describe"}
    )

The handler function (vision / ml_inference / embedding dispatch) is
**no longer** defined in this module — under runpod SDK 2.0 the
endpoint is configured server-side (RunPod console or a dedicated
handler repo). The category check below routes the *request*: this
pool will only accept jobs whose category matches GPU_TASK_CATEGORIES
and reject everything else.
"""

from __future__ import annotations

import logging
from typing import Any

from .runpod_pool import RunPodPool

logger = logging.getLogger(__name__)

# Task categories that should be routed to GPU pools. Categories
# outside this set are rejected at the pool boundary so the dispatch
# layer can fall back to a CPU pool.
GPU_TASK_CATEGORIES: frozenset[str] = frozenset({"vision", "ml_inference", "embedding"})


class GpuHandlerPool(RunPodPool):
    """Concrete RunPodPool that pre-routes GPU-only task categories.

    Inherits all connection / dispatch logic from ``RunPodPool`` — this
    subclass exists only to enforce category routing at the pool
    boundary. Under the runpod SDK 2.0 migration the handler functions
    previously defined here have moved into the RunPod endpoint
    configuration (server-side).
    """

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
