"""Discovery for the eval extension points.

Four groups are discoverable, one per pluggable extension point:

* ``mahavishnu.eval.scorers`` — scorers
* ``mahavishnu.eval.dataset_loaders`` — dataset loaders
* ``mahavishnu.eval.storage`` — run-storage backends
* ``mahavishnu.eval.model_backends`` — model backends

Discovery merges two sources:

1. **Built-ins** — ``_BUILTINS`` maps each group to ``{name: "module:attr"}``.
   This is the runtime source of truth for the extension points that ship
   with Mahavishnu.
2. **Installed entry points** — ``oneiric.plugins.iter_entry_points(group)``
   resolves any installed distribution's
   ``[project.entry-points."mahavishnu.eval.*"]`` declarations. Entry points
   win over built-ins of the same name, so a third-party distribution can
   replace a shipped extension point.

Python 3.14 removed ``importlib.metadata.entry_point()`` and
``EntryPoint.register()``, so entry points cannot be registered at runtime;
the built-in table is what makes the shipped extension points resolvable
without reinstalling the distribution. See
``docs/plans/2026-10-03-eval-adapter-phase1.md`` Task 1.3b.
"""

from __future__ import annotations

from importlib import import_module
import logging
import time
from typing import TYPE_CHECKING, Any

from oneiric.plugins import iter_entry_points

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# req: REQ-EVAL-001

SCORERS_GROUP = "mahavishnu.eval.scorers"
DATASET_LOADERS_GROUP = "mahavishnu.eval.dataset_loaders"
STORAGE_GROUP = "mahavishnu.eval.storage"
MODEL_BACKENDS_GROUP = "mahavishnu.eval.model_backends"

#: Built-in extension points, keyed by group then by extension-point name.
#: Values are ``"module:attr"`` targets resolved lazily on first discovery.
#: Keep this in sync with the ``[project.entry-points."mahavishnu.eval.*"]``
#: groups in ``pyproject.toml``; ``tests/unit/core/eval/test_registry.py``
#: asserts the two agree.
_BUILTINS: dict[str, dict[str, str]] = {
    SCORERS_GROUP: {
        "mahavishnu.exact_match": "mahavishnu.core.eval.scorers.exact_match:ExactMatchScorer",
        "mahavishnu.contains": "mahavishnu.core.eval.scorers.contains:ContainsScorer",
    },
    DATASET_LOADERS_GROUP: {
        "mahavishnu.jsonl": "mahavishnu.core.eval.loaders.jsonl:JsonlDatasetLoader",
    },
    STORAGE_GROUP: {
        "mahavishnu.sqlite": "mahavishnu.core.eval.storage_backends.sqlite:SqliteEvalStorage",
    },
    MODEL_BACKENDS_GROUP: {
        "mahavishnu.mock": "mahavishnu.core.eval.model_backends.mock:MockModelBackend",
    },
}

#: Discovery cache lifetime in seconds. Mirrors
#: ``AdapterRegistryConfig.cache_ttl_seconds`` (300 s) on the
#: adapter-registry config.
_CACHE_TTL_SECONDS = 300.0

_cache: dict[str, tuple[float, dict[str, Callable[..., Any]]]] = {}


def _resolve(target: str) -> Callable[..., Any]:
    """Resolve a ``"module:attr"`` target to the object it names.

    Args:
        target: Import target in ``"module.path:AttributeName"`` form.

    Returns:
        The imported attribute.

    Raises:
        ImportError: If the module cannot be imported.
        AttributeError: If the module has no such attribute.
    """
    module_name, _, attribute = target.partition(":")
    module = import_module(module_name)
    resolved: Callable[..., Any] = getattr(module, attribute)
    return resolved


def _discover(group: str) -> dict[str, Callable[..., Any]]:
    """Discover one group's extension points — built-ins first."""
    found: dict[str, Callable[..., Any]] = {
        name: _resolve(target) for name, target in _BUILTINS.get(group, {}).items()
    }
    for entry_point in iter_entry_points(group):
        found[entry_point.name] = entry_point.load()
    return found


def _cached(group: str, domain: str) -> dict[str, Callable[..., Any]]:
    """Return a group's extension points, re-discovering after the TTL.

    Args:
        group: The entry-point group name.
        domain: Short domain name used in the discovery log line.

    Returns:
        The extension points, keyed by name.
    """
    now = time.monotonic()
    cached = _cache.get(group)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    discovered = _discover(group)
    _cache[group] = (now, discovered)
    logger.info("eval.registry.discovered domain=%s count=%d", domain, len(discovered))
    return discovered


def discover_scorers() -> dict[str, Callable[..., Any]]:
    """Return the discovered scorers, keyed by extension-point name."""
    return _cached(SCORERS_GROUP, "scorer")


def discover_dataset_loaders() -> dict[str, Callable[..., Any]]:
    """Return the discovered dataset loaders, keyed by extension-point name."""
    return _cached(DATASET_LOADERS_GROUP, "dataset_loader")


def discover_storage() -> dict[str, Callable[..., Any]]:
    """Return the discovered storage backends, keyed by extension-point name."""
    return _cached(STORAGE_GROUP, "storage")


def discover_model_backends() -> dict[str, Callable[..., Any]]:
    """Return the discovered model backends, keyed by extension-point name."""
    return _cached(MODEL_BACKENDS_GROUP, "model_backend")
