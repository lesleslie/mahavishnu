"""Regression tests for MCP-bootstrap terminal adapter selection.

Root cause under test: ``mahavishnu.mcp.bootstrap.init_terminal_manager``
read ``terminal.adapter_preference`` into a local, compared it only against
``"iterm2"``, and then assigned ``MockTerminalAdapter()`` on *both* branches.
Every MCP server boot therefore ran pools against the mock adapter regardless
of configuration, so ``pool_execute`` hung until timeout waiting for a
completion marker the mock never emits.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import TYPE_CHECKING

from mahavishnu.mcp import bootstrap
from mahavishnu.terminal.config import TerminalSettings

if TYPE_CHECKING:
    import pytest


class _FakeTmuxTerminalAdapter:
    """Stand-in for the real TmuxTerminalAdapter (avoids touching ~/.mahavishnu)."""

    adapter_name = "tmux"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


class _FakeDurableWorkerManager:
    def __init__(self, **_kwargs: object) -> None:
        self.store = None


def _server_with_preference(preference: str) -> SimpleNamespace:
    """Build the minimal FastMCPServer surface ``init_terminal_manager`` touches."""
    return SimpleNamespace(
        app=SimpleNamespace(
            config=SimpleNamespace(
                terminal=TerminalSettings(enabled=True, adapter_preference=preference),
            ),
        ),
        mcp_client=None,
    )


def test_tmux_preference_does_not_silently_fall_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """adapter_preference='tmux' must yield the tmux adapter, not the mock.

    This is the regression that made pools no-ops: the mock adapter returns
    canned output that never contains the completion marker
    ``GenericShellWorker._monitor_completion`` polls for.
    """
    monkeypatch.setattr(
        "mahavishnu.terminal.adapters.tmux.TmuxTerminalAdapter",
        _FakeTmuxTerminalAdapter,
    )
    monkeypatch.setattr(
        "mahavishnu.workers.contract.manager.DurableWorkerManager",
        _FakeDurableWorkerManager,
    )
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))

    manager = bootstrap.init_terminal_manager(_server_with_preference("tmux"))

    assert manager is not None, "terminal manager must initialize for tmux preference"
    assert manager.adapter.adapter_name == "tmux", (
        f"expected tmux adapter, got {manager.adapter.adapter_name!r} "
        "- bootstrap is discarding adapter_preference"
    )


def test_mock_preference_still_yields_mock(tmp_path: pathlib.Path) -> None:
    """An explicit mock preference must keep working (no behavior change)."""
    manager = bootstrap.init_terminal_manager(_server_with_preference("mock"))

    assert manager is not None
    assert manager.adapter.adapter_name == "mock"
