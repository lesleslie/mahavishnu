"""Unit tests for ``mahavishnu.mcp.tools.worker_tools.worker_spawn``.

The durable-worker contract (F1) routes shell-based worker types
(``SHELL``, ``AI_ASSISTANT``, ``REMOTE``) through
``_durable_manager.spawn`` so they get tmux-backed lifecycle tracking.
Non-shell workers (container, gateway, application) continue to use the
legacy ``WorkerManager.spawn_workers`` path.

The fixture mirrors the Task 13 convention in
``tests/unit/mcp/tools/test_worker_contract_tools.py`` — the module-level
``_durable_manager`` and ``_worker_manager`` references are monkeypatched
so the tests do not need a real FastMCP app.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _durable_result(worker_id: str) -> MagicMock:
    """Build the SpawnResult-shaped mock returned by ``contract manager.spawn``."""
    record = MagicMock()
    record.worker_id = worker_id
    return MagicMock(worker_id=worker_id, record=record)


def test_worker_spawn_uses_durable_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shell worker types are routed through ``_durable_manager.spawn``."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.spawn = MagicMock(return_value=_durable_result("w-1"))
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    # _worker_manager should NOT be touched on the durable path.
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_spawn("terminal-claude", 1))

    assert out["worker_ids"] == ["w-1"]
    manager.spawn.assert_called_once()
    call_kwargs = manager.spawn.call_args.kwargs
    assert call_kwargs["worker_type"] == "terminal-claude"


def test_worker_spawn_routes_non_shell_through_legacy_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-shell worker types fall back to ``_worker_manager.spawn_workers``."""
    from mahavishnu.mcp.tools import worker_tools

    legacy = MagicMock()
    legacy.spawn_workers = AsyncMock(return_value=["w-1", "w-2"])
    monkeypatch.setattr(worker_tools, "_worker_manager", legacy)

    durable = MagicMock()
    durable.spawn = MagicMock()
    monkeypatch.setattr(worker_tools, "_durable_manager", durable)

    out = asyncio.run(worker_tools.worker_spawn("container", 2))

    assert out["worker_ids"] == ["w-1", "w-2"]
    legacy.spawn_workers.assert_awaited_once_with(worker_type="container", count=2)
    durable.spawn.assert_not_called()


def test_worker_spawn_falls_back_when_durable_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shell worker types fall back to legacy when durable manager is not configured."""
    from mahavishnu.mcp.tools import worker_tools

    legacy = MagicMock()
    legacy.spawn_workers = AsyncMock(return_value=["w-1"])
    monkeypatch.setattr(worker_tools, "_worker_manager", legacy)
    monkeypatch.setattr(worker_tools, "_durable_manager", None)

    out = asyncio.run(worker_tools.worker_spawn("terminal-claude", 1))

    assert out["worker_ids"] == ["w-1"]
    legacy.spawn_workers.assert_awaited_once_with(worker_type="terminal-claude", count=1)


def test_worker_spawn_validates_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """count bounds are enforced before either path is touched."""
    from mahavishnu.mcp.tools import worker_tools

    durable = MagicMock()
    durable.spawn = MagicMock()
    monkeypatch.setattr(worker_tools, "_durable_manager", durable)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    with pytest.raises(ValueError, match="count must be between 1 and 50"):
        asyncio.run(worker_tools.worker_spawn("terminal-claude", 0))
    with pytest.raises(ValueError, match="count must be between 1 and 50"):
        asyncio.run(worker_tools.worker_spawn("terminal-claude", 51))

    durable.spawn.assert_not_called()
