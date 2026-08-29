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
    """Ensure the module-level shared client + session dict are clean."""
    saved_client = terminal_proxy._client
    saved_state = terminal_proxy._state
    saved_sessions = dict(terminal_proxy._sessions)
    terminal_proxy._client = None
    terminal_proxy._state = None
    terminal_proxy._sessions.clear()
    try:
        yield
    finally:
        terminal_proxy._client = saved_client
        terminal_proxy._state = saved_state
        terminal_proxy._sessions.clear()
        terminal_proxy._sessions.update(saved_sessions)


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


def test_init_is_idempotent_when_client_already_live(reset_crow_state):
    """If the shared client is already live, ``init_crow_stdio_client`` is a
    no-op (does not raise) and leaves the existing client intact.

    The 2026-08-29 raw-JSON-RPC redesign made init idempotent because
    FastMCP's lifespan and any other entry point may both call
    ``init_crow_stdio_client``; rejecting a duplicate would deadlock the
    server. The legacy ``_state`` flag IS refreshed so old readers that
    check it still see init as having run.
    """
    import asyncio

    fake_client = MagicMock()
    terminal_proxy._client = fake_client
    settings = CrowSettings(workspace_root=Path("/tmp"))
    # Must not raise.
    asyncio.run(terminal_proxy.init_crow_stdio_client(settings))
    # Existing client preserved.
    assert terminal_proxy._client is fake_client
    # Legacy state flag refreshed.
    assert terminal_proxy._state is not None


def test_get_crow_session_returns_client_after_init(reset_crow_state):
    """Inject a fake client directly and verify the accessor returns it."""
    fake_client = MagicMock()
    terminal_proxy._client = fake_client
    assert terminal_proxy.get_crow_session() is fake_client


# ---- TerminalManager crow case ---------------------------------------------


def test_terminal_manager_crow_requires_mcp_client(tmp_path):
    """Without mcp_client, TerminalManager.create must refuse crow.

    The crow adapter path is opt-in: requires both
    `adapter_preference = "crow"` AND `crow_enabled = True`. With
    crow_enabled=False, the manager falls through to the mock adapter
    (no error). The "refuse without mcp_client" check only fires
    when crow_enabled=True.
    """
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.errors import ConfigurationError
    from mahavishnu.terminal.manager import TerminalManager

    config = MahavishnuSettings()
    config.terminal.adapter_preference = "crow"
    config.terminal.crow_enabled = True
    with pytest.raises(ConfigurationError, match="crow"):
        # use asyncio.run since create is async
        import asyncio

        asyncio.run(TerminalManager.create(config, mcp_client=None))


def test_terminal_manager_crow_creates_crow_adapter(tmp_path):
    """With mcp_client supplied AND crow_enabled=True,
    TerminalManager.create wires CrowTerminalAdapter."""
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
    from mahavishnu.terminal.manager import TerminalManager

    config = MahavishnuSettings()
    config.terminal.adapter_preference = "crow"
    config.terminal.crow_enabled = True
    mock_client = MagicMock()
    import asyncio

    manager = asyncio.run(TerminalManager.create(config, mcp_client=mock_client))
    assert isinstance(manager.adapter, CrowTerminalAdapter)
