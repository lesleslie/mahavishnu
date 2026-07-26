# tests/unit/mcp/tools/test_worker_execute_no_truncation.py
import asyncio

from mahavishnu.workers.protocol import WorkerResult, WorkerStatus


class _StubWorker:
    worker_type = "terminal-claude"

    async def execute(self, task):
        return WorkerResult(
            worker_id="w-1",
            status=WorkerStatus.COMPLETED,
            output="x" * 5000,
            error=None,
            exit_code=0,
            duration_seconds=0.1,
            metadata={},
        )


class _StubManager:
    def __init__(self, worker):
        self._worker = worker

    async def execute_task(self, worker_id, task):
        return await self._worker.execute(task)


def test_worker_execute_returns_full_output(monkeypatch):
    from mahavishnu.mcp.tools import worker_tools

    manager = _StubManager(_StubWorker())
    monkeypatch.setattr(worker_tools, "worker_manager", manager)
    out = asyncio.run(worker_tools.worker_execute("w-1", "do it"))
    assert out["status"] == "completed"
    assert len(out["output"]) == 5000  # full output, not 500 chars
    assert "truncated" not in out
