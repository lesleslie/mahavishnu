from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from mahavishnu.plan_index.writer import write


class TestWrite:
    def test_creates_file_with_content(self, tmp_path: Path) -> None:
        path = tmp_path / "out.md"
        write("# Hello\n", path)
        assert path.read_text() == "# Hello\n"

    def test_file_mode_0o644_on_new_file(self, tmp_path: Path) -> None:
        path = tmp_path / "new.md"
        write("x", path)
        mode = path.stat().st_mode & 0o777
        assert mode == 0o644
