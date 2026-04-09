"""Unit tests for core.paths."""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core import paths


def test_path_helper_functions_join_components() -> None:
    assert paths.get_data_path("a", "b.txt") == paths.DATA_DIR / "a" / "b.txt"
    assert paths.get_config_path("cfg.yaml") == paths.CONFIG_DIR / "cfg.yaml"
    assert paths.get_cache_path("x", "y") == paths.CACHE_DIR / "x" / "y"
    assert paths.get_state_path("s.db") == paths.STATE_DIR / "s.db"
    assert paths.get_log_path("app.log") == paths.LOG_DIR / "app.log"
    assert paths.get_audit_path("audit.log") == paths.AUDIT_DIR / "audit.log"


def test_ensure_directories_creates_all_expected_directories(
    tmp_path: Path, monkeypatch
) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    cache = tmp_path / "cache"
    state = tmp_path / "state"
    log = state / "logs"
    audit = state / "audit"

    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "CONFIG_DIR", config)
    monkeypatch.setattr(paths, "CACHE_DIR", cache)
    monkeypatch.setattr(paths, "STATE_DIR", state)
    monkeypatch.setattr(paths, "LOG_DIR", log)
    monkeypatch.setattr(paths, "AUDIT_DIR", audit)

    paths.ensure_directories()

    assert data.is_dir()
    assert config.is_dir()
    assert cache.is_dir()
    assert state.is_dir()
    assert log.is_dir()
    assert audit.is_dir()


def test_migrate_legacy_data_returns_false_when_legacy_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    new = tmp_path / "new.db"
    assert paths.migrate_legacy_data(missing, new) is False
    assert not new.exists()


def test_migrate_legacy_data_returns_false_when_destination_exists(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    legacy.write_text("legacy")
    new = tmp_path / "new.db"
    new.write_text("existing")

    assert paths.migrate_legacy_data(legacy, new) is False
    assert new.read_text() == "existing"


def test_migrate_legacy_data_copies_file(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    legacy.write_text("content")
    new = tmp_path / "nested" / "new.db"

    assert paths.migrate_legacy_data(legacy, new) is True
    assert new.exists()
    assert new.read_text() == "content"


def test_migrate_legacy_data_copies_directory(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy_dir"
    legacy_dir.mkdir()
    (legacy_dir / "one.txt").write_text("one")
    nested = legacy_dir / "sub"
    nested.mkdir()
    (nested / "two.txt").write_text("two")

    new_dir = tmp_path / "new" / "copied_dir"
    assert paths.migrate_legacy_data(legacy_dir, new_dir) is True
    assert (new_dir / "one.txt").read_text() == "one"
    assert (new_dir / "sub" / "two.txt").read_text() == "two"
