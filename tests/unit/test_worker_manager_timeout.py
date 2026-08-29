"""Regression tests for ``WorkerManager.execute_task`` timeout behavior.

Without a timeout, a hung worker holds its semaphore slot indefinitely and
starves every subsequent ``pool_execute``. Fix: wrap ``worker.execute(task)``
in ``asyncio.wait_for`` using the per-task ``timeout`` key (or
``config.default_timeout`` as the fallback).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.base import WorkerResult
from mahavishnu.core.status import WorkerStatus


class _HangingWorker:
    """Worker whose execute() awaits forever."""

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        await asyncio.Future()  # never resolves
        return WorkerResult(  # pragma: no cover - unreachable
            worker_id="hanging",
            status=WorkerStatus.COMPLETED,
            output="never",
            error=None,
            exit_code=0,
            duration_seconds=0.0,
        )


class _FastWorker:
    """Worker that completes immediately."""

    def __init__(self, worker_id: str = "fast") -> None:
        self.worker_id = worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        await asyncio.sleep(0.01)
        return WorkerResult(
            worker_id=self.worker_id,
            status=WorkerStatus.COMPLETED,
            output="ok",
            error=None,
            exit_code=0,
            duration_seconds=0.01,
        )


def _make_manager(worker_id: str, worker: Any) -> WorkerManager:
    """Construct a WorkerManager with a single injected worker."""
    mgr = WorkerManager.__new__(WorkerManager)
    mgr.max_concurrent = 1
    mgr._semaphore = asyncio.Semaphore(1)
    mgr._workers = {worker_id: worker}
    return mgr


@pytest.mark.asyncio
async def test_execute_task_returns_failed_when_worker_hangs_past_timeout() -> None:
    """Hung worker yields FAILED with timeout metadata; semaphore is released."""
    worker = _HangingWorker()
    mgr = _make_manager("hanging", worker)
    # The hanging worker is registered under worker_id "hanging".
    # Patch WorkerManager's _workers dict lookup by registering via attribute.
    mgr._workers = {"hanging": worker}

    result = await mgr.execute_task(
        "hanging",
        {"prompt": "test", "timeout": 0.05},
    )

    assert result.status == WorkerStatus.TIMEOUT
    assert result.worker_id == "hanging"
    assert result.error is not None
    assert "timeout" in result.error.lower() or "timed out" in result.error.lower()
    assert result.metadata.get("timeout") is True


@pytest.mark.asyncio
async def test_execute_task_releases_semaphore_after_timeout() -> None:
    """After a timeout, the next call on a fresh worker must not block forever."""
    hanging = _HangingWorker()
    mgr = _make_manager("hanging", hanging)
    mgr._workers = {"hanging": hanging}

    # First call times out
    first = await mgr.execute_task("hanging", {"timeout": 0.05})
    assert first.status == WorkerStatus.TIMEOUT

    # Re-register a fast worker; it must run promptly (semaphore was released).
    fast = _FastWorker(worker_id="fast")
    mgr._workers["fast"] = fast

    second = await asyncio.wait_for(
        mgr.execute_task("fast", {"prompt": "x"}),
        timeout=1.0,
    )
    assert second.status == WorkerStatus.COMPLETED


@pytest.mark.asyncio
async def test_execute_task_uses_config_default_timeout_when_not_specified() -> None:
    """Default timeout from the worker config caps execution."""
    worker = _HangingWorker()
    mgr = _make_manager("hanging", worker)
    mgr._workers = {"hanging": worker}
    # Inject a fake config whose default_timeout is 0.05s.
    fake_cfg = MagicMock()
    fake_cfg.default_timeout = 0.05
    worker.config = fake_cfg

    result = await mgr.execute_task("hanging", {})
    assert result.status == WorkerStatus.TIMEOUT
