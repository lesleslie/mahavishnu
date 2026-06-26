"""Regression test asserting FastMCP >= 3.4 across the Bodai ecosystem.

Plan 7 Phase 2 pins every Bodai core repo to FastMCP 3.4+. A downgrade
would silently break public-API consumers that depend on FastMCP 3.x
features (kwarg-only ``lifespan=``, public ``await server.get_tools()``,
``on_message`` middleware hook, ``transport=`` kwarg on ``run()``).

This guard test reads the pin from ``pyproject.toml`` and the installed
runtime version; both must report ``>= 3.4``.
"""

from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path

import pytest


def _read_pyproject_pin() -> str:
    """Return the fastmcp pin string from the repo pyproject.toml."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r"^\s*\"fastmcp([=<>~!]+)([^\"]+)\"", text, re.MULTILINE)
    if match is None:
        pytest.fail(f"No fastmcp pin found in {pyproject}")
    return match.group(2).strip()


def _parse_minimum(pin: str) -> tuple[int, int]:
    """Return (major, minor) from a pin string like '>=3.4.0,<4'."""
    first = pin.split(",")[0].strip()
    # strip leading operators
    cleaned = re.sub(r"^[>=<~!]+", "", first)
    parts = cleaned.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return major, minor


class TestFastMCPVersion:
    """Pin + installed version must both be >= 3.4 and the pin must have
    a hard upper bound to prevent surprise 4.0 breakages."""

    def test_pyproject_pin_is_at_least_3_4(self) -> None:
        """pyproject.toml pin must require fastmcp >= 3.4.0,<4."""
        pin = _read_pyproject_pin()
        major, minor = _parse_minimum(pin)
        assert (major, minor) >= (3, 4), (
            f"fastmcp pin '{pin}' resolves to {major}.{minor}; "
            "Plan 7 requires >= 3.4.0,<4"
        )

    def test_pyproject_pin_has_upper_bound(self) -> None:
        """pyproject.toml pin must include an upper bound (e.g. ,<4)
        to lock to the FastMCP 3.x major. Plan 7 explicitly forbids
        a bare ``>=3.4.0`` because that allows a surprise 4.0 upgrade.
        """
        pin = _read_pyproject_pin()
        upper_clauses = [c.strip() for c in pin.split(",") if c.strip().startswith("<")]
        assert upper_clauses, (
            f"fastmcp pin '{pin}' has no upper bound; "
            "Plan 7 requires an explicit upper bound (e.g. ,<4)"
        )

    def test_installed_runtime_is_at_least_3_4(self) -> None:
        """Installed fastmcp package version must satisfy >= 3.4."""
        installed = version("fastmcp")
        # Parse "3.4.2" or "3.5.0a1" etc. into (major, minor).
        match = re.match(r"^(\d+)\.(\d+)", installed)
        if match is None:
            pytest.fail(f"Unparsable fastmcp.__version__: {installed!r}")
        major = int(match.group(1))
        minor = int(match.group(2))
        assert (major, minor) >= (3, 4), (
            f"Installed fastmcp is {installed}; Plan 7 requires >= 3.4"
        )

    def test_mcp_common_reexports_fastmcp_symbols(self) -> None:
        """mcp_common.fastmcp must re-export FastMCP, Context, Middleware."""
        # Force the source-tree copy of mcp-common to win over any
        # stale site-packages copy. The Phase 1 re-export module
        # ``mcp_common.fastmcp`` is new and may be shadowed otherwise.
        import sys
        from pathlib import Path

        src = Path("/Users/les/Projects/mcp-common")
        assert src.is_dir(), f"mcp-common source tree not found at {src}"
        src_str = str(src)
        if sys.path[0] != src_str:
            sys.path.insert(0, src_str)
        # Drop a stale cached mcp_common so we re-import from source.
        for name in list(sys.modules):
            if name == "mcp_common" or name.startswith("mcp_common."):
                del sys.modules[name]

        from mcp_common.fastmcp import (  # noqa: F401
            Context,
            FastMCP,
            Middleware,
            MiddlewareContext,
            OneiricMCPConfig,
            RateLimitingMiddleware,
        )
        # All imports succeeded; assert FastMCP class is the upstream class.
        import fastmcp

        assert FastMCP is fastmcp.FastMCP
        assert Context is fastmcp.Context