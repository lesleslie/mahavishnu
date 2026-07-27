"""Tests for iTerm2 adapter deprecation and removal."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from mahavishnu.terminal.adapters.mock import MockTerminalAdapter

pytestmark = pytest.mark.unit


@pytest.fixture
def cfg() -> MagicMock:
    config = MagicMock()
    terminal = config.terminal
    terminal.enabled = True
    terminal.adapter_preference = "iterm2"
    terminal.max_concurrent_sessions = 5
    terminal.default_columns = 120
    terminal.default_rows = 30
    terminal.crow_enabled = False
    terminal.crow_http_host = "127.0.0.1"
    terminal.crow_http_port = 8675
    return config


async def test_iterm2_preference_emits_deprecation_and_falls_back_to_mock(
    cfg: MagicMock,
) -> None:
    from mahavishnu.terminal.manager import TerminalManager

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        manager = await TerminalManager.create(cfg, mcp_client=None)

    assert any(issubclass(item.category, DeprecationWarning) for item in caught)
    assert isinstance(manager.adapter, MockTerminalAdapter)
    assert manager.adapter.adapter_name == "mock"
