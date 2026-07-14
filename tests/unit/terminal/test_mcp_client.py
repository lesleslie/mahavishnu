"""Unit tests for mahavishnu.terminal.mcp_client.McpretentiousClient.

Regression tests pinning the launch command so a future regression to 'uvx'
on the npm-based mcpretentious package would be caught immediately.
"""
from __future__ import annotations

import pytest

from mahavishnu.terminal.mcp_client import McpretentiousClient, StdioMCPClient


@pytest.mark.unit
class TestMcpretentiousClientLaunchesViaRegistry:
    """The original bug was using 'uvx' for an npm package.

    These tests pin the launch command by inspecting the inner
    ``StdioMCPClient`` that ``McpretentiousClient`` constructs. The
    constructor is sync — ``start()`` runs the actual subprocess — so
    the assertion is on what ``StdioMCPClient`` is *constructed with*,
    not on ``create_subprocess_exec`` call args.
    """

    def test_default_backend_uses_npx_not_uvx(self) -> None:
        """The default 'mcpretentious' backend must be spawned via npx, not uvx."""
        client = McpretentiousClient()
        inner = client._client  # type: ignore[attr-defined]

        assert isinstance(inner, StdioMCPClient)
        assert inner.command == "npx", (
            f"Expected npx for npm package, got {inner.command!r}. "
            "This is the original 'uvx on npm' regression."
        )
        assert inner.args == ["mcpretentious"]

    def test_explicit_backend_name_uses_registry(self) -> None:
        """Passing a name resolves through BUILTIN_BACKENDS, not hardcoded."""
        client = McpretentiousClient(backend_name="mcpretentious")
        inner = client._client  # type: ignore[attr-defined]

        assert isinstance(inner, StdioMCPClient)
        assert inner.command == "npx"
        assert inner.args == ["mcpretentious"]

    def test_unknown_backend_name_raises_keyerror(self) -> None:
        """Asking for a backend that doesn't exist should fail loud, not silently."""
        with pytest.raises(KeyError) as exc_info:
            McpretentiousClient(backend_name="definitely-not-a-real-backend")
        # KeyError should mention the bad name for debuggability.
        assert "definitely-not-a-real-backend" in str(exc_info.value)
