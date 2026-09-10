"""PlanIndexWriter — thin I/O wrapper around rendered markdown."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["write"]


def write(rendered: str, path: Path) -> None:
    """Write rendered markdown to disk. Mode 0o644 on new files."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(path), flags, 0o644)
    try:
        os.write(fd, rendered.encode("utf-8"))
    finally:
        os.close(fd)
