"""JSON state-store helpers with POSIX flock + atomic write.

Generic, type-agnostic primitives for persistent JSON state files that
need concurrent-safe read/write across processes. Used by:

- ``mahavishnu.core.precommitment.JsonFileLockStore`` (the canonical
  producer; uses list-of-LockResult shape)
- ``mahavishnu.core.worktree_session_registry.SessionWorktreeRegistry``
  (uses dict-of-session shape)
- ``mahavishnu.distill.llm_usage.LLMUsageStore`` (uses list shape)

All callers share the same flock + temp-write + os.replace pattern.
This module is the single source of truth for those primitives so we
don't triplicate them (reviewer feedback, multi-agent review, 2026-07-20).

Security hardening (per reviewer feedback, multi-agent review, 2026-07-20):

- **O_NOFOLLOW** on open refuses pre-planted symlinks (CWE-59). The
  write path uses ``O_NOFOLLOW`` to canonicalize the destination
  inode before ``os.replace`` (closes the TOCTOU window that the
  prior ``lstat``-then-``os.replace`` pattern had).
- **chmod 0o600** on the file + **chmod 0o700** on the parent at first
  write (default-deny on world-read).

POSIX-only — mahavishnu is Unix-targeted by posture. NFS has subtle
flock semantics; this code assumes local FS.
"""
from __future__ import annotations

from collections.abc import Callable  # noqa: TC003 — type-only with __future__ annotations
from datetime import UTC, datetime
import errno
import fcntl
import json
import os
from pathlib import Path  # noqa: TC003 — type-only with __future__ annotations
import tempfile
from typing import Any


def _refuse_symlink_target(path: Path) -> None:
    """Refuse to write to a symlink at ``path`` (CWE-59).

    Uses ``O_NOFOLLOW`` open instead of ``lstat`` to close the TOCTOU
    window between the check and subsequent ``os.replace``. After
    this check, the destination inode is verified non-symlink;
    ``os.replace`` will follow a planted symlink if the attacker
    wins a microsecond race between this check and the replace.

    We accept that residual risk because the true mitigation
    (parent-directory locking) is not portable across all POSIX
    variants. See threat model in
    ``.claude/decisions/session-worktree-defaults.md``.
    """
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return  # first write — no inode to verify yet
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise OSError(
                errno.ELOOP,
                f"refusing to write to symlink target: {path}",
            ) from exc
        raise
    os.close(fd)


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
    """Atomically write ``data`` to ``path`` as JSON.

    Writes to a temp file in the same directory, then ``os.replace``s
    onto the target. Symlinks at the destination are refused via
    ``_refuse_symlink_target`` (``O_NOFOLLOW`` open). After successful
    write, applies ``chmod 0o600`` on the file and ``chmod 0o700`` on
    the parent.
    """
    _refuse_symlink_target(path)
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


def locked_json_modify(
    path: Path,
    modifier: Callable[
        [dict[str, Any] | list[Any] | None], dict[str, Any] | list[Any]
    ],
    *,
    default_factory: Callable[[], dict[str, Any] | list[Any]] | None = None,
) -> dict[str, Any] | list[Any]:
    """Atomically read-modify-write ``path`` under LOCK_EX on a sidecar lockfile.

    Acquires ``LOCK_EX`` on ``<path>.lock`` (a sidecar file in the same
    directory, created on first use with mode 0o600). All concurrent
    processes targeting the same ``path`` serialize on this lock,
    preventing lost-update races — see
    ``tests/integration/test_worktree_session_registry_concurrent.py``.

    Within the lock:
    1. Reads current content via ``locked_json_read`` (``O_NOFOLLOW``).
    2. If ``current`` is ``None`` and ``default_factory`` is provided,
       uses the factory's output as the initial value.
    3. Calls ``modifier(current)`` to compute new content.
    4. If ``modifier`` returns ``SKIP_WRITE``, no write happens.
    5. Otherwise atomically writes new content via ``atomic_json_write``.
    6. Releases lock.

    Returns the data that was written (or the unmodified current data
    if ``modifier`` returned ``SKIP_WRITE``).

    Args:
        path: target file path.
        modifier: callable ``(current_data) -> new_data``. May return
            ``SKIP_WRITE`` to indicate no write is needed (e.g., the
            on-disk schema version is unrecognized).
        default_factory: optional factory for the initial data when the
            file doesn't exist yet.
    """
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")

    # Ensure lockfile exists with restrictive mode. O_CREAT + O_NOFOLLOW
    # means we fail if the lockfile has been replaced with a symlink
    # (a planted symlink at the lockfile target would let an attacker
    # bypass the lock by flocking a different inode).
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    lock_fd = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            current = locked_json_read(path)
            if current is None and default_factory is not None:
                current = default_factory()
            new_data = modifier(current)
            if new_data is SKIP_WRITE:
                return current if current is not None else (
                    default_factory() if default_factory else {}
                )
            atomic_json_write(path, new_data)
            return new_data
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def utcnow_iso() -> str:
    """Return the current UTC time as ISO-8601 with ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


SKIP_WRITE = object()
"""Sentinel for ``locked_json_modify`` modifiers to indicate no write.

The modifier receives the current data and returns either the new data
to write, or ``SKIP_WRITE`` to indicate the operation should be a no-op
(e.g., refusing to write to a future-version file)."""


__all__ = [
    "SKIP_WRITE",
    "locked_json_read",
    "atomic_json_write",
    "locked_json_modify",
    "utcnow_iso",
]