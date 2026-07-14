"""Unit tests for mahavishnu.terminal.manager.

Pins that the operator's ``terminal.adapter_preference`` is threaded through
to the underlying client constructor so that any registered backend
(not just the default) can be selected via settings.

These are wiring tests — they catch the regression where the manager
hardcoded its backend choice and ignored the operator's preference.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.terminal.config import TerminalSettings
from mahavishnu.terminal.manager import TerminalManager


class TestManagerPassesPreferenceToClient:
    """The manager must thread the operator's preference through to the client."""

    @pytest.mark.asyncio
    async def test_mcpretentious_preference_passes_name(self) -> None:
        """When preference='mcpretentious', the manager must construct
        ``McpretentiousAdapter`` with ``backend_name='mcpretentious'``."""
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="mcpretentious")

        mock_client = MagicMock()

        # Block ITERM2_AVAILABLE so the manager falls through to the
        # mcpretentious branch instead of the iTerm2 branch (test ordering
        # could otherwise let iTerm2 be picked on dev laptops).
        with patch(
            "mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE",
            False,
        ):
            with patch(
                "mahavishnu.terminal.manager.McpretentiousAdapter",
            ) as mock_adapter_cls:
                adapter_instance = MagicMock()
                adapter_instance.adapter_name = "mcpretentious"
                mock_adapter_cls.return_value = adapter_instance

                await TerminalManager.create(config, mcp_client=mock_client)

        mock_adapter_cls.assert_called_once()
        call_kwargs = mock_adapter_cls.call_args.kwargs
        assert call_kwargs.get("backend_name") == "mcpretentious", (
            f"Expected backend_name='mcpretentious' in {call_kwargs!r}. "
            "The operator's adapter_preference must flow through to the client "
            "so any registered backend (not just the hardcoded default) can "
            "be selected via settings."
        )


class TestManagerAcceptsBuiltinBackend:
    """``mcpretentious`` is the sole BUILTIN_BACKENDS entry — the manager must
    route it through ``McpretentiousAdapter`` (and pass the name through).

    When the second backend (``pty_mcp_python``) was dropped (commit
    dropping it) the parametrize lists collapsed to a single value. If
    another built-in is added later, restore the parametrize here.
    """

    preference: str = "mcpretentious"

    @pytest.mark.asyncio
    async def test_builtin_backend_preference_routes_to_mcpretentious(self) -> None:
        """When preference is any BUILTIN_BACKENDS name, the manager must
        construct ``McpretentiousAdapter`` with ``backend_name=<preference>``."""
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference=self.preference)

        mock_client = MagicMock()

        # Block ITERM2_AVAILABLE so the manager falls through to the
        # mcpretentious branch instead of the iTerm2 branch (test ordering
        # could otherwise let iTerm2 be picked on dev laptops).
        with patch(
            "mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE",
            False,
        ):
            with patch(
                "mahavishnu.terminal.manager.McpretentiousAdapter",
            ) as mock_adapter_cls:
                adapter_instance = MagicMock()
                adapter_instance.adapter_name = self.preference
                mock_adapter_cls.return_value = adapter_instance

                await TerminalManager.create(config, mcp_client=mock_client)

        mock_adapter_cls.assert_called_once()
        call_kwargs = mock_adapter_cls.call_args.kwargs
        assert call_kwargs.get("backend_name") == self.preference, (
            f"Expected backend_name={self.preference!r} in {call_kwargs!r}. "
            "The BUILTIN_BACKENDS name must route through McpretentiousAdapter "
            "with the operator's preference threaded into backend_name."
        )


class TestManagerBuiltinBackendRequiresMcpClient:
    """Both code paths must agree on the mcp_client contract.

    The MCP boot path (mcp/server_core.py) always constructs an
    ``McpretentiousMCPClient`` before any adapter selection happens, so a
    BUILTIN_BACKENDS preference implicitly gets a working client. The direct
    ``TerminalManager.create(config, mcp_client=None)`` path historically fell
    through to the misleading ``"No suitable terminal adapter found"``
    ConfigurationError, masking the real cause. The two paths must agree:
    both succeed when an mcp_client is supplied, both refuse (with an
    actionable message) when one is not.
    """

    @pytest.mark.asyncio
    async def test_create_without_mcp_client_raises_actionable_error(self) -> None:
        """Direct Manager.create with mcp_client=None must raise a clear error.

        Previously this fell through to the misleading
        ``"No suitable terminal adapter found"`` ConfigurationError. The fix
        raises an early ConfigurationError that names the preference and
        points the operator at non-PTY adapters (``mock`` / ``iterm2`` /
        ``crow`` / ``auto``).
        """
        from mahavishnu.core.errors import ConfigurationError

        preference = "mcpretentious"
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference=preference)

        with patch(
            "mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE",
            False,
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                await TerminalManager.create(config, mcp_client=None)

        message = exc_info.value.message
        assert preference in message
        assert "mcp_client" in message
        # Operator guidance should mention the non-PTY fallbacks.
        assert "mock" in message
        # The error details should name the preference and the available PTY set
        # so downstream tooling can introspect the rejection.
        assert exc_info.value.details.get("adapter_preference") == preference
        assert "mcpretentious" in exc_info.value.details.get("available_pty_backends", [])
