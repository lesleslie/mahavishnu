"""Substrate-compat gate — lazy resolver for the optional Dhara substrate.

Producer modules query the substrate via :func:`dhara_calltime`; the
helper lazy-loads the ``dhara`` module on first call and resolves
``dhara.<name>``, returning ``None`` when the package is missing or
the attribute is unbound. No module-load-time dependency on dhara.

Usage in producer modules:

    from mahavishnu.core._dhara_substrate_compat import dhara_calltime
    put = dhara_calltime("put")
    if put is not None:
        put(key, validated)
    else:
        # substrate not bound — log a structured warning and skip persistence.
        ...
"""

from __future__ import annotations

from typing import Any


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
