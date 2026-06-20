from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig, OpenHandsWorker


@pytest.mark.unit
async def test_network_drop_during_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        OpenHandsClient,
        "stream_events",
        AsyncMock(side_effect=Exception("ws unavailable")),
    )
    config = OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=Path("/tmp/openhands-workspace"),  # noqa: S108
        poll_interval_seconds=0.01,
    )
    with respx.mock:
        respx.post("http://localhost:3000/api/conversations").mock(
            return_value=httpx.Response(200, json={"conversation_id": "conv-1"})
        )
        respx.get("http://localhost:3000/api/conversations/conv-1").mock(
            side_effect=httpx.NetworkError("connection reset")
        )
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
        workspace_dir=Path("/tmp/openhands-workspace"),  # noqa: S108
        poll_interval_seconds=0.01,
    )
    with respx.mock:
        respx.post("http://localhost:3000/api/conversations").mock(
            return_value=httpx.Response(200, json={"conversation_id": "conv-2"})
        )
        respx.get("http://localhost:3000/api/conversations/conv-2").mock(
            return_value=httpx.Response(500, text="internal server error")
        )
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
        workspace_dir=Path("/tmp/openhands-workspace"),  # noqa: S108
        poll_interval_seconds=0.01,
        timeout_seconds=1,
    )
    with respx.mock:
        respx.post("http://localhost:3000/api/conversations").mock(
            return_value=httpx.Response(200, json={"conversation_id": "conv-3"})
        )
        respx.get("http://localhost:3000/api/conversations/conv-3").mock(
            return_value=httpx.Response(200, json={"status": "running"})
        )
        worker = OpenHandsWorker(config=config)
        result = await worker.execute({"prompt": "test", "timeout": 0.05})
        await worker.stop()

    assert result.status == WorkerStatus.TIMEOUT
