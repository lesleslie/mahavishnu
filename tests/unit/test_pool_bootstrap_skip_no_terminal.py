"""Test: ``pool_bootstrap`` MCP tool skips gracefully when
``terminal_manager`` is uninitialized.

Wave 7 (2026-10-09) wiring fix. The previous behavior hard-failed
with ``{"status": "failed", "error": "Cannot spawn pool:
terminal_manager is not available. ... Ensure terminal
management is enabled and the adapter is properly initialized."}``
whenever the terminal subsystem failed to initialize — common in
lite-mode / tmux-unavailable / dev environments. The new contract
returns ``{"status": "skipped", "reason":
"terminal_manager_unavailable"}`` so the SessionStart hook and
observability surface can see the exact reason pools are empty
without the spawn crashing the entire hook.

The fix: gate the spawn on
``getattr(pool_manager, "terminal_manager", None) is None``
BEFORE calling ``spawn_pool``. Only the ``mahavishnu`` pool
substrate needs a terminal manager (``session-buddy`` and
``runpod`` are substrate-fixed), so the gate is also
pool-type-aware.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools.pool_tools import register_pool_tools


class _NoOpMcp:
    """Stand-in for fastmcp.FastMCP — captures registered tool
    functions.
    """

    def __init__(self) -> None:
        self._registered: dict[str, Any] = {}

    def tool(self) -> Any:  # noqa: ANN401 - test stub
        def _decorator(fn: Any) -> Any:  # noqa: ANN401 - test stub
            self._registered[fn.__name__] = fn
            return fn

        return _decorator


def _make_pool_manager(terminal_manager: Any) -> MagicMock:
    pm = MagicMock()
    pm.terminal_manager = terminal_manager
    pm.health_check = AsyncMock(return_value={"pools_active": 0})
    pm.spawn_pool = AsyncMock()
    return pm


def _patch_defaults(monkeypatch: pytest.MonkeyPatch, spawn_type: str) -> None:
    """Production code calls
    ``PoolManager._resolve_auto_spawn_defaults`` on the class (not
    the instance), so patch the classmethod.
    """
    from mahavishnu.pools import manager

    monkeypatch.setattr(
        manager.PoolManager,
        "_resolve_auto_spawn_defaults",
        classmethod(
            lambda cls: {
                "spawn_type": spawn_type,
                "min_workers": 1,
                "max_workers": 3,
                "worker_type": "shepherd",
            }
        ),
    )


@pytest.mark.asyncio
async def test_bootstrap_skips_when_mahavishnu_pool_has_no_terminal_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``PoolManager.terminal_manager`` is None and the
    configured spawn type is ``mahavishnu``, ``pool_bootstrap`` must
    return ``status=skipped, reason=terminal_manager_unavailable``
    instead of attempting the spawn (which would hard-fail with a
    ``RuntimeError``).
    """
    _patch_defaults(monkeypatch, spawn_type="mahavishnu")
    mcp = _NoOpMcp()
    pm = _make_pool_manager(terminal_manager=None)
    register_pool_tools(mcp, pm)  # type: ignore[arg-type]
    bootstrap = mcp._registered["pool_bootstrap"]

    result = await bootstrap()

    assert result["status"] == "skipped"
    assert result["reason"] == "terminal_manager_unavailable"
    assert result["pools_active_before"] == 0
    assert result["pools_active_after"] == 0
    # Critical: the broken-spawn path must NOT be attempted.
    pm.spawn_pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_attempts_spawn_when_terminal_manager_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The skip gate is conditional — when ``terminal_manager`` IS
    set, ``pool_bootstrap`` must proceed with the spawn (the happy
    path).
    """
    _patch_defaults(monkeypatch, spawn_type="mahavishnu")
    mcp = _NoOpMcp()
    pm = _make_pool_manager(terminal_manager=MagicMock(name="tmux"))
    pm.spawn_pool = AsyncMock(return_value="pool_test_1")
    register_pool_tools(mcp, pm)  # type: ignore[arg-type]
    bootstrap = mcp._registered["pool_bootstrap"]

    result = await bootstrap()

    assert result["status"] == "spawned"
    assert result["pool_id"] == "pool_test_1"
    pm.spawn_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_skips_when_session_buddy_pool_uses_no_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For non-mahavishnu pool types (e.g. session-buddy),
    ``terminal_manager`` is irrelevant — the bootstrap must NOT
    skip just because ``terminal_manager`` is None. This guards
    against the skip-gate being too broad.
    """
    _patch_defaults(monkeypatch, spawn_type="session-buddy")
    mcp = _NoOpMcp()
    pm = _make_pool_manager(terminal_manager=None)
    pm.spawn_pool = AsyncMock(return_value="pool_sb_1")
    register_pool_tools(mcp, pm)  # type: ignore[arg-type]
    bootstrap = mcp._registered["pool_bootstrap"]

    result = await bootstrap()

    # session-buddy uses its own substrate; no terminal needed.
    # pool_bootstrap returns status="warning" for non-mahavishnu
    # pool types because substrate-fixed sizing emits a sizing
    # warning (mirrors pool_spawn's type-specific sizing path).
    assert result["status"] == "warning"
    pm.spawn_pool.assert_awaited_once()
