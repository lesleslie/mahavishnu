"""Pool type registry — replaces the if/elif chain in PoolManager.spawn_pool.

Each pool module (mahavishnu_pool, session_buddy_pool, runpod_pool, pi_pool, ...)
registers itself on import via ``register_pool_type``. The dispatch in
``PoolManager.spawn_pool`` looks up the factory by canonical name (hyphen form).

Backward compatibility: the CLI whitelist accepts the underscore form
(``session_buddy``) and translates to the canonical hyphen form
(``session-buddy``) before lookup, so existing CLI users keep working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# Canonical key strings use hyphens to match the existing manager dispatch
# (mahavishnu, session-buddy, runpod). The new "pi" entry follows the same rule.
_POOL_FACTORIES: dict[str, Callable[..., Any]] = {}


def register_pool_type(name: str, factory: Callable[..., Any]) -> None:
    """Register a pool type factory.

    Args:
        name: Canonical pool type name (hyphen-separated, e.g. "session-buddy").
        factory: Callable that constructs a ``BasePool`` subclass. Receives
            ``config: PoolConfig`` and additional kwargs as forwarded by
            ``PoolManager.spawn_pool``.

    Raises:
        ValueError: If the name is already registered.
    """
    if name in _POOL_FACTORIES:
        raise ValueError(f"Pool type {name!r} is already registered")
    _POOL_FACTORIES[name] = factory


def get_pool_factory(name: str) -> Callable[..., Any]:
    """Look up a pool factory by canonical (hyphen) name.

    Args:
        name: Canonical pool type name (hyphens). Caller should normalize
            underscore input via :func:`canonicalize_pool_type` first.

    Returns:
        The factory callable.

    Raises:
        KeyError: If the name is not registered. Use :func:`list_pool_types`
            to discover the available names.
    """
    factory = _POOL_FACTORIES.get(name)
    if factory is None:
        raise KeyError(f"Unknown pool type {name!r}. Available: {', '.join(list_pool_types())}")
    return factory


def list_pool_types() -> tuple[str, ...]:
    """Return the registered pool type names, sorted.

    Useful for CLI whitelists and ``terminal_list_adapters``-style discovery.
    """
    return tuple(sorted(_POOL_FACTORIES))


def canonicalize_pool_type(name: str) -> str:
    """Normalize CLI input to the canonical hyphen-separated form.

    Examples:
        >>> canonicalize_pool_type("session_buddy")
        'session-buddy'
        >>> canonicalize_pool_type("session-buddy")
        'session-buddy'
        >>> canonicalize_pool_type("mahavishnu")
        'mahavishnu'
    """
    return name.replace("_", "-")


# Trigger pool module loading at registry-import. Callers who import
# ``mahavishnu.pools._registry`` directly (e.g. the CLI) bypass
# ``mahavishnu.pools.__init__``'s eager loader, so we must ensure registration
# happens here too. We import the modules through their public names so any
# import error propagates to the caller at the same place it would from
# ``mahavishnu.pools.__init__``.
def _ensure_pool_registry_loaded() -> None:
    from . import (
        gpu_handler_pool,  # noqa: F401  — registry side-effect
        mahavishnu_pool,  # noqa: F401  — registry side-effect
        pi_pool,  # noqa: F401  — registry side-effect (D1)
        runpod_pool,  # noqa: F401  — registry side-effect
        session_buddy_pool,  # noqa: F401  — registry side-effect
    )


_ensure_pool_registry_loaded()


__all__ = [
    "canonicalize_pool_type",
    "get_pool_factory",
    "list_pool_types",
    "register_pool_type",
]
