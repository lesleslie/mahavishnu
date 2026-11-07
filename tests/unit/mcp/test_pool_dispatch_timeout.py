"""Pin the ``timeout`` plumbing on ``pool_route_execute`` / ``_dispatch_internal``.

The worker reads its own execute timeout from ``task["timeout"]``. The
callers' ``timeout`` argument was accepted by ``pool_route_execute`` but
never reached the task dict, so every dispatch ran against the worker's
default (300s) regardless of the requested budget. A long task was
killed mid-flight while the caller believed it had been given a larger
timeout.

These tests pin that the value now flows through.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools.pool_tools import _dispatch_internal

pytestmark = pytest.mark.unit


def _capture_pool_route_execute(mock_pool_manager: MagicMock):
    """Capture the registered ``pool_route_execute`` callable.

    The tool is exposed through ``@mcp.tool()``, so a stubbed decorator
    captures the real function for direct invocation.
    """
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    captured: dict[str, Any] = {}

    def registering_decorator(func=None):
        if func is None:
            return lambda wrapped: registering_decorator(wrapped)
        captured[func.__name__] = func
        return func

    mcp = MagicMock()
    mcp.tool = registering_decorator
    register_pool_tools(mcp, mock_pool_manager)
    return captured["pool_route_execute"]


class _RecordingPoolManager:
    """Pool manager double that records the task dict it was handed."""

    def __init__(self) -> None:
        self.task: dict[str, Any] | None = None

    async def route_task(
        self, *, task: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        self.task = task
        return {"status": "success"}


class TestDispatchInternalTimeout:
    """The timeout must reach the task dict the worker consumes."""

    @pytest.mark.asyncio
    async def test_timeout_is_forwarded_into_task(self) -> None:
        """An explicit timeout lands in ``task["timeout"]``."""
        manager = _RecordingPoolManager()

        await _dispatch_internal(
            prompt="do the thing",
            pool_selector=MagicMock(),
            execution_id="exec-1",
            pool_affinity=None,
            coerced_kind=None,
            parent_session_id=None,
            auto_spawn=False,
            pool_manager=manager,
            timeout=1800,
        )

        assert manager.task is not None
        assert manager.task["timeout"] == 1800

    @pytest.mark.asyncio
    async def test_timeout_omitted_when_none(self) -> None:
        """No timeout means no key -- the worker applies its own default."""
        manager = _RecordingPoolManager()

        await _dispatch_internal(
            prompt="do the thing",
            pool_selector=MagicMock(),
            execution_id="exec-2",
            pool_affinity=None,
            coerced_kind=None,
            parent_session_id=None,
            auto_spawn=False,
            pool_manager=manager,
        )

        assert manager.task is not None
        assert "timeout" not in manager.task

    @pytest.mark.asyncio
    async def test_prompt_is_always_present(self) -> None:
        """The prompt survives alongside the timeout."""
        manager = _RecordingPoolManager()

        await _dispatch_internal(
            prompt="the prompt body",
            pool_selector=MagicMock(),
            execution_id="exec-3",
            pool_affinity=None,
            coerced_kind=None,
            parent_session_id=None,
            auto_spawn=False,
            pool_manager=manager,
            timeout=600,
        )

        assert manager.task is not None
        assert manager.task["prompt"] == "the prompt body"
        assert manager.task["timeout"] == 600


class TestRouteExecuteForwardsTimeout:
    """``pool_route_execute`` must hand its timeout to the dispatch helper."""

    @pytest.mark.asyncio
    async def test_route_execute_forwards_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The public tool forwards ``timeout`` to ``_dispatch_internal``."""
        from mahavishnu.mcp.tools import pool_tools

        captured: dict[str, Any] = {}

        async def _fake_dispatch(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"status": "success", "result": "ok"}

        monkeypatch.setattr(pool_tools, "_dispatch_internal", _fake_dispatch)

        pool_route_execute = _capture_pool_route_execute(MagicMock())

        await pool_route_execute(
            prompt="do the thing",
            pool_selector="least_loaded",
            timeout=1800,
        )

        assert captured["timeout"] == 1800
