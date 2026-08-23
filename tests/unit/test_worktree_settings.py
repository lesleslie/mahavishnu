"""Tests for WorktreeStorageSettings + WorktreeCacheSettings (PR-D.0)."""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core.config import (
    MahavishnuSettings,
    WorktreeCacheSettings,
    WorktreeLocalStorageSettings,
    WorktreeStorageSettings,
)


def test_worktree_storage_settings_defaults() -> None:
    s = WorktreeStorageSettings()
    assert s.backend_preference == ["local", "s3"]
    assert isinstance(s.local, WorktreeLocalStorageSettings)
    assert s.s3.bucket is None
    assert s.gcs.bucket is None
    assert s.azure.container is None


def test_worktree_local_storage_default_base_path_uses_helper() -> None:
    """Default base_path should come from get_worktree_base_path(), not
    a hardcoded ``~/worktrees`` literal (Phase 0.3 fix)."""
    s = WorktreeLocalStorageSettings()
    assert isinstance(s.base_path, Path)
    # The helper returns the configured path. We only check it's a Path,
    # not the literal value, to avoid coupling to env-specific config.
    assert s.base_path.is_absolute() or s.base_path.expanduser().is_absolute()


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
    assert settings.worktree_storage.backend_preference == ["local", "s3"]


def test_worktree_cache_settings_env_override(monkeypatch: object) -> None:
    """Oneiric layered config should pick up env-var overrides of nested fields.

    Pydantic Settings supports ``MAHAVISHNU_WORKTREE_CACHE__L2_HOST``
    style overrides (double underscore separator). Smoke test that
    the field name maps correctly.
    """
    import os

    monkeypatch.setenv("MAHAVISHNU_WORKTREE_CACHE__L2_HOST", "redis-test.example.com")  # type: ignore[attr-defined]
    settings = MahavishnuSettings()
    assert settings.worktree_cache.l2_host == "redis-test.example.com"
