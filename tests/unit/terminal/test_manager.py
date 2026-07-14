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
