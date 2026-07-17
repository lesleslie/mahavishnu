"""Registry mapping Claude session_id → worktree_path.

Persistent JSON-backed store for which Claude session is using which
git worktree. Backed by ``mahavishnu.core.json_state_store`` primitives
(single source of truth for flock + atomic-write — per the 4-lens
plan review, 2026-07-16).

Used by:

- ``.claude/hooks/worktree-session-isolation.py`` (the SessionStart
  hook that auto-provisions a worktree when ``MAHAVISHNU_AUTO_WORKTREE=1``)
- ``mahavishnu worktree list-sessions`` (CLI for users to inspect
  which sessions are using which worktrees)
- ``mahavishnu worktree prune-abandoned`` (CLI to clean up dead
  worktrees per the never-auto-remove policy)

Schema migration policy (per 4-lens plan, 2026-07-16):

- **schema_version > supported**: log warning to stderr, return empty
  registry (no writes).
- **corrupt JSON**: caller decides whether to quarantine. The
  registry exposes ``quarantine_corrupt_file()`` for this purpose.
- **bumping schema_version**: requires a ``migrate_v1_to_v2()`` function
  colocated with this class. Currently at v1.

Security hardening (per 4-lens plan, 2026-07-16):

- File written with ``chmod 0o600``, parent ``chmod 0o700`` (refuses
  symlinks via O_NOFOLLOW — CWE-59 mitigation).
- POSIX-only flock — mahavishnu is Unix-targeted by posture.

Failure modes: returns empty registry (no exception) when the file
is missing or schema is unrecognized; the caller decides whether to
proceed. Crashes during write are cleaned up (the temp file is removed
on exception).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from mahavishnu.core.json_state_store import (
    atomic_json_write,
    locked_json_read,
    utcnow_iso,
)
from mahavishnu.core.paths import get_state_path


SUPPORTED_SCHEMA_VERSION = 1


def _short_session_id(session_id_full: str) -> str:
    """Derive the 8-char registry key from a Claude session UUID.

    Claude session UUIDs have the form 8-4-4-4-12 hex. The first 8
    hex chars (before the first ``-``) are uniformly distributed and
    unique enough at sub-1000-session scale. Using the full 16 chars
    from ``[:16]`` slices into the time-low field which would collide
    across UUIDv4 variants. The first-segment 8 chars are the
    registry key.

    Returns an empty string if the input is malformed (UUID parse
    fails). Callers should treat empty as a hard skip — never coerce
    or guess.
    """
    try:
        return uuid.UUID(session_id_full).hex[:8]
    except (ValueError, AttributeError, TypeError):
        return ""


class SessionWorktreeRegistry:
    """``session_id_short → worktree_path`` registry.

    Persisted as a single JSON document at the XDG state path
    (``~/.local/state/mahavishnu/session-worktrees.json`` on Linux,
    ``~/Library/Application Support/mahavishnu/...`` on macOS). Override
    the path for tests.

    Schema::

        {
          "schema_version": 1,
          "updated_at": "2026-07-16T18:42:13.514Z",
          "sessions": {
            "<session_id_short>": {
              "session_id_short": "...",
              "worktree_path": "...",
              "branch": "...",
              "repo_path": "...",
              "repo_nickname": "...",
              "state": "active" | "abandoned",
              "created_at": "...",
              "last_seen_at": "...",
              "abandoned_at": "..." | null,
              "hook_pid": <int>,
              "metadata": {...}
            }
          }
        }
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_state_path("session-worktrees.json")
        self._read_only = False

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, Any]:
        """Read the registry, returning an empty structure on missing/corrupt.

        Honors schema_version: if the file declares a version higher
        than ``SUPPORTED_SCHEMA_VERSION``, returns an empty registry
        AND sets ``self._read_only = True`` so subsequent writes are
        rejected (no overwriting of an unknown-version file).
        """
        data = locked_json_read(self._path)
        if data is None:
            self._read_only = False
            return self._empty()
        if not isinstance(data, dict):
            self._read_only = False
            return self._empty()
        version = data.get("schema_version")
        if version is None:
            self._read_only = False
            return self._empty()
        if version > SUPPORTED_SCHEMA_VERSION:
            # Future version: refuse to write (4-lens plan policy).
            self._read_only = True
            return self._empty()
        if version < SUPPORTED_SCHEMA_VERSION:
            # Future: call migrate_<old>_to_<new>() here.
            self._read_only = True
            return self._empty()
        sessions = data.get("sessions", {})
        if not isinstance(sessions, dict):
            self._read_only = False
            return self._empty()
        self._read_only = False
        return data

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "updated_at": utcnow_iso(),
            "sessions": {},
        }

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically write ``data`` to disk, refreshing ``updated_at``.

        Refuses to write if ``self._read_only`` is True (set by ``_read``
        when the on-disk file declares a future ``schema_version``).
        """
        if self._read_only:
            return
        data["schema_version"] = SUPPORTED_SCHEMA_VERSION
        data["updated_at"] = utcnow_iso()
        atomic_json_write(self._path, data)

    def _save_sessions(self, sessions: dict[str, dict]) -> None:
        self._write(
            {
                "schema_version": SUPPORTED_SCHEMA_VERSION,
                "updated_at": utcnow_iso(),
                "sessions": sessions,
            }
        )

    # ── Public CRUD API ─────────────────────────────────────────────

    def register(
        self,
        session_id_short: str,
        worktree_path: str,
        branch: str,
        repo_path: str,
        repo_nickname: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or refresh an entry. Idempotent — refreshes ``last_seen_at``."""
        if not session_id_short:
            raise ValueError("session_id_short must be non-empty")
        data = self._read()
        now = utcnow_iso()
        existing = data["sessions"].get(session_id_short, {})
        merged = {
            "session_id_short": session_id_short,
            "worktree_path": str(worktree_path),
            "branch": branch,
            "repo_path": str(repo_path),
            "repo_nickname": repo_nickname,
            "state": existing.get("state", "active"),
            "created_at": existing.get("created_at", now),
            "last_seen_at": now,
            "abandoned_at": existing.get("abandoned_at"),
            "hook_pid": metadata.get("hook_pid") if metadata else None,
            "metadata": metadata or {},
        }
        data["sessions"][session_id_short] = merged
        self._save_sessions(data["sessions"])

    def get(self, session_id_short: str) -> dict[str, Any] | None:
        """Return the entry for ``session_id_short`` or ``None``."""
        return self._read()["sessions"].get(session_id_short)

    def mark_abandoned(
        self, session_id_short: str, abandoned_at: str | None = None
    ) -> None:
        """Flip an entry's state to ``"abandoned"``. No-op if missing."""
        data = self._read()
        record = data["sessions"].get(session_id_short)
        if record is None:
            return
        record["state"] = "abandoned"
        record["abandoned_at"] = abandoned_at or utcnow_iso()
        data["sessions"][session_id_short] = record
        self._save_sessions(data["sessions"])

    def remove(self, session_id_short: str) -> None:
        """Delete an entry. No-op if missing."""
        data = self._read()
        if session_id_short not in data["sessions"]:
            return
        del data["sessions"][session_id_short]
        self._save_sessions(data["sessions"])

    def list_active(
        self,
        *,
        state: str | None = "active",
        older_than_days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return entries, optionally filtered by state and age.

        ``state="active"`` returns only active sessions; ``state="abandoned"``
        returns only abandoned; ``state=None`` returns all. ``older_than_days``
        filters by ``last_seen_at`` for active or ``abandoned_at`` for
        abandoned.
        """
        from datetime import datetime, timedelta, timezone

        entries = list(self._read()["sessions"].values())
        if state is not None:
            entries = [e for e in entries if e.get("state") == state]
        if older_than_days is not None and older_than_days >= 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

            def _older_than(entry: dict[str, Any]) -> bool:
                ts_field = (
                    "abandoned_at"
                    if entry.get("state") == "abandoned"
                    else "last_seen_at"
                )
                ts_str = entry.get(ts_field)
                if not ts_str:
                    return False
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    return False
                return ts < cutoff

            entries = [e for e in entries if _older_than(e)]
        return entries

    # ── Recovery ────────────────────────────────────────────────────

    def quarantine_corrupt_file(self) -> Path | None:
        """Move a corrupt registry file aside. Returns the new path or None."""
        if not self._path.exists():
            return None
        ts = utcnow_iso().replace(":", "-").replace(".", "-")
        backup = self._path.with_suffix(f".corrupt-{ts}")
        self._path.rename(backup)
        return backup


__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "SessionWorktreeRegistry",
    "_short_session_id",
]
