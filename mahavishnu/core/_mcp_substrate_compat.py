"""Substrate-compat gate — lazy resolver for the optional MCP substrate.

Producer modules query the substrate via :func:`mcp_calltime`; the
helper lazy-loads the ``mcp`` module on first call and resolves
``mcp.<name>``, returning ``None`` when the package is missing or
the attribute is unbound. No module-load-time dependency on mcp.

Usage in producer modules:

    from mahavishnu.core._mcp_substrate_compat import mcp_calltime
    put = mcp_calltime("put")
    if put is not None:
        put(key, validated)
    else:
        # substrate not bound — log a structured warning and skip persistence.
        ...
"""

from __future__ import annotations

import importlib
from typing import Any


def _try_load_mcp() -> Any | None:
    """Resolve the optional ``mcp`` module at call time.

    Returns the ``mcp`` module if importable, else ``None``. The shim
    does not declare ``mcp`` as a hard dependency at module-load time
    — only this lazy resolver touches it.

    Uses ``importlib.import_module`` with a string literal so static type
    checkers (``ty``, ``mypy``) don't flag the unresolved name — the
    import is a runtime lookup, not a hard binding.
    """
    try:
        return importlib.import_module("mcp")
    except ImportError:
        return None


def mcp_calltime(name: str) -> Any:
    """Resolve ``mcp.<name>`` at call time. Returns ``None`` when unbound.

    Use this in producer modules instead of importing ``mcp`` directly.
    Returns ``None`` when the ``mcp`` package is not importable (no
    ImportError leaks to the caller) AND when the attribute is absent.
    """
    mcp = _try_load_mcp()
    if mcp is None:
        return None
    return getattr(mcp, name, None)
