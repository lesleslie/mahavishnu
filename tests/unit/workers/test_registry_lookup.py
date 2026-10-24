"""Tests for the new capability-driven worker lookup API.

This module pins the public contract added in Task 2.5:

- ``get_worker_entry(worker_type, *, settings=None) -> WorkerEntry`` raises
  :class:`MahavishnuError` (NOT ``KeyError``) on miss.
- ``list_worker_types(*, settings=None) -> list[str]`` returns the new
  no-``category`` capability-driven lookup.
- The legacy ``list_worker_types(category=...)`` signature remains
  available for back-compat testing.
"""
from __future__ import annotations

import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.errors import MahavishnuError
from mahavishnu.workers.registry import get_worker_entry, list_worker_types


def test_get_worker_entry_loads_from_settings() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "terminal-shell", "name": "Bash", "command_argv": ["bash"]},
        ]},
    })
    entry = get_worker_entry("terminal-shell", settings=s)
    assert entry.name == "Bash"


def test_get_worker_entry_raises_for_unknown() -> None:
    """Missing worker_type raises MahavishnuError(RESOURCE_NOT_FOUND), NOT KeyError."""
    s = MahavishnuSettings()
    with pytest.raises(MahavishnuError):
        get_worker_entry("does-not-exist", settings=s)


def _loaded_registry_settings() -> MahavishnuSettings:
    """The LOADED worker registry, from the committed ``worker_registry:`` block.

    A bare ``MahavishnuSettings()`` carries field DEFAULTS only -- it is a
    pydantic-settings model and does not read YAML. Its
    ``worker_registry.entries`` is therefore empty, which is why the
    capability-driven lookups are defined against the Oneiric-loaded
    registry instead. This helper loads the committed block directly so
    the test is hermetic: it does not touch ``~/.config`` or the
    process-wide settings cache.
    """
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parents[3]
    data = yaml.safe_load((repo_root / "settings" / "mahavishnu.yaml").read_text())
    return MahavishnuSettings.model_validate({"worker_registry": data["worker_registry"]})


def test_list_worker_types_returns_all_registered() -> None:
    s = _loaded_registry_settings()
    types_ = list_worker_types(settings=s)
    assert "terminal-claude" in types_
    assert "terminal-shell" in types_
    assert len(types_) >= 16


def test_legacy_list_worker_types_with_category_still_works() -> None:
    """The existing list_worker_types(category=...) signature is preserved."""
    from mahavishnu.workers.registry import list_worker_types as legacy
    s = MahavishnuSettings()
    types_ = legacy(settings=s, category="ai-context")  # may be empty, must not raise
    assert isinstance(types_, list)
