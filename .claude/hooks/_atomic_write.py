"""Atomic, owner-only file writes for the Claude Code hooks.

Shared helper for the hook scripts in this directory. It is deliberately
self-contained -- no ``mahavishnu`` import -- because a hook that
fires on every tool call cannot afford the package import, and because
a hook must never fail because the package is unavailable.

The naive fixed-name version of the "write to a temp file, then rename
over the destination" pattern has three distinct failure modes, all of
which are closed by using a uniquely named temp file:

1. **Concurrent-writer collision.** With a fixed temp name, every
   writer of the same destination shares one temp file. Whichever
   writer renames first moves the file out from under the others,
   whose rename then fails with ``FileNotFoundError`` -- and can
   publish the other writer's bytes. A writer that swallows ``OSError``
   turns that into a silently lost update.
2. **Stale temp reuse.** A temp file left behind by an earlier write
   is reused rather than recreated, so the new content lands in a file
   whose permissions were decided by that earlier -- possibly crashed --
   write.
3. **Symlink following.** Opening a fixed temp path with ``O_CREAT |
   O_TRUNC`` follows symlinks, so anything able to write into the
   destination directory can redirect the write -- and its truncation --
   at an arbitrary file.

``tempfile.mkstemp`` closes all three: it creates a fresh file with a
unique name, at 0600, and refuses to follow an existing path.

The published file's mode is set with ``fchmod`` on the open descriptor
rather than ``chmod`` on the path, so the file is never observable at a
wider mode than requested, even momentarily.
"""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["atomic_write_bytes", "atomic_write_text"]


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically, with owner-only permissions.

    Args:
        path: Destination path. Its parent directory must already exist.
        data: The bytes to write.
        mode: Permission bits for the published file.

    Raises:
        OSError: If the temp file cannot be created, written, or renamed.
    """
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write ``text`` to ``path`` atomically, with owner-only permissions.

    Args:
        path: Destination path. Its parent directory must already exist.
        text: The text to write, encoded as UTF-8.
        mode: Permission bits for the published file.

    Raises:
        OSError: If the temp file cannot be created, written, or renamed.
    """
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)
