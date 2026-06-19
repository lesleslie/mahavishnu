from __future__ import annotations

import asyncio
from typing import Any

import httpx
from oneiric.core.logging import get_logger

from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = get_logger(__name__)

_ACP_TIMEOUT = 30.0


class CrowWorker(BaseWorker):
    """Worker for crow-cli's ACP reasoning layer.

    Use this for multi-step autonomous tasks where crow-cli drives the loop.
    For PTY pass-through (launching a shell/AI assistant in a terminal),
    use GenericShellWorker with CrowTerminalAdapter instead.

    ACP lifecycle: initialize → new_session → prompt → poll → result
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8765",
        session_buddy_client: Any | None = None,
    ) -> None:
        super().__init__(worker_type="terminal-crow")
        self._base_url = base_url.rstrip("/")
        self._session_buddy_client = session_buddy_client
        self._session_id: str | None = None
        self._client = httpx.AsyncClient(timeout=_ACP_TIMEOUT)

    async def start(self) -> str:
        """Initialize ACP connection and create a session."""
        resp = await self._client.post(
            f"{self._base_url}/acp/new_session",
            json={"agent": "crow"},
        )
        resp.raise_for_status()
        self._session_id = resp.json()["session_id"]
        self._status = WorkerStatus.RUNNING
        logger.info(f"CrowWorker ACP session started: {self._session_id}")
        return self._session_id  # type: ignore[return-value]  # BaseWorker.start() returns str | None; always str here after assignment

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Send prompt to crow-cli ACP and poll for result."""
        if not self._session_id:
            await self.start()

        prompt = task.get("prompt", "")
        timeout = task.get("timeout", 300)

        resp = await self._client.post(
            f"{self._base_url}/acp/prompt",
            json={"session_id": self._session_id, "prompt": prompt},
        )
        resp.raise_for_status()

        elapsed = 0.0
        poll_interval = 2.0
        while elapsed < timeout:
            poll = await self._client.get(
                f"{self._base_url}/acp/status/{self._session_id}",
            )
            poll.raise_for_status()
            data = poll.json()

            if data.get("status") == "completed":
                return WorkerResult(
                    worker_id=self._session_id or "crow",
                    status=WorkerStatus.COMPLETED,
                    output=data.get("result", ""),
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type},
                )
            if data.get("status") == "error":
                return WorkerResult(
                    worker_id=self._session_id or "crow",
                    status=WorkerStatus.FAILED,
                    output=None,
                    error=data.get("error", "ACP task failed"),
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type},
                )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return WorkerResult(
            worker_id=self._session_id or "crow",
            status=WorkerStatus.TIMEOUT,
            error="ACP task timed out",
            duration_seconds=elapsed,
            metadata={"worker_type": self.worker_type},
        )

    async def stop(self) -> None:
        """Cancel ACP session."""
        try:
            if self._session_id:
                try:
                    await self._client.post(
                        f"{self._base_url}/acp/cancel/{self._session_id}",
                    )
                except Exception as e:
                    logger.warning(f"Failed to cancel CrowWorker ACP session: {e}")
                finally:
                    self._status = WorkerStatus.COMPLETED
        finally:
            await self._client.aclose()

    async def status(self) -> WorkerStatus:
        """Return current worker status."""
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Return progress information."""
        return {
            "status": self._status.value,
            "session_id": self._session_id,
            "worker_type": self.worker_type,
        }


__all__ = ["CrowWorker"]
