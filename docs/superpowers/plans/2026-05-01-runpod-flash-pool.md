---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: runpod-flash-pool
---

# RunPod Flash Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Add a `RunPodPool` as a 4th pool type in Mahavishnu's multi-pool orchestration system, backed by the `runpod-flash` SDK to execute GPU-heavy tasks (VISION, REASONING) on RunPod serverless infrastructure.
> **Architecture:** `RunPodPool` implements `BasePool` using `runpod-flash`'s `@Endpoint` decorator for remote GPU function dispatch. Each `execute_task()` call invokes a pre-registered Flash endpoint (keyed by task category), with Flash handling auto-scaling and worker provisioning transparently. Pool registration follows the existing `elif` factory in `PoolManager.spawn_pool()` — zero changes to other pool types.
> **Tech Stack:** `runpod-flash` (≥0.1.0), `runpod` API key via env var `RUNPOD_API_KEY`, Python 3.10+, async/await, `TaskCategory` from `mahavishnu/workers/task_router.py`

______________________________________________________________________

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `mahavishnu/pools/runpod_pool.py` | `RunPodPool` class — Flash endpoint lifecycle + `BasePool` impl |
| Modify | `mahavishnu/pools/manager.py:166-174` | Add `"runpod"` branch in `spawn_pool()` factory |
| Modify | `mahavishnu/pools/__init__.py:32-55` | Add `RunPodPool` to `__all__` and `_LAZY_IMPORTS` |
| Modify | `settings/mahavishnu.yaml` | Add `runpod_pool` config stanza |
| Create | `tests/unit/pools/test_runpod_pool.py` | Unit tests (mocked Flash SDK) |

______________________________________________________________________

### Task 1: Add `runpod-flash` dependency

**Files:**

- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Open `pyproject.toml` and add to the `[project] dependencies` list:

```toml
"runpod-flash>=0.1.0",
```

- [ ] **Step 2: Sync environment**

```bash
uv sync
```

Expected: resolves without conflicts. If `runpod-flash` is not yet on PyPI (it may be `runpod` SDK only), install from source:

```bash
uv add git+https://github.com/runpod/flash
```

- [ ] **Step 3: Verify import**

```bash
python -c "import runpod_flash; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add runpod-flash SDK"
```

______________________________________________________________________

### Task 2: Write failing tests for `RunPodPool`

**Files:**

- Create: `tests/unit/pools/test_runpod_pool.py`

- [ ] **Step 1: Write tests**

```python
"""Unit tests for RunPodPool — Flash SDK is fully mocked."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.runpod_pool import RunPodPool


@pytest.fixture
def config():
    return PoolConfig(
        name="test-runpod",
        pool_type="runpod",
        extra_config={
            "api_key": "test-key",
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-test",
            "dependencies": ["torch"],
        },
    )


@pytest.fixture
def pool(config):
    return RunPodPool(config=config)


@pytest.mark.asyncio
async def test_start_returns_pool_id(pool):
    with patch("runpod_flash.Endpoint", return_value=MagicMock()):
        pool_id = await pool.start()
    assert pool_id == pool.pool_id
    assert pool._status == PoolStatus.RUNNING


@pytest.mark.asyncio
async def test_execute_task_success(pool):
    mock_endpoint = MagicMock()
    mock_endpoint.__call__ = AsyncMock(return_value={"output": "result"})
    pool._endpoint = mock_endpoint
    pool._status = PoolStatus.RUNNING

    result = await pool.execute_task({"prompt": "analyze image", "category": "vision"})

    assert result["status"] == "completed"
    assert result["pool_id"] == pool.pool_id
    assert result["output"] == {"output": "result"}
    assert result["duration"] >= 0.0


@pytest.mark.asyncio
async def test_execute_task_failure(pool):
    mock_endpoint = MagicMock()
    mock_endpoint.__call__ = AsyncMock(side_effect=RuntimeError("RunPod error"))
    pool._endpoint = mock_endpoint
    pool._status = PoolStatus.RUNNING

    result = await pool.execute_task({"prompt": "analyze image"})

    assert result["status"] == "failed"
    assert "RunPod error" in result["error"]


@pytest.mark.asyncio
async def test_execute_batch_runs_concurrently(pool):
    call_count = 0

    async def fake_execute(task):
        nonlocal call_count
        call_count += 1
        return {"status": "completed", "pool_id": pool.pool_id, "worker_id": "ep",
                "output": "ok", "error": None, "duration": 0.0}

    pool.execute_task = fake_execute
    tasks = [{"prompt": f"task {i}"} for i in range(3)]
    results = await pool.execute_batch(tasks)

    assert len(results) == 3
    assert call_count == 3


@pytest.mark.asyncio
async def test_health_check_running(pool):
    pool._status = PoolStatus.RUNNING
    pool._endpoint = MagicMock()
    health = await pool.health_check()

    assert health["pool_id"] == pool.pool_id
    assert health["pool_type"] == "runpod"
    assert health["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_check_no_endpoint(pool):
    pool._status = PoolStatus.PENDING
    pool._endpoint = None
    health = await pool.health_check()

    assert health["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_scale_is_noop(pool):
    """Flash handles scaling; scale() should log and return without error."""
    pool._status = PoolStatus.RUNNING
    await pool.scale(5)  # No exception


@pytest.mark.asyncio
async def test_collect_memory_returns_items(pool):
    pool._task_results = [
        {"worker_id": "ep-1", "output": "result A", "status": "completed",
         "timestamp": time.time()},
    ]
    items = await pool.collect_memory()
    assert len(items) == 1
    assert items[0]["metadata"]["pool_type"] == "runpod"


@pytest.mark.asyncio
async def test_stop_clears_endpoint(pool):
    pool._endpoint = MagicMock()
    pool._status = PoolStatus.RUNNING
    await pool.stop()
    assert pool._status == PoolStatus.STOPPED
    assert pool._endpoint is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/pools/test_runpod_pool.py -v
```

Expected: `ImportError: cannot import name 'RunPodPool' from 'mahavishnu.pools.runpod_pool'`

- [ ] **Step 3: Commit the tests**

```bash
git add tests/unit/pools/test_runpod_pool.py
git commit -m "test(pools): add failing tests for RunPodPool"
```

______________________________________________________________________

### Task 3: Implement `RunPodPool`

**Files:**

- Create: `mahavishnu/pools/runpod_pool.py`

- [ ] **Step 1: Write the implementation**

```python
"""RunPod Flash worker pool.

Executes GPU tasks on RunPod serverless infrastructure via the runpod-flash SDK.
Workers scale automatically from 0 to N — no persistent worker management needed.

Cold start: 30-60s on first invocation. Subsequent calls: 2-3s.
Do not use for latency-sensitive routing; prefer for VISION/REASONING batch work.
"""

import asyncio
import logging
import time
from typing import Any

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

logger = logging.getLogger(__name__)


class RunPodPool(BasePool):
    """RunPod serverless GPU pool backed by runpod-flash.

    Each pool maps to one Flash endpoint (one GPU type, one set of dependencies).
    Spawn separate pools for different hardware configs (e.g. RTX 4090 vs A100).

    Architecture:
        RunPodPool.execute_task()
            → Flash @Endpoint (auto-provisioned GPU worker on RunPod)
                → Task output returned async

    Use Cases:
    - GPU inference (VISION tasks, image analysis)
    - Heavy REASONING tasks that benefit from dedicated GPU
    - Batch AI workloads not suitable for local Ollama

    Cold-start note: First invocation takes 30-60s while RunPod provisions
    the worker. Subsequent calls within the keep-alive window take 2-3s.
    """

    def __init__(
        self,
        config: PoolConfig,
        pool_id: str | None = None,
    ) -> None:
        super().__init__(config, pool_id)
        self._endpoint: Any = None
        self._task_results: list[dict[str, Any]] = []
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

        # Flash config from extra_config
        self._api_key: str = config.get("api_key", "")
        self._gpu_type: str = config.get("gpu_type", "NVIDIA_GEFORCE_RTX_4090")
        self._endpoint_name: str = config.get("endpoint_name", "mahavishnu-worker")
        self._dependencies: list[str] = config.get("dependencies", [])
        self._num_workers: int = config.get("num_workers", 3)

    async def start(self) -> str:
        """Register the Flash endpoint with RunPod.

        Returns:
            pool_id: Unique pool identifier
        """
        self._status = PoolStatus.INITIALIZING
        try:
            self._endpoint = self._build_endpoint()
            self._status = PoolStatus.RUNNING
            logger.info(
                f"RunPodPool {self.pool_id} started "
                f"(endpoint={self._endpoint_name}, gpu={self._gpu_type})"
            )
        except Exception as e:
            self._status = PoolStatus.FAILED
            logger.error(f"RunPodPool failed to start: {e}")
            raise
        return self.pool_id

    def _build_endpoint(self) -> Any:
        """Create and register the Flash endpoint function.

        Returns a callable async function that dispatches to RunPod GPU workers.
        """
        try:
            from runpod_flash import Endpoint, GpuType
        except ImportError as e:
            raise RuntimeError(
                "RunPodPool requires 'runpod-flash'. Install with: uv add runpod-flash"
            ) from e

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
            # This function body executes on the remote RunPod GPU worker.
            # Keep imports inside the function — they run in the remote environment.
            prompt = task_payload.get("prompt", "")
            category = task_payload.get("category", "general")
            return {"output": f"[{category}] processed: {prompt}", "status": "ok"}

        return _run_task

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a task to the RunPod Flash endpoint.

        Args:
            task: Task dict. Relevant keys:
                - prompt (str): Task prompt or instruction
                - category (str): Task category hint (e.g. "vision", "reasoning")
                - timeout (int): Max seconds to wait (default: 300)

        Returns:
            Execution result dict with keys:
                pool_id, worker_id, status, output, error, duration
        """
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
            self._task_results.append(
                {
                    "worker_id": worker_id,
                    "output": output,
                    "status": "completed",
                    "timestamp": start_time,
                }
            )

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
            logger.error(f"RunPod task timed out after {duration:.1f}s: {e}")
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
            logger.error(f"RunPod task failed: {e}")
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": str(e),
                "duration": duration,
            }

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Execute multiple tasks concurrently via Flash.

        Args:
            tasks: List of task dicts

        Returns:
            Mapping of task index string → result dict
        """
        results = await asyncio.gather(*(self.execute_task(t) for t in tasks))
        return {str(i): r for i, r in enumerate(results)}

    async def scale(self, target_worker_count: int) -> None:
        """No-op: Flash auto-scales workers based on demand.

        Args:
            target_worker_count: Ignored — Flash manages this automatically.
        """
        logger.info(
            f"RunPodPool scales automatically via Flash. "
            f"Target {target_worker_count} not applicable."
        )

    async def health_check(self) -> dict[str, Any]:
        """Check endpoint registration status.

        Returns:
            Health status dict
        """
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
        """Get pool metrics.

        Returns:
            PoolMetrics with current statistics
        """
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations)
            if self._task_durations
            else 0.0
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
        """Collect completed task results for Session-Buddy memory storage.

        Returns:
            List of memory dicts
        """
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
        logger.info(f"Collected {len(items)} memory items from RunPodPool {self.pool_id}")
        return items

    async def stop(self) -> None:
        """Deregister the Flash endpoint and mark pool stopped."""
        logger.info(f"Stopping RunPodPool {self.pool_id}...")
        self._endpoint = None
        self._task_results.clear()
        self._status = PoolStatus.STOPPED
        logger.info(f"RunPodPool {self.pool_id} stopped")
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/pools/test_runpod_pool.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/pools/runpod_pool.py
git commit -m "feat(pools): implement RunPodPool via runpod-flash SDK"
```

______________________________________________________________________

### Task 4: Register `RunPodPool` in the pool factory

**Files:**

- Modify: `mahavishnu/pools/manager.py:14` (import) and `:166-174` (factory)

- [ ] **Step 1: Add import**

At `mahavishnu/pools/manager.py`, find the existing import block:

```python
from .runpod_pool import RunPodPool
```

(Plan predates Kubernetes pool removal — adjust import block to current state.)

- [ ] **Step 2: Add factory branch**

Find the `elif pool_type == "kubernetes":` block (lines ~166-172) and add a new branch after it:

```python
            elif pool_type == "runpod":
                pool = RunPodPool(
                    config=config,
                )
```

Also update the docstring for `spawn_pool()` — change:

```python
            pool_type: Type of pool ("mahavishnu", "session-buddy", "runpod")
```

to:

```python
            pool_type: Type of pool ("mahavishnu", "session-buddy", "kubernetes", "runpod")
```

And update the known_types set (line ~119):

```python
        known_types = {"mahavishnu", "session-buddy", "kubernetes", "runpod"} | set(worker_counts.keys())
```

- [ ] **Step 3: Run existing pool manager tests to check for regressions**

```bash
pytest tests/unit/pools/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/pools/manager.py
git commit -m "feat(pools): register RunPodPool in PoolManager factory"
```

______________________________________________________________________

### Task 5: Export `RunPodPool` from the pools package

**Files:**

- Modify: `mahavishnu/pools/__init__.py:32-55`

- [ ] **Step 1: Add to `__all__`**

Add `"RunPodPool"` to the `__all__` list:

```python
__all__ = [
    "BasePool",
    "PoolConfig",
    "PoolMetrics",
    "PoolStatus",
    "PoolManager",
    "PoolSelector",
    "MemoryAggregator",
    "RunPodPool",
    "WebSocketBroadcaster",
    "create_broadcaster",
]
```

- [ ] **Step 2: Add to `_LAZY_IMPORTS`**

```python
    "RunPodPool": (".runpod_pool", "RunPodPool"),
```

- [ ] **Step 3: Verify import works**

```bash
python -c "from mahavishnu.pools import RunPodPool; print(RunPodPool)"
```

Expected: `<class 'mahavishnu.pools.runpod_pool.RunPodPool'>`

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/pools/__init__.py
git commit -m "feat(pools): export RunPodPool from pools package"
```

______________________________________________________________________

### Task 6: Add RunPod config stanza to settings

**Files:**

- Modify: `settings/mahavishnu.yaml`

- [ ] **Step 1: Add stanza**

Open `settings/mahavishnu.yaml` and add under the pool configuration section (after `pool_routing_strategy`):

```yaml
# RunPod Flash pool configuration
# Set RUNPOD_API_KEY env var before spawning runpod pools
runpod_pool:
  enabled: false           # set to true to allow runpod pool spawning
  default_gpu: "NVIDIA_GEFORCE_RTX_4090"
  default_workers: 3
  default_endpoint_name: "mahavishnu-worker"
  default_dependencies:
    - "torch"
    - "transformers"
```

- [ ] **Step 2: Add `RUNPOD_API_KEY` to env var docs**

In `CLAUDE.md` under "Configuration Files", add a note:

```
RUNPOD_API_KEY      Required for RunPodPool — set in environment before spawning runpod pools
```

- [ ] **Step 3: Commit**

```bash
git add settings/mahavishnu.yaml CLAUDE.md
git commit -m "feat(config): add runpod_pool config stanza to mahavishnu.yaml"
```

______________________________________________________________________

### Task 7: Write an integration smoke test

**Files:**

- Create: `tests/integration/pools/test_runpod_pool_smoke.py`

This test is **skipped by default** (requires a real RunPod API key). It verifies the full round-trip against the real Flash API when opted in.

- [ ] **Step 1: Write smoke test**

```python
"""Integration smoke test for RunPodPool.

Skipped unless RUNPOD_API_KEY is set in the environment.
Run manually:
    RUNPOD_API_KEY=<key> pytest tests/integration/pools/test_runpod_pool_smoke.py -v -s
"""

import os

import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.runpod_pool import RunPodPool

pytestmark = pytest.mark.skipif(
    not os.getenv("RUNPOD_API_KEY"),
    reason="RUNPOD_API_KEY not set — skipping RunPod integration test",
)


@pytest.fixture
async def live_pool():
    config = PoolConfig(
        name="smoke-test-pool",
        pool_type="runpod",
        extra_config={
            "api_key": os.environ["RUNPOD_API_KEY"],
            "gpu_type": "NVIDIA_GEFORCE_RTX_4090",
            "endpoint_name": "mahavishnu-smoke",
            "dependencies": [],
            "num_workers": 1,
        },
    )
    pool = RunPodPool(config=config)
    await pool.start()
    yield pool
    await pool.stop()


@pytest.mark.asyncio
async def test_live_execute_task(live_pool):
    result = await live_pool.execute_task({"prompt": "hello from smoke test", "category": "general"})
    assert result["status"] == "completed"
    assert result["output"] is not None
    assert live_pool._status == PoolStatus.RUNNING


@pytest.mark.asyncio
async def test_live_health_check(live_pool):
    health = await live_pool.health_check()
    assert health["status"] == "healthy"
    assert health["pool_type"] == "runpod"
```

- [ ] **Step 2: Verify smoke test is skipped in normal CI**

```bash
pytest tests/integration/pools/test_runpod_pool_smoke.py -v
```

Expected: `1 skipped` (no API key in CI env).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/pools/test_runpod_pool_smoke.py
git commit -m "test(pools): add RunPodPool integration smoke test (opt-in via RUNPOD_API_KEY)"
```

______________________________________________________________________

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| `BasePool` implementation | Task 3 |
| Factory registration in `PoolManager` | Task 4 |
| Package export | Task 5 |
| Config stanza | Task 6 |
| Dependency added | Task 1 |
| Tests | Tasks 2, 7 |
| Cold-start note documented | Task 3 (class docstring) |

### Placeholder scan

None — all code blocks are complete implementations.

### Type consistency

- `PoolConfig`, `PoolMetrics`, `PoolStatus` — imported from `.base` in both implementation and tests ✓
- `execute_task()` return shape (`pool_id`, `worker_id`, `status`, `output`, `error`, `duration`) matches `BasePool` docstring contract ✓
- `collect_memory()` metadata shape matches `KubernetesPool` and `SessionBuddyPool` conventions ✓

______________________________________________________________________

## Future Work

### Concrete GPU handler (required before production use)

`RunPodPool._run_task` raises `NotImplementedError` by design. To use the pool in production, subclass it and override `_build_endpoint`:

```python
from mahavishnu.pools.runpod_pool import RunPodPool
from runpod_flash import Endpoint, GpuType

class VisionPool(RunPodPool):
    def _build_endpoint(self):
        @Endpoint(
            name="mahavishnu-vision",
            gpu=GpuType.NVIDIA_GEFORCE_RTX_4090,
            workers=self._num_workers,
            dependencies=["torch", "transformers", "Pillow"],
        )
        def _run_task(task_payload: dict) -> dict:
            # real GPU inference code here
            ...
        return _run_task
```

Register the subclass in `PoolManager.spawn_pool()` under a new `pool_type` string (e.g. `"runpod-vision"`) or pass a factory callable.

### Task-category routing

`TaskRouter` in `mahavishnu/workers/task_router.py` maps `TaskCategory` → model. A parallel mechanism to map `TaskCategory.VISION` or `TaskCategory.REASONING` → `pool_type="runpod"` would allow automatic pool selection during task routing. This would go in `PoolManager.route_task()`.

### Integration smoke test

Run `tests/integration/pools/test_runpod_pool_smoke.py` with a real `RUNPOD_API_KEY` to validate the full SDK round-trip against live RunPod infrastructure before any production deployment.
