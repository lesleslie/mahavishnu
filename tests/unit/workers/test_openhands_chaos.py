from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx2 as httpx
import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig, OpenHandsWorker

from tests.unit._httpx_test_helpers import patch_async_client

_TARGET = "mahavishnu.workers.openhands"


@pytest.mark.unit
async def test_network_drop_during_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OpenHandsClient,
        "stream_events",
        AsyncMock(side_effect=Exception("ws unavailable")),
    )
    config = OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=Path("/tmp/openhands-workspace"),
        poll_interval_seconds=0.01,
    )

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.NetworkError("connection reset")

    handler_factory = lambda: (  # noqa: E731
        make_response_handler  # not used; placeholder for clarity
    )
    # Build a stateful handler that returns success for /conversations and
    # raises for /conversations/{id} (the polling endpoint).
    from tests.unit._httpx_test_helpers import make_response_handler

    def stateful_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/api/conversations"):
            return httpx.Response(200, json={"conversation_id": "conv-1"})
        if url.endswith("/api/conversations/conv-1"):
            raise httpx.NetworkError("connection reset")
        raise AssertionError(f"Unexpected URL: {url}")

    with patch_async_client(stateful_handler, _TARGET):
        worker = OpenHandsWorker(config=config)
        result = await worker.execute({"prompt": "test", "timeout": 10})
        await worker.stop()

    assert result.status == WorkerStatus.FAILED
    assert result.error is not None


@pytest.mark.unit
async def test_server_500_during_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OpenHandsClient,
        "stream_events",
        AsyncMock(side_effect=Exception("ws unavailable")),
    )
    config = OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=Path("/tmp/openhands-workspace"),
        poll_interval_seconds=0.01,
    )

    def stateful_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/api/conversations"):
            return httpx.Response(200, json={"conversation_id": "conv-2"})
        if url.endswith("/api/conversations/conv-2"):
            return httpx.Response(500, text="internal server error")
        raise AssertionError(f"Unexpected URL: {url}")

    with patch_async_client(stateful_handler, _TARGET):
        worker = OpenHandsWorker(config=config)
        result = await worker.execute({"prompt": "test", "timeout": 10})
        await worker.stop()

    assert result.status == WorkerStatus.FAILED
    assert result.error is not None


@pytest.mark.unit
async def test_task_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OpenHandsClient,
        "stream_events",
        AsyncMock(side_effect=Exception("ws unavailable")),
    )
    config = OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=Path("/tmp/openhands-workspace"),
        poll_interval_seconds=0.01,
        timeout_seconds=1,
    )

    def stateful_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/api/conversations"):
            return httpx.Response(200, json={"conversation_id": "conv-3"})
        if url.endswith("/api/conversations/conv-3"):
            return httpx.Response(200, json={"status": "running"})
        raise AssertionError(f"Unexpected URL: {url}")

    with patch_async_client(stateful_handler, _TARGET):
        worker = OpenHandsWorker(config=config)
        result = await worker.execute({"prompt": "test", "timeout": 0.05})
        await worker.stop()

    assert result.status == WorkerStatus.TIMEOUT
