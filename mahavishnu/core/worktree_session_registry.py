"""Registry mapping Claude session_id → worktree_path.

Persistent JSON-backed store for which Claude session is using which
git worktree. Backed by ``mahavishnu.core.json_state_store`` primitives
(single source of truth for flock + atomic-write — per the 4-lens
plan review, 2026-07-16; reinforced by the multi-agent review
2026-07-20).

Used by:

- ``.claude/hooks/worktree-session-isolation.py`` (the SessionStart
  hook that auto-provisions a worktree when ``MAHAVISHNU_AUTO_WORKTREE=1``)
- ``mahavishnu worktree list-sessions`` (CLI for users to inspect
  which sessions are using which worktrees)
- ``mahavishnu worktree prune-abandoned`` (CLI to clean up dead
  worktrees per the never-auto-remove policy)

Schema migration policy (per multi-agent review, 2026-07-20):

- **schema_version > supported**: ``_read_only`` is set; all writes are
  no-ops via ``SKIP_WRITE``. Caller can ``quarantine_corrupt_file()``
  if the data is corrupt, but a future-version file is left intact.
- **schema_version < supported**: same treatment — ``_read_only`` set,
  no migration yet (no v0 → v1 migration function exists).
- **corrupt JSON**: caller decides whether to quarantine. The
  registry exposes ``quarantine_corrupt_file()`` for this purpose.

Security hardening:

- File written with ``chmod 0o600``, parent ``chmod 0o700``.
- ``O_NOFOLLOW`` on open (read + lockfile) — CWE-59 mitigation.
- ``flock`` (``LOCK_EX``) on a sidecar ``.lock`` file holds across the
  full read-modify-write — fixes the lost-update race that the prior
  ``_read`` + ``_save_sessions`` pattern had.
- POSIX-only — mahavishnu is Unix-targeted by posture.

Failure modes: returns empty registry (no exception) when the file
is missing or schema is unrecognized; the caller decides whether to
proceed. Crashes during write are cleaned up (the temp file is removed
on exception).
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — type-only with __future__ annotations
import shutil
from typing import Any
import uuid

from mahavishnu.core.json_state_store import (
    SKIP_WRITE,
    locked_json_modify,
    locked_json_read,
    utcnow_iso,
)
from mahavishnu.core.paths import get_state_path

SUPPORTED_SCHEMA_VERSION = 1


def short_session_id(session_id_full: str) -> str:
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

    Note: previously named ``_short_session_id`` with a leading
    underscore; renamed in 2026-07-20 per Architecture review #3 to
    reflect the public API status (the hook imports it across a
    module boundary).
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

        Honors schema_version: if the file declares a version different
        from ``SUPPORTED_SCHEMA_VERSION``, sets ``self._read_only = True``
        so subsequent writes are rejected (no overwriting of an
        unknown-version file) and emits a one-line stderr diagnostic
        so the operator can see why writes are being refused (rather
        than a silent DoS — per Security audit finding #4, 2026-07-20).
        """
        import sys

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
        if version != SUPPORTED_SCHEMA_VERSION:
            if isinstance(version, int):
                direction = "newer" if version > SUPPORTED_SCHEMA_VERSION else "older"
            else:
                # Non-integer schema_version (e.g. string, list) — can't
                # meaningfully compare; treat as "unknown" version.
                direction = "unknown"
            sys.stderr.write(
                f"mahavishnu: refusing to write — registry file declares "
                f"schema_version={version!r}, this build supports "
                f"v{SUPPORTED_SCHEMA_VERSION} ({direction}). "
                f"See docs/CONFIGURATION.md or upgrade.\n"
            )
            sys.stderr.flush()
            # Future, legacy, or malformed version — refuse to write until
            # the file is migrated or removed.
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

    @staticmethod
    def _normalize_sessions(data: dict[str, Any]) -> None:
        """Ensure ``data["sessions"]`` is a dict (in-place normalization).

        Files written by older versions or with corrupt shapes may
        have ``sessions`` as a list, None, or another non-dict type.
        Per Test review #8 (2026-07-20): the modifier path assumed
        ``sessions`` is always a dict and would ``AttributeError`` on
        non-dict shapes. Normalizing to ``{}`` makes writes idempotent
        and self-healing for these corrupt-but-recoverable cases.
        """
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            data["sessions"] = {}

    @staticmethod
    def _finalize_envelope(data: dict[str, Any]) -> dict[str, Any]:
        """Stamp ``schema_version`` and ``updated_at`` on the top-level envelope.

        In-place normalization. Called from each modifier before
        returning so the written file always has the current schema
        version and timestamp, regardless of what was on disk.
        """
        data["schema_version"] = SUPPORTED_SCHEMA_VERSION
        data["updated_at"] = utcnow_iso()
        return data

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
        """Insert or refresh an entry. Idempotent — refreshes ``last_seen_at``.

        Atomic across processes: the entire read-modify-write is held
        under a single ``LOCK_EX`` on ``<path>.lock``. This fixes the
        lost-update race where two concurrent registrations could both
        read the same baseline and the latter's write would clobber
        the former's entry.
        """
        if not session_id_short:
            raise ValueError("session_id_short must be non-empty")

        def modifier(
            data: dict[str, Any] | list[Any] | None,
        ) -> dict[str, Any] | list[Any] | object:
            if not isinstance(data, dict):
                return SKIP_WRITE
            version = data.get("schema_version")
            if version is not None and version != SUPPORTED_SCHEMA_VERSION:
                self._read_only = True
                return SKIP_WRITE
            self._normalize_sessions(data)
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
            self._finalize_envelope(data)
            return data

        locked_json_modify(self._path, modifier, default_factory=self._empty)

    def get(self, session_id_short: str) -> dict[str, Any] | None:
        """Return the entry for ``session_id_short`` or ``None``."""
        return self._read()["sessions"].get(session_id_short)

    def mark_abandoned(self, session_id_short: str, abandoned_at: str | None = None) -> None:
        """Flip an entry's state to ``"abandoned"``. No-op if missing or read-only."""

        def modifier(
            data: dict[str, Any] | list[Any] | None,
        ) -> dict[str, Any] | list[Any] | object:
            if not isinstance(data, dict):
                return SKIP_WRITE
            version = data.get("schema_version")
            if version is not None and version != SUPPORTED_SCHEMA_VERSION:
                self._read_only = True
                return SKIP_WRITE
            self._normalize_sessions(data)
            record = data["sessions"].get(session_id_short)
            if record is None:
                return SKIP_WRITE  # nothing to update; skip write
            record["state"] = "abandoned"
            record["abandoned_at"] = abandoned_at or utcnow_iso()
            data["sessions"][session_id_short] = record
            self._finalize_envelope(data)
            return data

        locked_json_modify(self._path, modifier, default_factory=self._empty)

    def remove(self, session_id_short: str) -> None:
        """Delete an entry. No-op if missing or read-only."""

        def modifier(
            data: dict[str, Any] | list[Any] | None,
        ) -> dict[str, Any] | list[Any] | object:
            if not isinstance(data, dict):
                return SKIP_WRITE
            version = data.get("schema_version")
            if version is not None and version != SUPPORTED_SCHEMA_VERSION:
                self._read_only = True
                return SKIP_WRITE
            self._normalize_sessions(data)
            if session_id_short not in data["sessions"]:
                return SKIP_WRITE  # nothing to update; skip write
            del data["sessions"][session_id_short]
            self._finalize_envelope(data)
            return data

        locked_json_modify(self._path, modifier, default_factory=self._empty)

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
        from datetime import UTC, datetime, timedelta

        entries = list(self._read()["sessions"].values())
        if state is not None:
            entries = [e for e in entries if e.get("state") == state]
        if older_than_days is not None and older_than_days >= 0:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

            def _older_than(entry: dict[str, Any]) -> bool:
                ts_field = "abandoned_at" if entry.get("state") == "abandoned" else "last_seen_at"
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
        """Move a corrupt registry file aside. Returns the new path or None.

        Uses ``shutil.move`` (handles cross-device moves transparently)
        rather than ``Path.rename`` (raises ``OSError(EXDEV)`` if the
        backup path resolves to a different filesystem). Per the
        multi-agent review (Architecture #6), the prior implementation
        could crash on cross-device quarantine attempts, defeating the
        recovery guarantee.
        """
        if not self._path.exists():
            return None
        ts = utcnow_iso().replace(":", "-").replace(".", "-")
        backup = self._path.with_suffix(f".corrupt-{ts}")
        shutil.move(str(self._path), str(backup))
        return backup


__all__ = [
    "SUPPORTED_SCHEMA_VERSION",
    "SessionWorktreeRegistry",
    "short_session_id",
]
