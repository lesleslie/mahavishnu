"""Unit tests for ``mahavishnu.mcp.tools.eventbridge_tools``.

Mirrors the parallel tests in Crackerjack and Akosha. Verifies the
registration-time wiring and per-call re-read semantics of the
``enabled`` toggle.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mahavishnu.mcp.tools.eventbridge_tools import register_eventbridge_tools


pytestmark = pytest.mark.unit


def _capture_tool() -> Any:
    """Build a fake FastMCP app whose ``@app.tool()`` decorator captures the wrapped function."""
    captured: list[Any] = []

    def tool_decorator(*_args: Any, **_kwargs: Any) -> Any:
        def deco(func: Any) -> Any:
            captured.append(func)
            return func

        return deco

    app = MagicMock()
    app.tool = tool_decorator
    register_eventbridge_tools(app)
    assert len(captured) == 1
    return captured[0]


def _capture_tool_with(
    *,
    enabled: bool | None = None,
    enabled_fn: Any = None,
) -> Any:
    captured: list[Any] = []

    def tool_decorator(*_args: Any, **_kwargs: Any) -> Any:
        def deco(func: Any) -> Any:
            captured.append(func)
            return func

        return deco

    app = MagicMock()
    app.tool = tool_decorator
    kwargs: dict[str, Any] = {}
    if enabled is not None:
        kwargs["enabled"] = enabled
    if enabled_fn is not None:
        kwargs["enabled_fn"] = enabled_fn
    register_eventbridge_tools(app, **kwargs)
    assert len(captured) == 1
    return captured[0]


@pytest.mark.asyncio
async def test_publish_to_eventbridge_returns_disabled_when_toggle_false() -> None:
    publish = _capture_tool_with(enabled=False)
    result = await publish(topic="workflow.started", payload={"workflow_id": "w1"})
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_publish_to_eventbridge_returns_no_publisher_when_toggle_true_and_unwired() -> None:
    publish = _capture_tool_with(enabled=True)
    result = await publish(topic="workflow.started", payload={"workflow_id": "w1"})
    assert result.get("status") == "no_publisher"
    assert "warning" in result


@pytest.mark.asyncio
async def test_enabled_re_reads_each_call_when_enabled_fn_provided() -> None:
    """Per-call re-read: operators can flip the toggle without restart."""
    state = {"enabled": False}

    def my_enabled_fn() -> bool:
        return state["enabled"]

    publish = _capture_tool_with(enabled_fn=my_enabled_fn)

    result_1 = await publish(topic="workflow.started", payload={"workflow_id": "w1"})
    assert result_1 == {"status": "disabled"}

    state["enabled"] = True
    result_2 = await publish(topic="workflow.started", payload={"workflow_id": "w2"})
    assert result_2.get("status") == "no_publisher"
