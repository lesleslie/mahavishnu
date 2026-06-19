from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.unit
async def test_crow_worker_execute_returns_completed_result() -> None:
    from mahavishnu.workers.crow import CrowWorker
    from mahavishnu.core.status import WorkerStatus

    worker = CrowWorker(base_url="http://localhost:8765")

    mock_response = {
        "session_id": "sess-abc",
        "status": "completed",
        "result": "Task done.",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_post.return_value.json.return_value = {"session_id": "sess-abc"}
        mock_post.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = lambda: None

        result = await worker.execute({"prompt": "Write a hello world script"})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output is not None


@pytest.mark.unit
async def test_crow_worker_returns_worker_type() -> None:
    from mahavishnu.workers.crow import CrowWorker

    worker = CrowWorker(base_url="http://localhost:8765")
    assert worker.worker_type == "terminal-crow"
