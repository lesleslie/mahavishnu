# tests/unit/conftest.py
"""Unit-test-only conftest: mock missing mcp_common.types before any test runs."""

from __future__ import annotations

import sys
from types import ModuleType


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


# Apply once when this file is imported (i.e. at pytest collection time)
_ensure_mcp_common_types()
