"""Model-evaluation extension points for Mahavishnu.

Phase 1 of the model-evaluation feature: a new primitive (deliberately not
an ``OrchestratorAdapter`` subclass — the execution shapes are
incompatible) plus four pluggable extension-point groups.

Public names are lazily imported so that importing ``mahavishnu.core.eval``
does not pull in oneiric or the storage layer.

See ``docs/plans/2026-10-03-eval-adapter-phase1.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._registry import (
        discover_dataset_loaders,
        discover_model_backends,
        discover_scorers,
        discover_storage,
    )

__all__ = [
    "discover_dataset_loaders",
    "discover_model_backends",
    "discover_scorers",
    "discover_storage",
]

_LAZY_IMPORTS = {
    "discover_dataset_loaders": ("._registry", "discover_dataset_loaders"),
    "discover_model_backends": ("._registry", "discover_model_backends"),
    "discover_scorers": ("._registry", "discover_scorers"),
    "discover_storage": ("._registry", "discover_storage"),
}


def __getattr__(name: str):
    """Lazily resolve a public name to its implementation module."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
