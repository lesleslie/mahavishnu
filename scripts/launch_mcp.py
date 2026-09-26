#!/usr/bin/env python3
"""Launch wrapper for the Mahavishnu MCP server (mcp-common launcher edition).

Phase 4a Task 4a.1 migration. Replaces launch_mcp_with_secrets.py:
- secrets parsing lives at mcp_common.server.launcher.load_secrets (REQ-002)
- secrets_path = ~/.config/secrets.env (same as before)
- os.execvp hop is GONE — the launcher's launch() calls FastMCP's run_async
  in-process; launchd sees a single long-running Python process.

Bridge: the launcher duck-types on `run_async(transport="http", host=, port=,
uvicorn_config=)`. FastMCPServer exposes `start(host, port)` and the inner
FastMCP exposes `run_http_async(...)` — neither matches. The _RunAsyncAdapter
below wraps FastMCPServer so the launcher can drive it. See
.claude/decisions/2026-09-26-mcp-launcher-migration.md §4 trap #1.
"""
from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from mcp_common.server import launch


class _RunAsyncAdapter:
    """Adapt FastMCPServer to the launcher's duck-typed run_async(transport=, ...) contract."""

    def __init__(self, mhv_server) -> None:
        self._server = mhv_server

    async def run_async(self, *, transport, host, port, uvicorn_config):
        # FastMCPServer.start() runs the full lifecycle (tool profile, feed warm,
        # run_http_async). It honors its own uvicorn_config but ignores the
        # launcher-passed one. We call the inner FastMCP directly so the
        # launcher's timeout_graceful_shutdown (REQ-007) actually wins.
        await self._server.server.run_http_async(
            host=host, port=port, uvicorn_config=uvicorn_config,
        )


def build_server():
    """Closure: returns the configured Mahavishnu MCP server. build_server() takes no args."""
    from mahavishnu.core.app import MahavishnuApp
    from mahavishnu.mcp.server_core import FastMCPServer

    maha_app = MahavishnuApp()
    mhv_server = FastMCPServer(maha_app)
    return _RunAsyncAdapter(mhv_server)


def main() -> int:
    # REQ-014 — explicit SIGTERM handler so the wrapper exits 0 (not -15) on
    # cooperative shutdown. See launcher-cookbook.md "Failure modes" row for
    # why this is load-bearing for incident-response scripts.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    asyncio.run(
        launch(
            build_server=build_server,
            component_name="mahavishnu",
            # secrets_path matches DEFAULT_SECRETS_PATH in mcp_common.server.launcher
            # (Path.home() / ".config" / "secrets.env"). Passed explicitly so the
            # intent is visible; do NOT use Path("~/.config/secrets.env") here —
            # pathlib does not expand "~" in .exists() and load_secrets would
            # silently no-op.
            secrets_path=Path.home() / ".config" / "secrets.env",
            # No settings_path — mahavishnu uses settings/mahavishnu.yaml but
            # the launcher-warmed `settings` feed is for the generic
            # HealthFeedState ("entities_count > 0"). Mahavishnu's /health
            # reports skills_signer + plan_index, not `settings`, so warming
            # a `settings` feed here would be a no-op for the visible body.
            host="127.0.0.1",
            port=8680,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())