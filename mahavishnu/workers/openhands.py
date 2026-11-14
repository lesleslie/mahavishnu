from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx2 as httpx
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = get_logger(__name__)

#: The terminal event kinds the current OpenHands API emits. The event's
#: discriminator is ``kind``; a stream ends on one of these, and ``stuck``
#: is terminal without being a completion.
# req: REQ-C14
TERMINAL_EVENT_KINDS: Final[frozenset[str]] = frozenset({"finished", "error", "stuck"})

#: The terminal kinds that mean the task did NOT succeed.
FAILED_EVENT_KINDS: Final[frozenset[str]] = frozenset({"error", "stuck"})


@dataclass
class OpenHandsConfig:
    base_url: str = "http://localhost:3000"
    workspace_dir: Path = Path("/tmp/openhands-workspace")
    timeout_seconds: float = 600
    poll_interval_seconds: float = 3.0
    max_output_chars: int = 50_000


class OpenHandsClient:
    """Thin async client for the OpenHands REST API."""

    def __init__(self, config: OpenHandsConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(30.0),
        )

    async def create_conversation(self, task: str) -> str:
        """Start an OpenHands conversation and return its conv_id.

        The current API takes a ``StartConversationRequest``: the task
        text is the request's ``initial_message``.
        """
        resp = await self._http.post(
            "/api/conversations",
            json={"initial_message": task},
        )
        resp.raise_for_status()
        return resp.json()["conversation_id"]

    async def get_status(self, conv_id: str) -> dict[str, Any]:
        """Poll REST endpoint for conversation status."""
        resp = await self._http.get(f"/api/conversations/{conv_id}")
        resp.raise_for_status()
        return resp.json()

    async def stream_events(self, conv_id: str) -> list[dict[str, Any]]:
        """Consume the conversation's event socket (best-effort, may raise).

        The events live on ``/sockets/events/{conversation_id}`` and the
        discriminator is the event's ``kind``.
        """
        import json

        import websockets

        url = (
            self._config.base_url.replace("http://", "ws://").replace(
                "https://", "wss://"
            )
            + f"/sockets/events/{conv_id}"
        )
        events: list[dict[str, Any]] = []
        async with websockets.connect(url) as ws:
            async for raw in ws:
                event = json.loads(raw)
                events.append(event)
                if event.get("kind") in TERMINAL_EVENT_KINDS:
                    break
        return events

    async def cancel_conversation(self, conv_id: str) -> None:
        await self._http.delete(f"/api/conversations/{conv_id}")

    async def health_check(self) -> bool:
        try:
            resp = await self._http.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:  # health probe soft-fails to False on any HTTP/connect error  # background task — broad catch is the documented contract  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            return False

    async def close(self) -> None:
        await self._http.aclose()


class OpenHandsWorker(BaseWorker):
    """Gateway worker delegating autonomous dev tasks to an OpenHands server.

    Does NOT embed a quality loop — quality checks belong in the MCP tool layer
    (openhands_tools.openhands_run).
    """

    def __init__(
        self,
        config: OpenHandsConfig | None = None,
        crackerjack_client: Any | None = None,
    ) -> None:
        super().__init__(worker_type="openhands")
        self._config = config or OpenHandsConfig()
        self._crackerjack_client = crackerjack_client
        self._client = OpenHandsClient(self._config)

    async def start(self, *, prompt: str | None = None) -> str:
        """Mark the worker as running and return a fixed worker ID."""
        self._status = WorkerStatus.RUNNING
        return "openhands"

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Submit a task to OpenHands and poll/stream until completion."""
        prompt = task.get("prompt", "")
        timeout = task.get("timeout", self._config.timeout_seconds)

        try:
            conv_id = await self._client.create_conversation(prompt)
        except Exception as e:  # create_conversation may raise any HTTP/connect error; map to WorkerResult FAILED  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            return WorkerResult(
                worker_id="openhands",
                status=WorkerStatus.FAILED,
                error=str(e),
                error_code=ErrorCode.OPENHANDS_SERVICE_ERROR,
                metadata={"worker_type": self.worker_type},
            )

        # Prefer WebSocket stream; fall back to REST polling on connection failure.
        try:
            events = await self._client.stream_events(conv_id)
            finished = next(
                (e for e in events if e.get("kind") in TERMINAL_EVENT_KINDS), None
            )
            if finished:
                kind = str(finished.get("kind"))
                if kind in FAILED_EVENT_KINDS:
                    return WorkerResult(
                        worker_id=conv_id,
                        status=WorkerStatus.FAILED,
                        error=finished.get("message")
                        or f"OpenHands conversation {kind}",
                        error_code=ErrorCode.OPENHANDS_TASK_FAILED,
                        metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                    )
                output = finished.get("result") or finished.get("message", "")
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.COMPLETED,
                    output=output[: self._config.max_output_chars],
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )
        except Exception as ws_err:  # WebSocket streaming can fail on any network/protocol error; fall back to REST polling  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(
                f"OpenHands WS stream failed, falling back to polling: {ws_err}"
            )

        # REST polling fallback
        elapsed = 0.0
        while elapsed < timeout:
            try:
                data = await self._client.get_status(conv_id)
            except Exception as e:  # REST status poll may raise any HTTP/timeout error; map to WorkerResult FAILED  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.FAILED,
                    error=str(e),
                    error_code=ErrorCode.OPENHANDS_SERVICE_ERROR,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )

            # The REST status field carries the API's vocabulary — the
            # same one the socket's ``kind`` uses. One vocabulary, or the
            # fallback and the socket disagree about what "done" is.
            status = str(data.get("status") or "")
            if status in TERMINAL_EVENT_KINDS:
                if status in FAILED_EVENT_KINDS:
                    return WorkerResult(
                        worker_id=conv_id,
                        status=WorkerStatus.FAILED,
                        error=data.get("error") or f"OpenHands conversation {status}",
                        error_code=ErrorCode.OPENHANDS_TASK_FAILED,
                        duration_seconds=elapsed,
                        metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                    )
                output = data.get("result", "")
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.COMPLETED,
                    output=str(output)[: self._config.max_output_chars],
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )

            await asyncio.sleep(self._config.poll_interval_seconds)
            elapsed += self._config.poll_interval_seconds

        return WorkerResult(
            worker_id=conv_id,
            status=WorkerStatus.TIMEOUT,
            error="OpenHands task timed out",
            duration_seconds=elapsed,
            metadata={"worker_type": self.worker_type, "conv_id": conv_id},
        )

    async def stop(self) -> None:
        try:
            self._status = WorkerStatus.COMPLETED
        finally:
            await self._client.close()

    async def status(self) -> WorkerStatus:
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        return {"status": self._status.value, "worker_type": self.worker_type}
