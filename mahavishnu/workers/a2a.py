from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING
import uuid

import httpx
from oneiric.core.logging import get_logger

from mahavishnu.a2a import A2AError
from mahavishnu.a2a.card import AgentCard
from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

if TYPE_CHECKING:
    from typing import Any

logger = get_logger(__name__)


@dataclass
class A2AAgentConfig:
    """Resolved agent entry — URL is always from settings, never from task input."""

    name: str
    url: str
    description: str = ""
    api_key: str | None = None  # already resolved from api_key_env at construction


# ─── helpers ──────────────────────────────────────────────────────────────────


def _build_task_payload(task_id: str, prompt: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "message": {"role": "user", "parts": [{"type": "text", "text": prompt}]},
    }


def _event_to_result(task_id: str, event: dict[str, Any]) -> WorkerResult:
    state = event.get("status", {}).get("state", "failed")
    if state == "completed":
        artifacts = event.get("artifacts", [])
        output = artifacts[0].get("parts", [{}])[0].get("text", "") if artifacts else ""
        return WorkerResult(
            worker_id=task_id,
            status=WorkerStatus.COMPLETED,
            output=output,
            metadata={"worker_type": "a2a"},
        )
    return WorkerResult(
        worker_id=task_id,
        status=WorkerStatus.FAILED,
        error=event.get("status", {}).get("message", "A2A task failed"),
        error_code=ErrorCode.A2A_AGENT_ERROR,
        metadata={"worker_type": "a2a"},
    )


# ─── A2AClient ────────────────────────────────────────────────────────────────


class A2AClient:
    """Thin httpx wrapper for the Google A2A protocol."""

    _CARD_TIMEOUT: float = 10.0
    _TASK_TIMEOUT: float = 600.0

    def __init__(self, config: A2AAgentConfig) -> None:
        self._config = config
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.AsyncClient(
            base_url=config.url,
            headers=headers,
            timeout=httpx.Timeout(self._TASK_TIMEOUT),
            follow_redirects=False,
        )

    async def fetch_card(self) -> AgentCard:
        """GET /.well-known/agent.json — raises httpx.HTTPStatusError on non-2xx."""
        resp = await self._http.get(
            "/.well-known/agent.json",
            timeout=self._CARD_TIMEOUT,
        )
        resp.raise_for_status()
        return AgentCard.model_validate(resp.json())

    async def send_task(self, task_id: str, prompt: str) -> dict[str, Any]:
        """POST /tasks/send — synchronous, returns the final task object."""
        resp = await self._http.post(
            "/tasks/send",
            json=_build_task_payload(task_id, prompt),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def send_task_subscribe(self, task_id: str, prompt: str) -> WorkerResult:
        """POST /tasks/sendSubscribe — SSE stream; returns WorkerResult on final event."""
        async with self._http.stream(
            "POST",
            "/tasks/sendSubscribe",
            json=_build_task_payload(task_id, prompt),
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                if event.get("final"):
                    return _event_to_result(task_id, event)
        raise A2AError("SSE stream closed without a final event")

    async def close(self) -> None:
        await self._http.aclose()


# ─── A2AWorker ────────────────────────────────────────────────────────────────


class A2AWorker(BaseWorker):
    """Routes tasks to external A2A-compliant agents by name.

    Agent name → URL resolution is from the configured registry only.
    URLs never come from task input (SSRF prevention).
    """

    def __init__(self, agent_configs: dict[str, A2AAgentConfig]) -> None:
        super().__init__(worker_type="a2a")
        self._registry = agent_configs  # name → A2AAgentConfig

    async def start(self) -> str:
        self._status = WorkerStatus.RUNNING
        return "a2a"

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        agent_name: str = task.get("agent", "")
        prompt: str = task.get("prompt", "")

        if agent_name not in self._registry:
            return WorkerResult(
                worker_id="a2a",
                status=WorkerStatus.FAILED,
                error=f"Unknown A2A agent: {agent_name!r}",
                error_code=ErrorCode.A2A_AGENT_NOT_FOUND,
                metadata={"worker_type": "a2a"},
            )

        config = self._registry[agent_name]
        client = A2AClient(config)
        task_id = str(uuid.uuid4())

        try:
            card = await client.fetch_card()
            if card.capabilities.streaming:
                return await client.send_task_subscribe(task_id, prompt)
            data = await client.send_task(task_id, prompt)
            return _event_to_result(task_id, data)
        except httpx.HTTPStatusError as e:
            logger.exception("A2A HTTP error for agent %r", agent_name)
            return WorkerResult(
                worker_id=task_id,
                status=WorkerStatus.FAILED,
                error=f"Remote agent returned HTTP {e.response.status_code}",
                error_code=ErrorCode.A2A_AGENT_ERROR,
                metadata={"worker_type": "a2a", "agent": agent_name},
            )
        except A2AError:
            logger.exception("A2A protocol error for agent %r", agent_name)
            return WorkerResult(
                worker_id=task_id,
                status=WorkerStatus.FAILED,
                error="A2A protocol error (stream closed without final event)",
                error_code=ErrorCode.A2A_AGENT_ERROR,
                metadata={"worker_type": "a2a", "agent": agent_name},
            )
        except Exception:
            logger.exception("Unexpected error for A2A agent %r", agent_name)
            return WorkerResult(
                worker_id=task_id,
                status=WorkerStatus.FAILED,
                error="A2A task failed unexpectedly",
                error_code=ErrorCode.A2A_AGENT_ERROR,
                metadata={"worker_type": "a2a", "agent": agent_name},
            )
        finally:
            await client.close()

    async def stop(self) -> None:
        self._status = WorkerStatus.COMPLETED

    async def status(self) -> WorkerStatus:
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        return {"status": self._status.value, "worker_type": self.worker_type}
