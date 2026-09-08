"""Bash-friendly wrapper that invokes `mahavishnu worktree scan` via the Python module.

Per spec A70: uses `python -m mahavishnu.worktree_cli` (not the `mahavishnu`
console_script) for venv-correctness. The CLI exposes `scan` at the top
level of the module (not nested under a `worktree` subcommand), so the
invocation is `python -m mahavishnu.worktree_cli scan ...`.
"""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    """Pass through CLI args to the mahavishnu worktree scan subcommand."""
    cmd = [sys.executable, "-m", "mahavishnu.worktree_cli", "scan", *sys.argv[1:]]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
