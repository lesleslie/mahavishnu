# tests/unit/conftest.py
"""Unit-test-only conftest: mock missing mcp_common.types before any test runs."""

from __future__ import annotations

import os
import sys
from types import ModuleType

# Disable beartype's meta-path import hook before any `import beartype`.
# See `docs/followups/2026-09-05-beartype-coverage-pytest-cov-py3.14.md`
# for the race-condition analysis. Setting the env var here (pytest
# collection time) avoids the `claw_state` partial-initialization
# ImportError that otherwise surfaces on the *second* pytest-cov run
# in a venv. Beartype's runtime type-checking still operates via
# decorators on explicitly-decorated callables; only the import-time
# hook installation is suppressed, which does not affect code that
# never imports beartype directly (Mahavishnu itself does not).
os.environ.setdefault("BEARTYPE_DISABLE_CLI_HOOKS", "1")


def _ensure_mcp_common_types() -> None:
    """Satisfy imports of `from mcp_common.types import Field`.

    The real ``mcp_common`` package (from ``mcp-common`` repo) does not
    expose a ``types`` submodule; ``Field`` is simply ``pydantic.Field``.
    We inject a shim so that modules that import from ``mcp_common.types``
    load correctly in the test environment.
    """
    if "mcp_common.types" in sys.modules:
        return

    # Create a module that re-exports pydantic.Field as mcp_common.types.Field
    import pydantic

    types_mod = ModuleType("mcp_common.types")
    types_mod.Field = pydantic.Field
    sys.modules["mcp_common.types"] = types_mod


def _ensure_mcp_error_compat() -> None:
    """Alias MCPError -> McpError in mcp.shared.exceptions.

    Upstream ``mcp`` renamed ``MCPError`` to ``McpError``; ``agno``'s
    ``agno.utils.mcp`` still imports the old name. Without this shim,
    ``import agno.tools.mcp`` raises ImportError, which (because
    agno.tools exposes ``mcp`` only as a lazy submodule) surfaces to
    tests as ``AttributeError: module 'agno.tools' has no attribute
    'mcp'`` whenever they do ``patch("agno.tools.mcp.MCPTools")``.

    We force-load ``mcp.shared.exceptions`` and re-export ``McpError``
    under the legacy name so agno's import chain resolves.
    """
    # Make sure mcp.shared.exceptions has been loaded by importing it
    import mcp.shared.exceptions as exc  # noqa: F401

    if hasattr(sys.modules.get("mcp.shared.exceptions", exc), "MCPError"):
        return

    exc_mod = sys.modules.get("mcp.shared.exceptions") or exc
    exc_mod.MCPError = exc_mod.McpError  # type: ignore[attr-defined]


# Apply once when this file is imported (i.e. at pytest collection time)
_ensure_mcp_common_types()
_ensure_mcp_error_compat()
