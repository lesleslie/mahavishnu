"""Unit tests for mahavishnu.terminal.manager.

Pins that the operator's ``terminal.adapter_preference`` is honored by the
factory method so any registered backend (not just the default) can be
selected via settings. These are wiring tests — they catch the regression
where the manager hardcoded its backend choice and ignored the
operator's preference.

The mcpretentious adapter was removed 2026-08-12 (see
``docs/followups/2026-08-12-mcpretentious-removed.md``). The only PTY
backends now are ``tmux`` (default) and ``crow`` (opt-in via
crow_enabled + Bodai-component HTTP MCP server) — see ``adapters/crow.py`` and ``mcp/crow_server.py``.
``crow_enabled: true``). These tests now cover the ``tmux`` / ``crow``
routing paths and the operator guidance surfaced when neither is
available.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.terminal.config import TerminalSettings
from mahavishnu.terminal.manager import TerminalManager


class TestManagerRoutesTmuxPreference:
    """``tmux`` is the default durable-worker terminal backend (Spec §9.4)."""

    @pytest.mark.asyncio
    async def test_tmux_preference_routes_to_tmux_adapter(self) -> None:
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="tmux")

        # The tmux branch imports ``TmuxTerminalAdapter`` lazily from
        # ``mahavishnu.terminal.adapters.tmux``. Patch the symbol at its
        # source module so the lazy import resolves to the mock.
        with patch(
            "mahavishnu.terminal.adapters.tmux.TmuxTerminalAdapter",
        ) as mock_adapter_cls:
            adapter_instance = MagicMock()
            adapter_instance.adapter_name = "tmux"
            mock_adapter_cls.return_value = adapter_instance

            manager = await TerminalManager.create(config, mcp_client=None)

        mock_adapter_cls.assert_called_once()
        assert manager.adapter.adapter_name == "tmux"


class TestManagerRoutesMockPreference:
    """``mock`` (and ``auto``) resolve to the always-available mock adapter."""

    @pytest.mark.asyncio
    async def test_mock_preference_constructs_mock_adapter(self) -> None:
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="mock")

        manager = await TerminalManager.create(config, mcp_client=None)

        assert manager.adapter.adapter_name == "mock"


class TestManagerCrowPreferenceRequiresFlag:
    """``crow`` only takes the bundled adapter path when ``crow_enabled`` is set."""

    @pytest.mark.asyncio
    async def test_crow_without_flag_falls_back_to_mock(self) -> None:
        config = MagicMock()
        # TerminalSettings defaults ``crow_enabled`` to False — pin it explicitly
        # so the test is robust against future default flips.
        config.terminal = TerminalSettings(
            adapter_preference="crow",
            crow_enabled=False,
        )

        manager = await TerminalManager.create(config, mcp_client=None)

        # Stock installs with ``adapter_preference='crow'`` no longer crash —
        # the manager falls back to the mock adapter (MHV-001 fix).
        assert manager.adapter.adapter_name == "mock"


class TestManagerUnknownPreferenceRaisesActionableError:
    """Unknown preferences surface a ConfigurationError naming the preference."""

    @pytest.mark.asyncio
    async def test_unknown_preference_raises_configuration_error(self) -> None:
        from mahavishnu.core.errors import ConfigurationError

        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="bogus")

        with pytest.raises(ConfigurationError) as exc_info:
            await TerminalManager.create(config, mcp_client=None)

        assert "bogus" in exc_info.value.message
        assert exc_info.value.details.get("adapter_preference") == "bogus"
