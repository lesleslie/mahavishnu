from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus

if TYPE_CHECKING:
    from pathlib import Path

    from mahavishnu.workers.openhands import OpenHandsConfig


def make_config(tmp_path: Path) -> OpenHandsConfig:
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

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-123",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.get_status",
            new_callable=AsyncMock,
            return_value={"status": "finished", "result": "done"},
        ),
    ):
        result = await worker.execute({"prompt": "Write a test", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output is not None


@pytest.mark.unit
async def test_worker_execute_returns_failed_on_task_error(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-456",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.get_status",
            new_callable=AsyncMock,
            return_value={"status": "error", "error": "task failed"},
        ),
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

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-789",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.get_status",
            new_callable=AsyncMock,
            return_value={"status": "running"},
        ),
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

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-ws-fail",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
            new_callable=AsyncMock,
            side_effect=ConnectionError("WS refused"),
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.get_status",
            new_callable=AsyncMock,
            return_value={"status": "finished", "result": "done via polling"},
        ),
    ):
        result = await worker.execute({"prompt": "WS fallback task", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED


@pytest.mark.unit
async def test_the_rest_fallback_uses_the_api_terminal_vocabulary(
    tmp_path: Path,
) -> None:
    """The REST status field carries the API's vocabulary, not the socket's.

    The WebSocket path discriminates events by ``kind`` and ends on
    ``finished | error | stuck``. The REST fallback polls the same
    conversation, so it has to read the same vocabulary — otherwise a
    conversation that finished falls through to the timeout, and the
    caller sees a timeout for work that succeeded.
    """
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-rest-finished",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
            new_callable=AsyncMock,
            side_effect=ConnectionError("WS refused"),
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.get_status",
            new_callable=AsyncMock,
            return_value={"status": "finished", "result": "done"},
        ),
    ):
        result = await worker.execute({"prompt": "REST vocabulary", "timeout": 5})

    assert result.status == WorkerStatus.COMPLETED


@pytest.mark.unit
async def test_a_stuck_conversation_fails_through_the_rest_fallback(
    tmp_path: Path,
) -> None:
    """``stuck`` is terminal without being a completion."""
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-rest-stuck",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
            new_callable=AsyncMock,
            side_effect=ConnectionError("WS refused"),
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.get_status",
            new_callable=AsyncMock,
            return_value={"status": "stuck", "error": "no progress"},
        ),
    ):
        result = await worker.execute({"prompt": "REST stuck", "timeout": 5})

    assert result.status == WorkerStatus.FAILED


@pytest.mark.unit
def test_both_paths_read_one_terminal_vocabulary() -> None:
    """The socket's terminal kinds and the REST fallback's are the same set."""
    from mahavishnu.workers.openhands import (
        FAILED_EVENT_KINDS,
        TERMINAL_EVENT_KINDS,
    )

    assert {"finished", "error", "stuck"} == TERMINAL_EVENT_KINDS
    assert {"error", "stuck"} == FAILED_EVENT_KINDS


class _FakeWS:
    """A stand-in for the OpenHands events socket."""

    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = list(events)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str:
        if not self._events:
            raise StopAsyncIteration
        return json.dumps(self._events.pop(0))


@pytest.mark.unit
async def test_the_conversation_request_uses_initial_message() -> None:
    """The current API takes a StartConversationRequest."""
    from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig

    client = OpenHandsClient(OpenHandsConfig(base_url="http://localhost:3000"))
    response = MagicMock()
    response.json = MagicMock(return_value={"conversation_id": "conv-1"})
    response.raise_for_status = MagicMock()
    post = AsyncMock(return_value=response)

    with patch.object(client._http, "post", post):
        await client.create_conversation("Write a test")

    call = post.await_args
    assert call is not None
    assert call.kwargs["json"] == {"initial_message": "Write a test"}


@pytest.mark.unit
async def test_the_event_stream_uses_the_sockets_path() -> None:
    """The events live on /sockets/events/{conversation_id}."""
    from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig

    client = OpenHandsClient(OpenHandsConfig(base_url="https://openhands.example"))
    connect = MagicMock(return_value=_FakeWS([]))

    with patch("websockets.connect", connect):
        await client.stream_events("conv-1")

    assert connect.call_args.args[0] == "wss://openhands.example/sockets/events/conv-1"


@pytest.mark.unit
@pytest.mark.parametrize("terminal", ["finished", "error", "stuck"])
async def test_the_event_stream_stops_at_a_terminal_kind(terminal: str) -> None:
    """The stream ends on a terminal kind, and the kind is the discriminator."""
    from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig

    client = OpenHandsClient(OpenHandsConfig(base_url="http://localhost:3000"))
    fake = _FakeWS(
        [
            {"kind": "action", "message": "working"},
            {"kind": terminal, "message": "terminal"},
            {"kind": "action", "message": "never reached"},
        ]
    )

    with patch("websockets.connect", MagicMock(return_value=fake)):
        events = await client.stream_events("conv-1")

    assert [event["kind"] for event in events] == ["action", terminal]


@pytest.mark.unit
async def test_a_finished_event_is_read_by_its_kind(tmp_path: Path) -> None:
    """The worker reads the event's ``kind``, not a ``type`` field."""
    from mahavishnu.workers.openhands import OpenHandsWorker

    worker = OpenHandsWorker(config=make_config(tmp_path))

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-finished",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
            new_callable=AsyncMock,
            return_value=[{"kind": "finished", "message": "all done"}],
        ),
    ):
        result = await worker.execute({"prompt": "p", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output == "all done"


@pytest.mark.unit
async def test_an_error_event_is_a_failure(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    worker = OpenHandsWorker(config=make_config(tmp_path))

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-error",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
            new_callable=AsyncMock,
            return_value=[{"kind": "error", "message": "it broke"}],
        ),
    ):
        result = await worker.execute({"prompt": "p", "timeout": 60})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == ErrorCode.OPENHANDS_TASK_FAILED


@pytest.mark.unit
async def test_a_stuck_event_is_a_failure(tmp_path: Path) -> None:
    """``stuck`` is terminal and is not a completion."""
    from mahavishnu.workers.openhands import OpenHandsWorker

    worker = OpenHandsWorker(config=make_config(tmp_path))

    with (
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
            new_callable=AsyncMock,
            return_value="conv-stuck",
        ),
        patch(
            "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
            new_callable=AsyncMock,
            return_value=[{"kind": "stuck", "message": "no progress"}],
        ),
    ):
        result = await worker.execute({"prompt": "p", "timeout": 60})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == ErrorCode.OPENHANDS_TASK_FAILED
