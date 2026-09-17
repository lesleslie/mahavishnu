"""Substrate-compat helper for cross-portfolio producer modules.

Provide a single seam that lets producer modules query the optional Dhara
substrate at call time without taking a hard module-load-time dependency
on it. If the local dhara distribution exposes ``put`` / ``get`` / ``list``,
this module surfaces those via ``dhara_calltime``; if not (or if dhara
isn't installed at all), it returns ``None`` gracefully so the caller
can fall through to an in-memory path.

Lazy-load rationale: before Phase 8 of the Dhara MCP retirement plan,
this module did ``import dhara`` at the top so producers could call
``stamp_dhara_attr("put")`` to monkey-patch the live ``dhara`` module
at import time. After Wave A (no more direct ``import dhara`` calls
in this repo), the lazy-load lets the shim stay importable even when
dhara is uninstalled, while still resolving call-time lookups when it
is installed.

Usage in producer modules (after Phase 8):

    from mahavishnu.core._dhara_substrate_compat import dhara_calltime
    put = dhara_calltime("put")
    if put is not None:
        put(key, validated)
"""

from __future__ import annotations

from typing import Any, Final


_PUT: Final[str] = "put"
_GET: Final[str] = "get"
_LIST: Final[str] = "list"


def _try_load_dhara() -> Any | None:
    """Resolve the optional ``dhara`` module at call time.

    Returns the ``dhara`` module if importable, else ``None``. The shim
    does not declare ``dhara`` as a hard dependency at module-load time
    — only this lazy resolver touches it.
    """
    try:
        import dhara
    except ImportError:
        return None
    return dhara


def stamp_dhara_attr(name: str) -> None:
    """Stamp ``name`` onto the live ``dhara`` module if absent.

    Idempotent: safe to call multiple times. With the lazy-load refactor
    in Phase 8 Task 5, this becomes a defensive no-op when ``dhara`` is
    not installed. Kept for backward compatibility with producer
    modules that still call it; new code should prefer
    :func:`dhara_calltime`.
    """
    dhara = _try_load_dhara()
    if dhara is None:
        return
    if not hasattr(dhara, name):
        setattr(dhara, name, None)  # type: ignore[attr-defined]


def dhara_calltime(name: str) -> Any:
    """Resolve ``dhara.<name>`` at call time. Returns ``None`` when unbound.

    Use this in producer modules instead of importing ``dhara`` directly.
    Returns ``None`` when the ``dhara`` package is not importable (no
    ImportError leaks to the caller) AND when the attribute is absent.
    """
    dhara = _try_load_dhara()
    if dhara is None:
        return None
    return getattr(dhara, name, None)
