"""Unit tests for mahavishnu.mcp.tools.worker_contract_tools."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def test_launch_worker_calls_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = MagicMock()
    manager.spawn = MagicMock(
        return_value=MagicMock(worker_id="w-1", record=MagicMock(worker_id="w-1"))
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.launch_worker(
            prompt="do it",
            worker_type="terminal-claude",
            backend="claude_tui",
            command=["claude"],
        )
    )

    assert out["worker_id"] == "w-1"
    manager.spawn.assert_called_once()


def test_workflow_status_returns_record(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = MagicMock()
    manager.status = MagicMock(return_value=MagicMock(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))

    assert out["worker_id"] == "w-1"
    manager.status.assert_called_once_with("w-1")
