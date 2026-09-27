"""Atomic sidecar state persistence with fcntl.flock.

The sidecar tracks per-card revision counters for CAS-style conflict
detection. Concurrent watcher + CLI invocations are serialized via flock.

macOS fcntl.flock semantics note (per plan gotcha):
- On Linux, ``fcntl.flock`` is whole-file advisory locking that plays
  well across threads of one process AND across processes on one host.
- On macOS, ``fcntl.flock`` IS available (BSD-origin) and behaves the
  same as Linux for our purposes, but ``fcntl.fcntl`` (the POSIX
  advisory-lock API) is NOT supported on macOS — so we deliberately use
  ``fcntl.flock`` (BSD) rather than ``fcntl.fcntl`` (POSIX).
- ``fcntl.flock`` is non-portable to Windows. Operators on Windows must
  run the watcher under WSL or disable it (set
  ``markdown_board.enabled: false`` in settings).

A LOCK_EX acquired by one process blocks LOCK_EX on the same file from
another process on the same host. It does NOT coordinate across hosts —
the state sidecar is per-host only.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager

import fcntl


@contextmanager
def flocked_file(path: Path, mode: str = "r") -> Iterator[Any]:
    """Open file with flock; release in ``finally``.

    Lock-fd leak risk: if the with-block raises between ``open()`` and
    ``fcntl.flock()``, the LOCK_EX would never be released. We attempt
    the flock unconditionally; even if it fails the underlying fd is
    still closed in the finally clause.

    The unlock in ``finally`` swallows ``OSError``: ``fcntl.flock`` raises
    if the underlying fd has been closed (e.g. by another path in a
    refactor), and we never want a finally-block that crashes the
    supervisor loop.
    """
    fd = open(path, mode)
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        yield fd
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass  # best-effort unlock
        fd.close()


def load_state(state_path: Path) -> dict[str, int]:
    """Load per-card revision map. Returns empty map on missing/corrupt.

    Uses blocking LOCK_EX so concurrent watcher + CLI invocations see a
    consistent snapshot. Note: the lock lifetime is the lifetime of the
    read, NOT the lifetime of any downstream write — callers that intend
    to mutate must reload after acquiring the writer-side lock.
    """
    if not state_path.exists():
        return {}
    with flocked_file(state_path, "r") as f:
        try:
            data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    if not isinstance(data, dict):
        return {}
    coerced: dict[str, int] = {}
    for key, value in data.items():
        try:
            coerced[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return coerced


def save_state(state_path: Path, state: dict[str, int]) -> None:
    """Atomic write: write to a unique temp file, fsync, rename.

    The temp file is created in the same directory with a per-call
    unique suffix (PID + random hex) so concurrent callers do not
    truncate each other's in-flight writes. ``.replace()`` is atomic
    on POSIX (including macOS) when source and destination are on the
    same filesystem. On Windows, rename is not atomic — operators on
    Windows must run the watcher in WSL.

    The fdsync before rename ensures the sidecar's contents are
    durable on disk before the rename publishes them to readers.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Per-call unique temp filename avoids the "second open() truncates
    # the first writer's in-flight file" race that bit the implementation
    # that reused ``state.json.tmp``.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=state_path.name + ".",
        suffix=".tmp",
        dir=str(state_path.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        # Acquire flock on the freshly-created temp so a second
        # concurrent save_state with the same name has to wait.
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.replace(tmp_path, state_path)
    finally:
        # ``os.replace`` may have already moved the file out of the
        # way; ignore the unlink race.
        try:
            tmp_path.unlink()
        except OSError:
            pass
