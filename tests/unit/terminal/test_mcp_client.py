"""Unit tests for mahavishnu.terminal.mcp_client.McpretentiousClient.

Regression tests pinning the launch command resolution through
``BUILTIN_BACKENDS``. After the 2026-08-12 mcpretentious removal, ``tmux``
is the only PTY builtin; these tests pin that the constructor still
delegates to the registry instead of hardcoding a launch command.
"""
from __future__ import annotations

import pytest

from mahavishnu.terminal.mcp_client import McpretentiousClient, StdioMCPClient


@pytest.mark.unit
class TestMcpretentiousClientLaunchesViaRegistry:
    """The default and explicit ``backend_name`` resolve through ``BUILTIN_BACKENDS``.

    These tests pin the launch command by inspecting the inner
    ``StdioMCPClient`` that ``McpretentiousClient`` constructs. The
    constructor is sync — ``start()`` runs the actual subprocess — so
    the assertion is on what ``StdioMCPClient`` is *constructed with*,
    not on ``create_subprocess_exec`` call args.
    """

    def test_default_backend_uses_tmux(self) -> None:
        """The default 'tmux' backend must be spawned via the tmux binary."""
        client = McpretentiousClient()
        inner = client._client  # type: ignore[attr-defined]

        assert isinstance(inner, StdioMCPClient)
        assert inner.command == "tmux"
        assert inner.args == []

    def test_explicit_backend_name_uses_registry(self) -> None:
        """Passing 'tmux' resolves through BUILTIN_BACKENDS, not hardcoded."""
        client = McpretentiousClient(backend_name="tmux")
        inner = client._client  # type: ignore[attr-defined]

        assert isinstance(inner, StdioMCPClient)
        assert inner.command == "tmux"
        assert inner.args == []

    def test_unknown_backend_name_raises_keyerror(self) -> None:
        """Asking for a backend that doesn't exist should fail loud, not silently."""
        with pytest.raises(KeyError) as exc_info:
            McpretentiousClient(backend_name="definitely-not-a-real-backend")
        # KeyError should mention the bad name for debuggability.
        assert "definitely-not-a-real-backend" in str(exc_info.value)
