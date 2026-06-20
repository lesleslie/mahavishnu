from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from mahavishnu.a2a.server import build_a2a_router
from mahavishnu.core.config import A2ASettings
from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult


def _make_app(worker_result: WorkerResult) -> TestClient:
    """Build a TestClient with a mock execute_fn."""
    settings = A2ASettings()
    settings.card.capabilities.streaming = True

    execute_fn = AsyncMock(return_value=worker_result)

    app = build_a2a_router(settings, execute_fn)
    return TestClient(app, raise_server_exceptions=True)


# ── Scenario 1: GET /.well-known/agent.json ───────────────────────────────────


@pytest.mark.unit
def test_agent_card_returns_valid_json() -> None:
    client = _make_app(WorkerResult(worker_id="x", status=WorkerStatus.COMPLETED, output=""))
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Mahavishnu"
    assert data["capabilities"]["streaming"] is True


# ── Scenario 2: POST /tasks/send success ──────────────────────────────────────


@pytest.mark.unit
def test_tasks_send_success() -> None:
    result = WorkerResult(
        worker_id="t1",
        status=WorkerStatus.COMPLETED,
        output="task done",
    )
    client = _make_app(result)

    resp = client.post(
        "/tasks/send",
        json={
            "id": "t1",
            "message": {"role": "user", "parts": [{"type": "text", "text": "do work"}]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["state"] == "completed"
    assert data["id"] == "t1"


# ── Scenario 3: POST /tasks/sendSubscribe returns SSE ────────────────────────


@pytest.mark.unit
def test_tasks_send_subscribe_streams_sse() -> None:
    result = WorkerResult(
        worker_id="t2",
        status=WorkerStatus.COMPLETED,
        output="streamed result",
    )
    client = _make_app(result)

    with client.stream(
        "POST",
        "/tasks/sendSubscribe",
        json={
            "id": "t2",
            "message": {"role": "user", "parts": [{"type": "text", "text": "stream me"}]},
        },
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = "".join(resp.iter_text())
    # Must contain at least one SSE data line
    assert "data:" in body
    # Must contain the final completed event
    assert '"completed"' in body


# ── Scenario 4: POST /tasks/send — worker failure ────────────────────────────


@pytest.mark.unit
def test_tasks_send_worker_failure() -> None:
    result = WorkerResult(
        worker_id="t3",
        status=WorkerStatus.FAILED,
        error="ran out of memory",
    )
    client = _make_app(result)

    resp = client.post(
        "/tasks/send",
        json={
            "id": "t3",
            "message": {"role": "user", "parts": [{"type": "text", "text": "risky task"}]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["state"] == "failed"
