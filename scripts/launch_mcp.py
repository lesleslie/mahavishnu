#!/usr/bin/env python3
"""Launch wrapper for the Mahavishnu MCP server (mcp-common launcher edition).

Phase 4a Task 4a.1 migration. Replaces launch_mcp_with_secrets.py:
- secrets parsing lives at mcp_common.server.launcher.load_secrets (REQ-002)
- secrets_path = ~/.config/secrets.env (same as before)
- os.execvp hop is GONE — the launcher's launch() calls FastMCP's run_async
  in-process; launchd sees a single long-running Python process.

2026-10-03 (lifespan refactor) — the previous ``_RunAsyncAdapter`` shim
that bypassed ``FastMCPServer.start()`` has been removed. The wrapper
now returns the ``FastMCPServer`` wrapper directly. Its
``run_async(transport=..., host=..., port=..., uvicorn_config=...)``
method satisfies the launcher's duck-typed contract and routes through
``start()`` so the full post-listener lifespan (signer feed, plan_index
rebuild, ``TaskOrphanSweeper`` spawn) actually runs. This closes the
circular dep that hid behind the bypass — see
``docs/specs/2026-10-04-mcp-lifespan-plan-index-init.md`` and the
2026-09-26 launcher-migration decision Trap #1 (now superseded) for
the historical context.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

# Venv bootstrap: the wrapper's shebang (`#!/usr/bin/env python3`) resolves to
# whatever python3 is in launchd's $PATH — typically Homebrew's system python
# (e.g. /usr/local/bin/python3 → /usr/local/Cellar/python@3.14/...). That python
# is the SAME binary as the venv's `.venv/bin/python` (both symlink to the same
# Homebrew cellar file), but the venv's site-packages aren't on sys.path unless
# Python was launched via the venv's binary. Fix: use `site.addsitedir` (NOT
# just `sys.path.insert`) so `.pth` files in the venv's site-packages get
# processed at runtime — `site.addsitedir` walks the directory and exec's any
# `.pth` it finds (e.g. `_editable_impl_mahavishnu.pth` adds the repo root to
# sys.path, which is where the editable `mahavishnu` package lives). A plain
# `sys.path.insert` misses these because Python's site initialization ran
# before our bootstrap prepend. Idempotent — no-op when the venv is already
# active (sys.prefix is already under `_REPO_ROOT/.venv`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_ROOT = _REPO_ROOT / ".venv"
_VENV_SITE_PACKAGES = (
    _VENV_ROOT
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
try:
    _VENV_SITE_PACKAGES.relative_to(Path(sys.prefix))
    _IN_VENV = True
except ValueError:
    _IN_VENV = False
if not _IN_VENV and _VENV_SITE_PACKAGES.is_dir():
    site.addsitedir(str(_VENV_SITE_PACKAGES))

import asyncio
import signal

from mcp_common.server import launch


def build_server():
    """Closure: returns the configured Mahavishnu MCP server. build_server() takes no args.

    ``FastMCPServer.run_async(transport="http", host=..., port=...,
    uvicorn_config=...)`` satisfies the launcher's duck-typed contract,
    so the wrapper can be returned directly — no adapter needed. The
    launcher-driven ``start()`` path runs the post-listener lifespan
    (init_signer_feed_state, plan_index rebuild, task_orphan_sweeper
    spawn) so the three /health feeds warm correctly instead of
    reporting permanent ``warming_up`` as they did under the previous
    bypass.
    """
    from mahavishnu.core.app import MahavishnuApp
    from mahavishnu.mcp.server_core import FastMCPServer

    maha_app = MahavishnuApp()
    return FastMCPServer(maha_app)


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
