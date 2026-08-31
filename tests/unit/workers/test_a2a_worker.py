from __future__ import annotations

import httpx2 as httpx
import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.a2a import A2AAgentConfig, A2AWorker

from tests.unit._httpx_test_helpers import patch_async_client

_TARGET = "mahavishnu.workers.a2a"


def _make_worker(*names_urls: tuple[str, str]) -> A2AWorker:
    registry = {name: A2AAgentConfig(name=name, url=url) for name, url in names_urls}
    return A2AWorker(agent_configs=registry)


# ── Scenario 1: Happy path SSE ───────────────────────────────────────────────


@pytest.mark.unit
async def test_happy_path_sse() -> None:
    """Agent supports streaming; sendSubscribe returns working→completed."""
    card_json = {
        "name": "coder",
        "description": "codes things",
        "url": "http://coder.example.com",
        "version": "1.0.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
    }
    sse_body = (
        'data: {"id": "t1", "status": {"state": "working"}, "final": false}\n\n'
        'data: {"id": "t1", "status": {"state": "completed"}, '
        '"artifacts": [{"parts": [{"type": "text", "text": "hello world"}]}], '
        '"final": true}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/agent.json"):
            return httpx.Response(200, json=card_json)
        if url.endswith("/tasks/sendSubscribe"):
            return httpx.Response(
                200, text=sse_body, headers={"content-type": "text/event-stream"}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch_async_client(handler, _TARGET):
        worker = _make_worker(("coder", "http://coder.example.com"))
        result = await worker.execute({"agent": "coder", "prompt": "say hello"})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output == "hello world"


# ── Scenario 2: Non-streaming fallback ───────────────────────────────────────


@pytest.mark.unit
async def test_non_streaming_fallback() -> None:
    """Agent does NOT support streaming; falls back to /tasks/send."""
    card_json = {
        "name": "simple",
        "description": "simple agent",
        "url": "http://simple.example.com",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
    }
    task_response = {
        "id": "t2",
        "status": {"state": "completed"},
        "artifacts": [{"parts": [{"type": "text", "text": "result text"}]}],
        "final": True,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/agent.json"):
            return httpx.Response(200, json=card_json)
        if url.endswith("/tasks/send"):
            return httpx.Response(200, json=task_response)
        raise AssertionError(f"Unexpected URL: {url}")

    with patch_async_client(handler, _TARGET):
        worker = _make_worker(("simple", "http://simple.example.com"))
        result = await worker.execute({"agent": "simple", "prompt": "run task"})

    assert result.status == WorkerStatus.COMPLETED


# ── Scenario 3: Unknown agent name ───────────────────────────────────────────


@pytest.mark.unit
async def test_unknown_agent_name() -> None:
    """Agent name not in registry returns FAILED with MHV-310."""
    worker = _make_worker(("known-agent", "http://known.example.com"))
    result = await worker.execute({"agent": "ghost-agent", "prompt": "do something"})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == "MHV-310"


# ── Scenario 4: Remote agent SSE error event ─────────────────────────────────


@pytest.mark.unit
async def test_remote_agent_sse_error_event() -> None:
    """Remote agent emits failed final event; worker returns FAILED with MHV-311."""
    card_json = {
        "name": "erring",
        "description": "always fails",
        "url": "http://erring.example.com",
        "version": "1.0.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
    }
    sse_body = (
        'data: {"id": "t3", "status": {"state": "failed", "message": '
        '"quota exceeded"}, "final": true}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/agent.json"):
            return httpx.Response(200, json=card_json)
        if url.endswith("/tasks/sendSubscribe"):
            return httpx.Response(
                200, text=sse_body, headers={"content-type": "text/event-stream"}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch_async_client(handler, _TARGET):
        worker = _make_worker(("erring", "http://erring.example.com"))
        result = await worker.execute({"agent": "erring", "prompt": "run task"})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == "MHV-311"


# ── Scenario 5: Card fetch 503 ────────────────────────────────────────────────


@pytest.mark.unit
async def test_card_fetch_503() -> None:
    """Agent card endpoint returns 503; worker returns FAILED."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    with patch_async_client(handler, _TARGET):
        worker = _make_worker(("down", "http://down.example.com"))
        result = await worker.execute({"agent": "down", "prompt": "ping"})

    assert result.status == WorkerStatus.FAILED
