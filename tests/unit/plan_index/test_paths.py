from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from mahavishnu.plan_index.paths import (
    errors_log_path,
    jot_dir,
    log_path,
    node_path,
)


class TestPaths:
    def test_jot_dir_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        path = jot_dir()
        assert path == tmp_path / ".mahavishnu" / "plan_index"
        assert path.exists()
        assert oct(path.stat().st_mode)[-3:] == "700"

    def test_log_path_under_jot_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert log_path().parent == jot_dir()

    def test_errors_log_path_under_jot_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert errors_log_path().parent == jot_dir()

    def test_node_path_under_jot_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        assert node_path().parent == jot_dir()

    def test_log_file_mode_0o600_on_creation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        path = log_path()
        assert path.exists()
        assert oct(path.stat().st_mode)[-3:] == "600"
