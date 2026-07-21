from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_workers_enabled_false_blocks_spawn() -> None:
    env = os.environ.copy()
    env["MAHAVISHNU_WORKERS__ENABLED"] = "false"
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