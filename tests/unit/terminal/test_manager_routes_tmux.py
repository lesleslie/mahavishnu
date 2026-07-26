from __future__ import annotations

import pathlib

import pytest

from mahavishnu.terminal.config import TerminalSettings
from mahavishnu.terminal.manager import TerminalManager


class _FakeMcpretentiousAdapter:
    adapter_name = "tmux"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("tmux preference must not construct McpretentiousAdapter")


class _FakeDurableWorkerManager:
    def __init__(self, **_kwargs: object) -> None:
        self.store = None


@pytest.mark.asyncio
async def test_manager_routes_tmux_preference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """The tmux preference selects the durable terminal adapter."""
    monkeypatch.setattr(
        "mahavishnu.terminal.manager.McpretentiousAdapter",
        _FakeMcpretentiousAdapter,
    )
    monkeypatch.setattr(
        "mahavishnu.workers.contract.manager.DurableWorkerManager",
        _FakeDurableWorkerManager,
    )
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))

    config = type(
        "Config",
        (),
        {"terminal": TerminalSettings(enabled=True, adapter_preference="tmux")},
    )()

    manager = await TerminalManager.create(config, mcp_client=None)

    assert type(manager.adapter).__name__ == "TmuxTerminalAdapter"
    assert manager.adapter.adapter_name == "tmux"
