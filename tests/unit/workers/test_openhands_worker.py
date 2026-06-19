from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus


def make_config(tmp_path: Path) -> "OpenHandsConfig":  # noqa: UP037
    from mahavishnu.workers.openhands import OpenHandsConfig

    return OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=tmp_path,
        timeout_seconds=60,
        poll_interval_seconds=0.1,
    )


@pytest.mark.unit
async def test_worker_execute_returns_completed_on_success(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-123",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "completed", "result": "done"},
    ):
        result = await worker.execute({"prompt": "Write a test", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output is not None


@pytest.mark.unit
async def test_worker_execute_returns_failed_on_task_error(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-456",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "error", "error": "task failed"},
    ):
        result = await worker.execute({"prompt": "Bad task", "timeout": 60})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == ErrorCode.OPENHANDS_TASK_FAILED


@pytest.mark.unit
async def test_worker_execute_returns_timeout_when_poll_expires(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    config.timeout_seconds = 0.1  # force immediate timeout
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-789",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "running"},
    ):
        result = await worker.execute({"prompt": "Slow task", "timeout": 0})

    assert result.status == WorkerStatus.TIMEOUT


@pytest.mark.unit
async def test_worker_execute_raises_on_service_unavailable(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        side_effect=ConnectionError("OpenHands unreachable"),
    ):
        result = await worker.execute({"prompt": "Any task", "timeout": 10})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == ErrorCode.OPENHANDS_SERVICE_ERROR


@pytest.mark.unit
async def test_worker_execute_websocket_fallback_to_polling(tmp_path: Path) -> None:
    """WebSocket status stream failing must fall back to REST polling."""
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-ws-fail",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
        new_callable=AsyncMock,
        side_effect=ConnectionError("WS refused"),
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "completed", "result": "done via polling"},
    ):
        result = await worker.execute({"prompt": "WS fallback task", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED
