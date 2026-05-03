"""Tests for PID-based locking."""

from __future__ import annotations

import os
from pathlib import Path

from mahavishnu.core.code_index.lock import RepoIndexLock


def test_acquire_and_release(tmp_path: Path) -> None:
    lock = RepoIndexLock(str(tmp_path))
    assert lock.acquire() is True
    assert lock.lock_file.exists()
    lock.release()
    assert not lock.lock_file.exists()


def test_acquire_when_locked(tmp_path: Path) -> None:
    lock1 = RepoIndexLock(str(tmp_path))
    lock2 = RepoIndexLock(str(tmp_path))
    assert lock1.acquire() is True
    assert lock2.acquire() is False
    lock1.release()


def test_acquire_reclaims_dead_process(tmp_path: Path) -> None:
    lock = RepoIndexLock(str(tmp_path))
    lock.lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock.lock_file.write_text(f"99999\n0\n{tmp_path}\n")
    assert lock.acquire() is True
    lock.release()


def test_acquire_reclaims_stale_lock(tmp_path: Path) -> None:
    lock = RepoIndexLock(str(tmp_path))
    lock.lock_file.parent.mkdir(parents=True, exist_ok=True)
    # Write a lock with current PID but very old timestamp
    lock.lock_file.write_text(f"{os.getpid()}\n0\n{tmp_path}\n")
    # Should reclaim because TTL exceeded
    assert lock.acquire() is True
    lock.release()


def test_release_non_owner(tmp_path: Path) -> None:
    lock = RepoIndexLock(str(tmp_path))
    lock.lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock.lock_file.write_text(f"99999\n0\n{tmp_path}\n")
    # Should NOT remove lock owned by another PID
    lock.release()
    assert lock.lock_file.exists()


def test_release_nonexistent(tmp_path: Path) -> None:
    lock = RepoIndexLock(str(tmp_path))
    # Should not raise
    lock.release()
