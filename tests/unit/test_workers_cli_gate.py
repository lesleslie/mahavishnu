from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_workers_enabled_false_blocks_spawn(tmp_path: Path) -> None:
    settings = tmp_path / "settings.yaml"
    settings.write_text("workers:\n  enabled: false\n")
    env = os.environ.copy()
    env["MAHAVISHNU_SETTINGS_PATH"] = str(settings)
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "spawn",
         "--type", "terminal-shell", "--count", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode != 0
    assert "disabled" in (result.stderr + result.stdout).lower()