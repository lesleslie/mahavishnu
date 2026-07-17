"""JSON state-store helpers with POSIX flock + atomic write.

Generic, type-agnostic primitives for persistent JSON state files that
need concurrent-safe read/write across processes. Used by:

- ``mahavishnu.core.precommitment.JsonFileLockStore`` (the canonical
  producer; uses list-of-LockResult shape)
- ``mahavishnu.core.worktree_session_registry.SessionWorktreeRegistry``
  (uses dict-of-session shape)

Both callers share the same flock + temp-write + os.replace pattern.
This module is the single source of truth for those primitives so we
don't triplicate them (reviewer feedback, 4-lens plan, 2026-07-16).

Security hardening (per reviewer feedback, 4-lens plan, 2026-07-16):

- **O_NOFOLLOW** on open refuses pre-planted symlinks (CWE-59).
- **chmod 0o600** on the file + **chmod 0o700** on the parent at first
  write (default-deny on world-read).

POSIX-only — mahavishnu is Unix-targeted by posture. NFS has subtle
flock semantics; this code assumes local FS.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _check_not_symlink(path: Path) -> None:
    """Reject symlink targets (CWE-59).

    Refuses to write to a path whose final component is a symlink. The
    caller should pass the target path before any symlink substitution
    can occur. The atomic_write below uses ``os.replace`` which follows
    symlinks at the target — this pre-check is the actual defense.
    """
    if path.is_symlink():
        raise OSError(
            errno.ELOOP,
            f"refusing to write to symlink target: {path}",
        )


def locked_json_read(path: Path) -> dict[str, Any] | list[Any] | None:
    """Read JSON from ``path`` under a shared flock.

    Returns ``None`` if the file does not exist or is empty. Raises
    ``json.JSONDecodeError`` if the file is corrupt — the caller decides
    whether to quarantine (e.g. rename to ``.corrupt-<ts>``) and start
    fresh, or surface the error.
    """
    if not path.exists():
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        raw = b""
        try:
            # Read in chunks up to a sane upper bound; state files are small.
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 10 * 1024 * 1024:  # 10 MB safety cap
                    raise ValueError(
                        f"state file {path} exceeds 10 MB safety cap"
                    )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
    if not raw.strip():
        return None
    return json.loads(raw.decode("utf-8"))


def atomic_json_write(path: Path, data: dict[str, Any] | list[Any]) -> None:
    """Atomically write ``data`` to ``path`` as JSON, under an exclusive flock.

    Writes to a temp file in the same directory, then ``os.replace``s
    onto the target. ``fcntl.flock`` (exclusive) coordinates with
    concurrent readers and writers. The temp file is cleaned up on
    any failure. After successful write, applies ``chmod 0o600`` on
    the file and ``chmod 0o700`` on the parent.
    """
    _check_not_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Harden parent dir before writing.
    path.parent.chmod(0o700)

    encoded = json.dumps(
        data,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        fd = -1  # mark closed; finally block skips cleanup
        os.replace(tmp_path, path)
    except BaseException:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            Path(tmp_path).unlink()
        except FileNotFoundError:
            pass
        raise

    # Post-write: harden the file (defense in depth — even though parent
    # is 0700, the file mode prevents accidental world-read via symlink).
    path.chmod(0o600)


def utcnow_iso() -> str:
    """Return the current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


__all__ = ["locked_json_read", "atomic_json_write", "utcnow_iso"]
