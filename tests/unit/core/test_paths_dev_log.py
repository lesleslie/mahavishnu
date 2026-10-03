"""CI guard test: paths.py must expose DEV_LOG_DIR constant and
get_dev_log_path() helper, mirroring get_audit_path() pattern.
"""
from __future__ import annotations

from pathlib import Path


def test_dev_log_dir_constant_exists() -> None:
    from mahavishnu.core import paths

    assert hasattr(paths, "DEV_LOG_DIR"), (
        "paths.py must expose DEV_LOG_DIR constant for the dev-log audit dir"
    )
    assert paths.DEV_LOG_DIR == paths.STATE_DIR / "dev-log"


def test_get_dev_log_path_mirrors_get_audit_path() -> None:
    from mahavishnu.core import paths

    assert paths.get_dev_log_path("foo.md") == paths.DEV_LOG_DIR / "foo.md"
    assert (
        paths.get_dev_log_path("nested", "bar.md")
        == paths.DEV_LOG_DIR / "nested" / "bar.md"
    )


def test_ensure_directories_creates_dev_log_dir(tmp_path, monkeypatch) -> None:
    """ensure_directories() must create DEV_LOG_DIR on invocation."""
    from mahavishnu.core import paths

    monkeypatch.setattr(paths, "STATE_DIR", tmp_path)
    paths.ensure_directories()
    assert (tmp_path / "dev-log").is_dir()
