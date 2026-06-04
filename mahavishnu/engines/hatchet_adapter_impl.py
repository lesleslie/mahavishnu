"""Hatchet durable workflow adapter for Mahavishnu.

Dispatches tasks to a Hatchet server as named workflow runs.
WaitForEvent steps in those workflows connect to the approval
primitives via event key "mahavishnu.approval.<run_id>".
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
from mahavishnu.core.config import HatchetConfig

logger = logging.getLogger(__name__)

_APPROVAL_EVENT_PREFIX = "mahavishnu.approval"


class HatchetAdapterImpl(OrchestratorAdapter):
    """Adapter that dispatches durable agent-loop workflows to Hatchet.

    Args:
        config: HatchetConfig with server_url, namespace, and timeout settings.
    """

    def __init__(self, config: HatchetConfig | None = None) -> None:
        self._config = config or HatchetConfig()
        self._client: Any = None

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.HATCHET

    @property
    def name(self) -> str:
        return "hatchet"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=False,
            supports_batch_execution=False,
            has_cloud_ui=True,
            supports_multi_agent=True,
        )

    async def initialize(self) -> None:
        """Connect to Hatchet server using HATCHET_CLIENT_TOKEN."""
        token = os.environ.get("HATCHET_CLIENT_TOKEN", "")
        if not token:
            raise RuntimeError(
                "HatchetAdapterImpl requires HATCHET_CLIENT_TOKEN environment variable."
            )
        try:
            from hatchet_sdk import Hatchet
            from hatchet_sdk.config import ClientConfig
        except ImportError:
            raise RuntimeError(
                "hatchet-sdk not installed. Install with: uv pip install 'mahavishnu[hatchet]'"
            ) from None

        # hatchet-sdk exposes a Pydantic ClientConfig; the Hatchet() constructor
        # does not accept token/host_port/namespace as kwargs directly.
        self._client = Hatchet(
            config=ClientConfig(
                token=token,
                host_port=self._config.server_url,
                namespace=self._config.namespace,
            ),
        )
        logger.info(
            "HatchetAdapter initialized: server=%s namespace=%s",
            self._config.server_url,
            self._config.namespace,
        )

    async def cleanup(self) -> None:
        """Close Hatchet client connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                logger.warning("Error closing Hatchet client: %s", exc)
            finally:
                self._client = None

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Dispatch a durable workflow run to Hatchet.

        Task keys:
            prompt (str, required): Workflow input / user message.
            workflow_name (str): Hatchet workflow to dispatch (default: "agent-loop").
            timeout (int): Override task timeout in seconds.
        """
        if self._client is None:
            await self.initialize()

        prompt = task.get("prompt", "")
        if not prompt:
            return {"status": "error", "error": "prompt is required", "output": ""}

        workflow_name = task.get("workflow_name", "agent-loop")
        timeout = task.get("timeout", self._config.task_timeout_seconds)

        try:
            # hatchet-sdk >=1.0: Hatchet.run() is async (returns a coroutine).
            # Guard against SDK variants that return a WorkflowRunRef requiring .result().
            coro_or_ref = self._client.run(
                workflow_name,
                input={"prompt": prompt, "repos": repos},
            )
            if asyncio.iscoroutine(coro_or_ref):
                awaitable = coro_or_ref
            elif hasattr(coro_or_ref, "result"):
                awaitable = coro_or_ref.result()
            else:
                awaitable = coro_or_ref
            run_result = await asyncio.wait_for(awaitable, timeout=timeout)

            return {
                "status": "completed",
                "output": run_result.get("output", ""),
                "run_id": run_result.get("run_id", ""),
                "adapter": self.name,
                "workflow": workflow_name,
            }

        except TimeoutError:
            logger.warning("Hatchet run timed out after %ss", timeout)
            return {
                "status": "timeout",
                "error": f"Hatchet workflow timed out after {timeout}s",
                "output": "",
            }
        except Exception as exc:
            logger.error("Hatchet execute failed: %s", exc)
            return {"status": "error", "error": str(exc), "output": ""}

    async def get_health(self) -> dict[str, Any]:
        """Return health status for the Hatchet adapter."""
        if self._client is None:
            return {
                "status": "unhealthy",
                "details": {"reason": "client not initialized"},
            }
        try:
            await asyncio.wait_for(self._client.rest.workflow_list(), timeout=5.0)
            return {
                "status": "healthy",
                "details": {
                    "server_url": self._config.server_url,
                    "namespace": self._config.namespace,
                },
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "details": {"error": str(exc)},
            }

    async def send_approval_event(self, run_id: str, approved: bool) -> None:
        """Send a WaitForEvent completion to an in-progress Hatchet run.

        Bridges Mahavishnu's approval primitives to Hatchet's WaitForEvent step.
        Call from any approval handler to unblock a paused agent-loop workflow.
        """
        if self._client is None:
            raise RuntimeError("HatchetAdapter not initialized")
        event_key = f"{_APPROVAL_EVENT_PREFIX}.{run_id}"
        await self._client.event.push(
            event_key,
            payload={"approved": approved, "run_id": run_id},
        )
        logger.info("Sent approval event: run_id=%s approved=%s", run_id, approved)


__all__ = ["HatchetAdapterImpl"]
