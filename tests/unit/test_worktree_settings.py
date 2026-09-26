"""Tests for WorktreeCacheSettings (kept) + WorktreeStorageSettings new shape.

REQ-001: Oneiric nested settings models for 5 new sections (WorktreeStorageSettings
replaces the previous multi-backend storage hierarchy per no-backcompat pre-1.0).
"""

from __future__ import annotations

import pytest

from mahavishnu.core.config import (
    MahavishnuSettings,
    WorktreeCacheSettings,
    WorktreeStorageSettings,
)


@pytest.mark.req(["REQ-001"])
class TestWorktreeStorageSettingsNewShape:
    """New spec-driven WorktreeStorageSettings shape (C-1 prep)."""

    def test_loads_with_defaults(self) -> None:
        s = WorktreeStorageSettings()
        assert s.enabled is False
        assert s.default_isolation == "host"
        assert s.max_concurrent == 5

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            WorktreeStorageSettings(unknown_field="nope")  # type: ignore[call-arg]

    def test_rejects_invalid_isolation(self) -> None:
        with pytest.raises(ValueError, match="default_isolation"):
            WorktreeStorageSettings(default_isolation="unknown")  # type: ignore[arg-type]

    def test_max_concurrent_bounds(self) -> None:
        with pytest.raises(ValueError, match="max_concurrent"):
            WorktreeStorageSettings(max_concurrent=0)
        with pytest.raises(ValueError, match="max_concurrent"):
            WorktreeStorageSettings(max_concurrent=10_000)


def test_worktree_cache_settings_key_prefix_is_canonical() -> None:
    """The default key prefix MUST match ADR §3 / cache.py DEFAULT_KEY_PREFIX."""
    s = WorktreeCacheSettings()
    assert s.key_prefix == "mahavishnu:worktree-cache:"
    assert s.l1_enabled is True
    assert s.l2_enabled is True
    assert s.l2_port == 6379
    assert s.l2_db == 1


def test_mahavishnu_settings_exposes_worktree_blocks() -> None:
    """Top-level MahavishnuSettings must include worktree_storage + worktree_cache."""
    settings = MahavishnuSettings()
    assert isinstance(settings.worktree_storage, WorktreeStorageSettings)
    assert isinstance(settings.worktree_cache, WorktreeCacheSettings)
    # Defaults carry through
    assert settings.worktree_cache.key_prefix == "mahavishnu:worktree-cache:"
    # New shape defaults
    assert settings.worktree_storage.enabled is False
    assert settings.worktree_storage.max_concurrent == 5


def test_worktree_cache_settings_env_override(monkeypatch: object) -> None:
    """Oneiric layered config should pick up env-var overrides of nested fields.

    Pydantic Settings supports ``MAHAVISHNU_WORKTREE_CACHE__L2_HOST``
    style overrides (double underscore separator). Smoke test that
    the field name maps correctly.
    """

    monkeypatch.setenv("MAHAVISHNU_WORKTREE_CACHE__L2_HOST", "redis-test.example.com")  # type: ignore[attr-defined]
    settings = MahavishnuSettings()
    assert settings.worktree_cache.l2_host == "redis-test.example.com"
