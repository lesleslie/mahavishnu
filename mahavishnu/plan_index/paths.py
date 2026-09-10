"""Filesystem paths for the plan_index module.

Mirror `mahavishnu/jot/paths.py` for mode discipline (0o700 dir, 0o600 files).
The jot_dir() raises PermissionError on creation failure; we propagate.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["errors_log_path", "jot_dir", "log_path", "node_path"]


def jot_dir() -> Path:
    """Return the plan_index directory, creating it with mode 0o700."""
    path = Path.home() / ".mahavishnu" / "plan_index"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def log_path() -> Path:
    """Return the path to the in-memory operational log. Created with mode 0o600 on first access."""
    path = jot_dir() / "log.jsonl"
    if not path.exists():
        path.touch(mode=0o600)
    return path


def errors_log_path() -> Path:
    """Return the path to errors.log. Mode 0o600 on creation."""
    path = jot_dir() / "errors.log"
    if not path.exists():
        path.touch(mode=0o600)
    return path


def node_path() -> Path:
    """Return the path to the persisted HLC node identifier."""
    return jot_dir() / "node"
