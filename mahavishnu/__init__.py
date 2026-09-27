"""Mahavishnu - Global orchestrator package.

``__version__`` is derived from the installed distribution metadata via
``importlib.metadata.version()`` so :file:`pyproject.toml` is the single
source of truth for the version string. Editable installs without a
built ``.dist-info`` fall back to ``"0+unknown"`` (PEP 440 local-version
label) so the import never crashes.
"""

from __future__ import annotations

from importlib import metadata as _metadata

# PEP 440 local-version label; sentinel for "metadata not found" rather
# than a real release version.
_VERSION_FALLBACK = "0+unknown"


def _resolve_version() -> str:
    """Return the distribution version, falling back to a known sentinel.

    Wrapped in a function so tests can monkeypatch the lookup without
    having to reload the package.
    """
    try:
        return _metadata.version("mahavishnu")
    except _metadata.PackageNotFoundError:
        return _VERSION_FALLBACK


__version__ = _resolve_version()

__all__ = ["__version__"]
