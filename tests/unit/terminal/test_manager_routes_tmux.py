from __future__ import annotations

import pathlib

import pytest

from mahavishnu.terminal.config import TerminalSettings
from mahavishnu.terminal.manager import TerminalManager


class _FakeTmuxTerminalAdapter:
    """Stand-in for the real TmuxTerminalAdapter."""

    adapter_name = "tmux"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        # Track that the durable-worker manager was wired through.
        self.durable_worker_manager = _kwargs.get("durable_worker_manager")


class _FakeDurableWorkerManager:
    def __init__(self, **_kwargs: object) -> None:
        self.store = None


@pytest.mark.asyncio
async def test_manager_routes_tmux_preference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """The tmux preference selects the durable terminal adapter."""
    # The tmux branch imports ``TmuxTerminalAdapter`` lazily from
    # ``mahavishnu.terminal.adapters.tmux``. Patch the symbol at its source
    # module so the lazy import resolves to the fake.
    monkeypatch.setattr(
        "mahavishnu.terminal.adapters.tmux.TmuxTerminalAdapter",
        _FakeTmuxTerminalAdapter,
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

    assert type(manager.adapter).__name__ == "_FakeTmuxTerminalAdapter"
    assert manager.adapter.adapter_name == "tmux"
