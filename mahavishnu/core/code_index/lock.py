"""PID-based file locks for preventing concurrent indexing of the same repo."""

from __future__ import annotations

import contextlib
import errno
import os
from pathlib import Path
import time

LOCK_TTL_SECONDS = 600  # 10 minutes

# Flags for atomic exclusive file creation
_O_CREAT_EXCL = os.O_CREAT | os.O_EXCL | os.O_WRONLY


class RepoIndexLock:
    """PID-based lock for per-repo indexing.

    Lock file format: {pid}\\n{timestamp}\\n{repo_path}

    Uses ``O_CREAT | O_EXCL`` so that two processes cannot both believe they
    hold the lock at the same instant.
    """

    def __init__(self, repo_path: str) -> None:
        self.repo_path = repo_path
        self.lock_file = Path(repo_path) / ".git" / "mahavishnu-index.lock"

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if acquired."""
        if self._try_acquire():
            return True
        # Lock exists -- check if stale
        try:
            content = self.lock_file.read_text().strip().split("\n")
            pid = int(content[0])
            ts = float(content[1])
        except (ValueError, IndexError, FileNotFoundError):
            self._remove_lock()
            return self._try_acquire()

        if self._is_process_alive(pid):
            if time.time() - ts > LOCK_TTL_SECONDS:
                self._remove_lock()
                return self._try_acquire()
            return False

        # Owner process is dead -- reclaim
        self._remove_lock()
        return self._try_acquire()

    def release(self) -> None:
        """Release the lock if we hold it."""
        try:
            content = self.lock_file.read_text().strip().split("\n")
            pid = int(content[0])
            if pid == os.getpid():
                self._remove_lock()
        except (ValueError, IndexError, FileNotFoundError):
            pass

    def _try_acquire(self) -> bool:
        """Atomically create the lock file (fails if it already exists)."""
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.lock_file), _O_CREAT_EXCL, 0o644)
            try:
                os.write(fd, f"{os.getpid()}\n{time.time()}\n{self.repo_path}\n".encode())
            finally:
                os.close(fd)
            return True
        except OSError:
            return False

    def _remove_lock(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.lock_file.unlink()

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Return True if *pid* refers to a running process."""
        try:
            os.kill(pid, 0)
            return True
        except OSError as e:
            return e.errno != errno.ESRCH
