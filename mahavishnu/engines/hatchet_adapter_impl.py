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
from mahavishnu.core.capabilities import (
    Capability,
    CapabilityKind,
    CapabilityState,
    CostHint,
    TypeSchema,
)
from mahavishnu.core.config import HatchetConfig

logger = logging.getLogger(__name__)

_APPROVAL_EVENT_PREFIX = "mahavishnu.approval"


def _hatchet_run_output(run_result: object) -> str:
    """Extract the run's output text from whatever shape the SDK returned.

    ``hatchet-sdk`` 1.43's ``runs.aio_create`` returns a pydantic
    ``V1WorkflowRunDetails``, whose output lives on the nested ``run``
    (``V1WorkflowRun``); older ``Hatchet.run`` returned a plain dict.
    Normalize both to a string.
    """
    if isinstance(run_result, dict):
        value = run_result.get("output", "")
    else:
        value = getattr(run_result, "output", None)
        if value is None:
            nested = getattr(run_result, "run", None)
            value = getattr(nested, "output", None)
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _hatchet_run_id(run_result: object) -> str:
    """Extract the run id from whatever shape the SDK returned.

    ``V1WorkflowRunDetails`` carries the id on the nested ``run`` as
    ``displayName`` -- Hatchet v1 uses the display name as the run id.
    Without this the demo reported an empty run id for every dispatch.
    """
    if isinstance(run_result, dict):
        value = run_result.get("run_id") or run_result.get("id")
    else:
        value = getattr(run_result, "run_id", None) or getattr(run_result, "id", None)
        if value is None:
            nested = getattr(run_result, "run", None)
            # The SDK's pydantic models expose snake_case field names
            # (``display_name``) even though the wire format is camelCase.
            value = (
                getattr(nested, "display_name", None)
                or getattr(nested, "displayName", None)
                or getattr(nested, "workflow_version_id", None)
                or getattr(nested, "workflowVersionId", None)
            )
    return "" if value is None else str(value)


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

    @property
    def provides(self) -> list[Capability]:
        """Capabilities this engine exposes to the conductor.

        Surfaces ``engine:durable-flow-alternative`` so the worker-registry-capability-refactor
        conductor (Phase 3a) can route durable-flow workloads to Hatchet
        when preferred over Prefect (Hatchet is the alternative backend).
        """
        return [
            Capability(
                id="engine:durable-flow-alternative",
                kind=CapabilityKind.ENGINE,
                description="Durable agent-loop workflow execution via Hatchet",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.DURABLE,
                cost_hint=CostHint(has_side_effects=True),
            ),
        ]

    async def initialize(self) -> None:
        """Connect to Hatchet -- the embedded engine, or a server.

        With ``config.use_embedded`` the SDK's embedded engine runs
        in-process (no Docker, no API token). Otherwise the client
        connects to ``config.server_url`` using ``HATCHET_CLIENT_TOKEN``;
        with no ``server_url`` configured, the SDK derives the address
        from the token itself.
        """
        try:
            from hatchet_sdk import Hatchet
            from hatchet_sdk.config import ClientConfig
        except ImportError:
            raise RuntimeError(
                "hatchet-sdk not installed. Install with: uv sync --group hatchet "
                "(or pull it transitively via: uv sync --group dev)"
            ) from None

        if self._config.use_embedded:
            # The embedded engine runs in-process and issues its own
            # address and token at startup, so neither HATCHET_CLIENT_TOKEN
            # nor a reachable server is required. It is also the only path
            # that needs no Docker.
            self._client = Hatchet.from_embedded()
            logger.info(
                "HatchetAdapter initialized: embedded engine namespace=%s",
                self._config.namespace,
            )
            return

        token = os.environ.get("HATCHET_CLIENT_TOKEN", "")
        if not token:
            raise RuntimeError(
                "HatchetAdapterImpl requires HATCHET_CLIENT_TOKEN environment variable."
            )

        # hatchet-sdk exposes a Pydantic ClientConfig; the Hatchet() constructor
        # does not accept token/host_port/namespace as kwargs directly.
        #
        # ``host_port`` is passed only when a server is actually configured.
        # The SDK derives it from the token otherwise (``ClientConfig``'s
        # ``validate_addresses`` reads the token's own broadcast address when
        # the field is not explicitly set), and passing it unconditionally
        # overrode the address the credential was issued for.
        config_kwargs: dict[str, Any] = {
            "token": token,
            "namespace": self._config.namespace,
        }
        if self._config.server_url:
            config_kwargs["host_port"] = self._config.server_url
        self._client = Hatchet(config=ClientConfig(**config_kwargs))
        logger.info(
            "HatchetAdapter initialized: server=%s namespace=%s",
            self._config.server_url or "(derived from token)",
            self._config.namespace,
        )

    @property
    def client(self) -> Any:
        """The underlying Hatchet client, or ``None`` before ``initialize()``.

        Exposed so a caller can act on the engine directly -- registering
        a workflow definition, for instance -- without reaching into the
        adapter's private state.
        """
        return self._client

    async def cleanup(self) -> None:
        """Close Hatchet client connection.

        ``hatchet-sdk`` 1.43 dropped ``Hatchet.close()`` -- the client
        no longer owns a closable handle -- so calling it unconditionally
        raised ``AttributeError: 'Hatchet' object has no attribute
        'close'``. Close only when the installed SDK actually exposes a
        closer, and stay quiet when it does not.
        """
        if self._client is not None:
            closer = getattr(self._client, "close", None)
            if not callable(closer):
                closer = getattr(self._client, "aclose", None)
            if not callable(closer):
                self._client = None
                return
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # engine adapter wrapping third-party Hatchet client call — broad catch isolates external failures from adapter caller  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
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
            # The trigger API moved across hatchet-sdk majors:
            #   - older:  ``Hatchet.run(workflow_name, input=...)``
            #   - >=1.43: ``Hatchet.runs.aio_create(workflow_name, input=...)``
            # ``Hatchet.run`` was removed in 1.43, so the old call raised
            # ``AttributeError: 'Hatchet' object has no attribute 'run'``.
            # Probe for the legacy attribute *first*: a client that still
            # has ``run`` uses it, and a 1.43+ client (which has no
            # ``run`` at all) falls through to ``runs.aio_create``.
            legacy_run = getattr(self._client, "run", None)
            if callable(legacy_run):
                coro_or_ref = legacy_run(
                    workflow_name,
                    input={"prompt": prompt, "repos": repos},
                )
            else:
                runs_client = getattr(self._client, "runs", None)
                aio_create = getattr(runs_client, "aio_create", None)
                if not callable(aio_create):
                    raise TypeError(
                        "the installed hatchet-sdk exposes neither "
                        "Hatchet.run() nor Hatchet.runs.aio_create() -- "
                        "unsupported hatchet-sdk version"
                    )
                coro_or_ref = aio_create(
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
                "output": _hatchet_run_output(run_result),
                "run_id": _hatchet_run_id(run_result),
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
        except Exception as exc:  # engine adapter wrapping third-party Hatchet client call — broad catch isolates external failures from adapter caller  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
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
            # The installed hatchet-sdk exposes the workflow list on
            # ``client.workflows`` (an async ``aio_list``); there is no
            # ``client.rest`` attribute, so the old call raised
            # AttributeError and every health check reported unhealthy.
            await asyncio.wait_for(self._client.workflows.aio_list(), timeout=5.0)
            return {
                "status": "healthy",
                "details": {
                    "server_url": self._config.server_url or "(embedded engine)",
                    "namespace": self._config.namespace,
                },
            }
        except Exception as exc:  # engine adapter wrapping third-party Hatchet client call — broad catch isolates external failures from adapter caller  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
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
