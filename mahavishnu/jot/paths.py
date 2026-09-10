"""Filesystem path resolution for the jot inbox.

All paths resolve under ~/.mahavishnu/jot/ which is created with mode 0o700 on
first access. Individual files (log, errors, node) are NOT created by these
helpers — only the directory is. File creation happens lazily in the hook.
"""
from __future__ import annotations

import os
from pathlib import Path

# Cache the directory after first creation. Tests reset via conftest.py.
_jot_dir_cache: Path | None = None


def jot_dir() -> Path:
    """Return ~/.mahavishnu/jot, creating it with mode 0o700 if missing."""
    global _jot_dir_cache
    if _jot_dir_cache is None:
        path = Path.home() / ".mahavishnu" / "jot"
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        _jot_dir_cache = path
    return _jot_dir_cache


def log_path() -> Path:
    """Return the path to the main JSONL log (not created)."""
    return jot_dir() / "log.jsonl"


def errors_log_path() -> Path:
    """Return the path to the errors log (not created)."""
    return jot_dir() / "errors.log"


def node_path() -> Path:
    """Return the path to the node identifier file (not created)."""
    return jot_dir() / "node"
