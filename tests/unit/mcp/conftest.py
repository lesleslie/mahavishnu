"""Conftest for mcp tool unit tests.

Ensures the real ``mcp`` package (and ``mcp.types``) is always present in
``sys.modules`` before each test in this directory runs.

Background: in certain test orderings, an earlier test installs a minimal stub
``mcp`` into ``sys.modules`` via monkeypatch.  When the stub lacks a real
``mcp.types`` submodule, ``fastmcp.server.context`` fails on
``import mcp.types``, causing
``ImportError: FastMCP server support is not installed``.

Fix: before each test, verify ``mcp.types`` is available. If not, evict the
stub ``mcp`` (and any partially-cached ``fastmcp.server`` modules) so that
the next import re-discovers the real package from the filesystem.
"""

from __future__ import annotations

import sys


def _restore_real_mcp() -> None:
    """Replace any stub ``mcp`` in sys.modules with the real package."""
    mcp_types_missing = "mcp.types" not in sys.modules

    if mcp_types_missing:
        # Evict any stub or partial mcp modules
        for key in list(sys.modules.keys()):
            if key == "mcp" or key.startswith("mcp.") or key.startswith("fastmcp.server"):
                del sys.modules[key]

        try:
            import mcp  # noqa: F401
            import mcp.types  # noqa: F401
        except ImportError:
            pass  # unavailable; individual tests will fail naturally


# Run once at conftest import time (helps when not using xdist)
_restore_real_mcp()


def pytest_runtest_setup(item) -> None:  # type: ignore[no-untyped-def]
    """Restore the real mcp package before each test."""
    _restore_real_mcp()
