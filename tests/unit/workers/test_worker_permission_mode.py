"""The envelope's permission mode must reach the agent's command line.

The envelope projects a server-derived permission mode into the worker's
task dict — one that is never ``yolo``. If nothing reads it, the mode
that reaches the CLI is the registry default, and ``terminal-qwen``'s
registry default is ``yolo``: auto-approve, no human gate. The control
is only a control if it is threaded from the envelope to the worker
factory.

The operator's setting still wins: ``workers.permission_modes`` is the
deployment's own decision about its agents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.adapters.worker import WorkerOrchestratorAdapter
from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.registry import get_worker_config

if TYPE_CHECKING:
    from mahavishnu.workers.registry import WorkerConfig


def _manager(permission_modes: dict[str, str] | None = None) -> WorkerManager:
    """A WorkerManager whose operator setting is exactly what is asked for."""
    from mahavishnu.core.config import MahavishnuSettings

    settings = MahavishnuSettings(
        server_name="Test Server",
        observability_enabled=False,
        terminal_enabled=False,
        pools={"enabled": False},
        workers={"enabled": False, "permission_modes": permission_modes or {}},
        otel_storage={"enabled": False},
    )
    return WorkerManager(terminal_manager=MagicMock(), settings=settings)


def _qwen_config() -> WorkerConfig:
    config = get_worker_config("terminal-qwen")
    assert config is not None
    return config


class TestTheRegistryDefaultIsTheProblem:
    """The premise: the registry default for qwen is auto-approve."""

    def test_terminal_qwen_defaults_to_yolo(self) -> None:
        assert _qwen_config().permission_mode == "yolo"


class TestTheEnvelopeModeReachesTheWorker:
    def test_the_envelope_mode_wins_over_the_registry_default(self) -> None:
        manager = _manager()
        mode = manager._resolve_permission_mode(_qwen_config(), "plan")
        assert mode == "plan"

    def test_the_operator_setting_wins_over_the_envelope_mode(self) -> None:
        # The deployment's own decision about its agents outranks the
        # envelope's server-side default table.
        manager = _manager({"terminal-qwen": "auto"})
        mode = manager._resolve_permission_mode(_qwen_config(), "plan")
        assert mode == "auto"

    def test_the_registry_default_is_the_last_resort(self) -> None:
        # A caller that reaches the worker manager without an envelope
        # keeps today's behaviour.
        manager = _manager()
        mode = manager._resolve_permission_mode(_qwen_config())
        assert mode == "yolo"

    def test_an_invalid_mode_is_refused(self) -> None:
        # The mode is substituted into a command line; an unchecked value
        # could smuggle a flag into the agent's argv.
        manager = _manager()
        with pytest.raises(ValueError):
            manager._resolve_permission_mode(_qwen_config(), "bypassPermissions")


class TestTheAdapterThreadsTheMode:
    @pytest.mark.asyncio
    async def test_the_adapter_passes_the_permission_mode_to_the_manager(self) -> None:
        manager = MagicMock()
        manager.submit_workers = AsyncMock(return_value=["worker-1"])
        manager.execute_batch = AsyncMock(return_value={})
        manager.collect_results = AsyncMock(return_value={})
        adapter = WorkerOrchestratorAdapter(worker_manager=manager)

        await adapter.execute(
            {
                "prompt": "do the thing",
                "worker_type": "terminal-qwen",
                "permission_mode": "plan",
                "count": 1,
            },
            ["/repo/a"],
        )

        await_args = manager.submit_workers.await_args
        assert await_args is not None
        assert await_args.kwargs["permission_mode"] == "plan"

    @pytest.mark.asyncio
    async def test_the_adapter_passes_no_mode_when_the_task_carries_none(self) -> None:
        manager = MagicMock()
        manager.submit_workers = AsyncMock(return_value=["worker-1"])
        manager.execute_batch = AsyncMock(return_value={})
        manager.collect_results = AsyncMock(return_value={})
        adapter = WorkerOrchestratorAdapter(worker_manager=manager)

        await adapter.execute(
            {"prompt": "do the thing", "worker_type": "terminal-qwen", "count": 1},
            ["/repo/a"],
        )

        await_args = manager.submit_workers.await_args
        assert await_args is not None
        assert await_args.kwargs.get("permission_mode") is None
