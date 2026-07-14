"""Integration smoke test for the mcpretentious backend.

Gated by MCPRETENTIOUS_INTEGRATION=1. Skipped otherwise. This is the only
test that actually spawns a real MCPretentious subprocess and exercises
its tool surface; everything else is unit-level with mocks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest

# Skip the whole module unless both the env var is set AND the prerequisites
# are present on PATH. This makes the test safe to run in any environment.
INTEGRATION_ENABLED = bool(os.environ.get("MCPRETENTIOUS_INTEGRATION"))
NODE_AVAILABLE = shutil.which("node") is not None
NPM_AVAILABLE = shutil.which("npm") is not None
SKIP_REASON = "Set MCPRETENTIOUS_INTEGRATION=1 with node and npm on PATH to run."


@unittest.skipUnless(INTEGRATION_ENABLED and NODE_AVAILABLE and NPM_AVAILABLE, SKIP_REASON)
class TestMcpretentiousSmoke(unittest.IsolatedAsyncioTestCase):
    """End-to-end smoke against a real MCPretentious subprocess."""

    async def test_session_open_type_read_close(self) -> None:
        """Open a session, send 'echo hello', read the output, close."""
        from mahavishnu.terminal.mcp_client import McpretentiousClient

        # Pre-flight: confirm npm has mcpretentious installable.
        result = subprocess.run(
            ["npm", "list", "-g", "mcpretentious"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest("mcpretentious not installed globally; run: npm install -g mcpretentious")

        # Spawn the client.
        client = McpretentiousClient(backend_name="mcpretentious")
        await client._client.start()  # type: ignore[attr-defined]

        try:
            # Open a session.
            session_id = await client._client.call_tool(  # type: ignore[attr-defined]
                "mcpretentious-open",
                {"columns": 120, "rows": 40},
            )
            self.assertIsNotNone(session_id)

            try:
                # Send a command and read the output.
                await client._client.call_tool(  # type: ignore[attr-defined]
                    "mcpretentious-type",
                    {"terminal_id": session_id, "input": ["echo hello", "enter"]},
                )
                # Read may take a moment; allow some time.
                output = await client._client.call_tool(  # type: ignore[attr-defined]
                    "mcpretentious-read",
                    {"terminal_id": session_id, "limit_lines": 50},
                )
                self.assertIn("hello", str(output))
            finally:
                # Always close, even on failure.
                try:
                    await client._client.call_tool(  # type: ignore[attr-defined]
                        "mcpretentious-close",
                        {"terminal_id": session_id},
                    )
                except Exception:
                    pass
        finally:
            # Stop the client subprocess.
            try:
                await client._client.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
