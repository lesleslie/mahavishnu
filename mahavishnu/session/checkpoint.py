"""Session-Buddy integration for Mahavishnu."""

import logging
from typing import Any, cast
import uuid

import httpx

from ..core.config import MahavishnuSettings
from ..core.errors import ExternalServiceError, TimeoutError

logger = logging.getLogger(__name__)

_TOOLS_CALL_PATH = "/tools/call"


class SessionBuddy:
    """Session management and checkpoint integration with Session-Buddy.

    Acts as a write-forward sink: lifecycle events are pushed to Session-Buddy
    for durability and analysis, but checkpoint IDs are managed locally.
    Session-Buddy does not provide a CRUD checkpoint lookup API.
    """

    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.enabled = config.session.enabled
        self.checkpoint_interval = config.session.checkpoint_interval
        self._base_url = config.pools.session_buddy_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def _call_mcp(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}{_TOOLS_CALL_PATH}",
                json={"name": tool_name, "arguments": arguments},
            )
            response.raise_for_status()
            return cast("dict[str, Any]", response.json())
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"session-buddy:{tool_name}",
                details={"tool": tool_name, "url": self._base_url},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                "session-buddy",
                f"Tool '{tool_name}' returned {exc.response.status_code}",
                details={"tool": tool_name, "status_code": exc.response.status_code},
            ) from exc
        except httpx.TransportError as exc:
            raise ExternalServiceError(
                "session-buddy",
                f"Unreachable: {exc}",
                details={"tool": tool_name, "url": self._base_url},
            ) from exc

    async def is_healthy(self) -> bool:
        health_url = self._base_url.replace("/mcp", "/health")
        try:
            r = await self._client.get(health_url, timeout=5.0)
            return r.status_code == 200
        except (httpx.HTTPError, httpx.TransportError):
            return False

    async def create_checkpoint(self, session_id: str, state: dict[str, Any]) -> str:
        checkpoint_id = str(uuid.uuid4())
        if not self.enabled:
            return f"checkpoint_disabled_{session_id}"

        quality_score = state.get("quality_score") if isinstance(state, dict) else None
        try:
            await self._call_mcp(
                "store_conversation_checkpoint",
                {
                    "checkpoint_type": "workflow",
                    **({"quality_score": quality_score} if quality_score is not None else {}),
                },
            )
            logger.debug(
                "Checkpoint %s stored in Session-Buddy for session %s", checkpoint_id, session_id
            )
        except (ExternalServiceError, TimeoutError) as exc:
            logger.warning("Session-Buddy checkpoint create degraded: %s — returning local ID", exc)

        return checkpoint_id

    async def update_checkpoint(
        self, checkpoint_id: str, status: str, result: dict[str, Any] | None = None
    ) -> bool:
        if not self.enabled:
            return True

        terminal_states = {"completed", "failed", "cancelled"}
        if status not in terminal_states:
            logger.debug(
                "Checkpoint %s status=%s (non-terminal, not forwarded to Session-Buddy)",
                checkpoint_id,
                status,
            )
            return True

        quality_score = None
        if isinstance(result, dict):
            quality_score = result.get("quality_score") or result.get("score")

        try:
            await self._call_mcp(
                "store_conversation_checkpoint",
                {
                    "checkpoint_type": f"workflow_{status}",
                    **({"quality_score": int(quality_score)} if quality_score is not None else {}),
                },
            )
            logger.debug(
                "Checkpoint %s terminal state '%s' forwarded to Session-Buddy",
                checkpoint_id,
                status,
            )
            return True
        except (ExternalServiceError, TimeoutError) as exc:
            logger.warning("Session-Buddy checkpoint update degraded: %s", exc)
            return False

    async def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        # Session-Buddy has no lookup-by-ID API — callers handle None.
        return None

    async def restore_from_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        # Session-Buddy has no restore-by-ID API — orchestration recovery uses local state.
        return None

    async def cleanup_checkpoint(self, checkpoint_id: str) -> bool:
        # No remote resource to clean up.
        return True
