from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = get_logger(__name__)


@dataclass
class OpenHandsConfig:
    base_url: str = "http://localhost:3000"
    workspace_dir: Path = Path("/tmp/openhands-workspace")  # noqa: S108
    timeout_seconds: int = 600
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
        """Start an OpenHands conversation and return its conv_id."""
        resp = await self._http.post(
            "/api/conversations",
            json={"task": task},
        )
        resp.raise_for_status()
        return resp.json()["conversation_id"]  # type: ignore[no-any-return]

    async def get_status(self, conv_id: str) -> dict[str, Any]:
        """Poll REST endpoint for conversation status."""
        resp = await self._http.get(f"/api/conversations/{conv_id}")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def stream_events(self, conv_id: str) -> list[dict[str, Any]]:
        """Attempt to consume WebSocket events (best-effort, may raise)."""
        import json  # noqa: PLC0415

        import websockets  # noqa: PLC0415

        url = (
            self._config.base_url.replace("http://", "ws://").replace("https://", "wss://")
            + f"/ws?conversation_id={conv_id}"
        )
        events: list[dict[str, Any]] = []
        async with websockets.connect(url) as ws:
            async for raw in ws:
                event = json.loads(raw)
                events.append(event)
                if event.get("type") in ("FINISHED", "ERROR"):
                    break
        return events

    async def cancel_conversation(self, conv_id: str) -> None:
        await self._http.delete(f"/api/conversations/{conv_id}")

    async def health_check(self) -> bool:
        try:
            resp = await self._http.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
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

    async def start(self) -> str:
        """Mark the worker as running and return a fixed worker ID."""
        self._status = WorkerStatus.RUNNING
        return "openhands"

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Submit a task to OpenHands and poll/stream until completion."""
        prompt = task.get("prompt", "")
        timeout = task.get("timeout", self._config.timeout_seconds)

        try:
            conv_id = await self._client.create_conversation(prompt)
        except Exception as e:
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
                (e for e in events if e.get("type") in ("FINISHED", "ERROR")), None
            )
            if finished:
                if finished.get("type") == "ERROR":
                    return WorkerResult(
                        worker_id=conv_id,
                        status=WorkerStatus.FAILED,
                        error=finished.get("message", "OpenHands task failed"),
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
        except Exception as ws_err:
            logger.warning(
                f"OpenHands WS stream failed, falling back to polling: {ws_err}"
            )

        # REST polling fallback
        elapsed = 0.0
        while elapsed < timeout:
            try:
                data = await self._client.get_status(conv_id)
            except Exception as e:
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.FAILED,
                    error=str(e),
                    error_code=ErrorCode.OPENHANDS_SERVICE_ERROR,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )

            status = data.get("status")
            if status == "completed":
                output = data.get("result", "")
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.COMPLETED,
                    output=str(output)[: self._config.max_output_chars],
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )
            if status == "error":
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.FAILED,
                    error=data.get("error", "OpenHands task failed"),
                    error_code=ErrorCode.OPENHANDS_TASK_FAILED,
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
        self._status = WorkerStatus.COMPLETED
        await self._client.close()

    async def status(self) -> WorkerStatus:
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        return {"status": self._status.value, "worker_type": self.worker_type}
