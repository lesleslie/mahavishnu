from __future__ import annotations

from pathlib import Path
import stat

import pytest

from mahavishnu.jot.paths import (
    errors_log_path,
    jot_dir,
    log_path,
    node_path,
)


def test_jot_dir_creates_directory_with_mode_0o700(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """jot_dir() must create ~/.mahavishnu/jot with mode 0o700."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = jot_dir()
    assert result == tmp_path / ".mahavishnu" / "jot"
    assert result.exists()
    assert result.is_dir()
    mode = stat.S_IMODE(result.stat().st_mode)
    assert mode == 0o700


def test_jot_dir_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling jot_dir() multiple times must not error or change permissions."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    first = jot_dir()
    second = jot_dir()
    assert first == second


def test_log_path_returns_jot_dir_log_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """log_path() must return <jot_dir>/log.jsonl."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert log_path() == tmp_path / ".mahavishnu" / "jot" / "log.jsonl"


def test_log_path_does_not_create_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """log_path() must not create the file."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = log_path()
    assert not path.exists()


def test_errors_log_path_returns_correct_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert errors_log_path() == tmp_path / ".mahavishnu" / "jot" / "errors.log"


def test_errors_log_path_does_not_create_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = errors_log_path()
    assert not path.exists()


def test_node_path_returns_correct_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert node_path() == tmp_path / ".mahavishnu" / "jot" / "node"


def test_jot_dir_works_when_dir_already_exists_with_0o700(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If jot_dir already exists, jot_dir() must not error or change mode."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    existing = tmp_path / ".mahavishnu" / "jot"
    existing.mkdir(parents=True, mode=0o700)
    original_mode = stat.S_IMODE(existing.stat().st_mode)
    jot_dir()
    assert stat.S_IMODE(existing.stat().st_mode) == original_mode
