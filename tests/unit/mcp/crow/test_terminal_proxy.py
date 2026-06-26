"""Tests for mahavishnu.mcp.crow.terminal_proxy — stdio subprocess to crow-mcp.

RED phase: tests written before implementation.

Per plan Task 4 (this task) the focus is the integration point that
proxies terminal calls through to crow-mcp stdio. The heavy lifting
(`_CrowState` dataclass, atomic publish, AsyncExitStack lifecycle) is
Task 9 in the plan. For Task 4 we test only the basic guard rails:

1. ``get_crow_session()`` raises when no session has been initialised.
2. ``init_crow_stdio_client`` rejects re-entry while a session is live.
3. ``close_crow_stdio_client`` is idempotent and safe to call when no
   session is active.
4. TerminalManager.create wires the crow adapter when adapter_preference
   is "crow" and an mcp_client is supplied.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mahavishnu.mcp.crow import terminal_proxy
from mahavishnu.mcp.crow.settings import CrowSettings


@pytest.fixture
def reset_crow_state():
    """Ensure the module-level session state is clean before/after."""
    saved = terminal_proxy._state
    terminal_proxy._state = None
    try:
        yield
    finally:
        terminal_proxy._state = saved


def test_get_crow_session_raises_before_init(reset_crow_state):
    with pytest.raises(RuntimeError, match="not initialized"):
        terminal_proxy.get_crow_session()


def test_close_is_idempotent_when_no_session(reset_crow_state):
    """Calling close without prior init must be safe."""
    import asyncio

    asyncio.run(terminal_proxy.close_crow_stdio_client())
    # Second call also safe
    asyncio.run(terminal_proxy.close_crow_stdio_client())
    assert terminal_proxy._state is None


def test_init_rejects_double_init(reset_crow_state):
    """If a session is already initialised, init must reject rather than
    silently overwriting state (which would leak the previous subprocess)."""
    import asyncio

    fake_state = MagicMock()
    fake_state.session = MagicMock()
    fake_state.exit_stack = MagicMock()
    terminal_proxy._state = fake_state
    settings = CrowSettings(workspace_root=Path("/tmp"))
    with pytest.raises(RuntimeError, match="already initialized"):
        asyncio.run(terminal_proxy.init_crow_stdio_client(settings))


def test_get_crow_session_returns_session_after_init(reset_crow_state):
    """Inject a fake state directly and verify the accessor returns the session."""
    fake_session = MagicMock()
    fake_state = MagicMock()
    fake_state.session = fake_session
    terminal_proxy._state = fake_state
    assert terminal_proxy.get_crow_session() is fake_session


# ---- TerminalManager crow case ---------------------------------------------


def test_terminal_manager_crow_requires_mcp_client(tmp_path):
    """Without mcp_client, TerminalManager.create must refuse crow."""
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.errors import ConfigurationError
    from mahavishnu.terminal.manager import TerminalManager

    config = MahavishnuSettings()
    config.terminal.adapter_preference = "crow"
    with pytest.raises(ConfigurationError, match="crow"):
        # use asyncio.run since create is async
        import asyncio

        asyncio.run(TerminalManager.create(config, mcp_client=None))


def test_terminal_manager_crow_creates_crow_adapter(tmp_path):
    """With mcp_client supplied, TerminalManager.create wires CrowTerminalAdapter."""
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
    from mahavishnu.terminal.manager import TerminalManager

    config = MahavishnuSettings()
    config.terminal.adapter_preference = "crow"
    mock_client = MagicMock()
    import asyncio

    manager = asyncio.run(TerminalManager.create(config, mcp_client=mock_client))
    assert isinstance(manager.adapter, CrowTerminalAdapter)