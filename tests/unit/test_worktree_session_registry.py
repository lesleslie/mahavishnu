"""Unit tests for ``mahavishnu.core.worktree_session_registry``.

Pins the contract for the SessionWorktreeRegistry class:
- CRUD semantics (register, get, mark_abandoned, remove, list_active)
- Idempotency on re-register (refreshes ``last_seen_at``, preserves created_at)
- Schema migration policy (newer versions + corrupt JSON)
- Symlink-rejection on write (CWE-59 mitigation)
- chmod 0o600 / 0o700 hardening at first write
"""
from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 — type-only with __future__ annotations
import uuid

import pytest

from mahavishnu.core.worktree_session_registry import (
    SUPPORTED_SCHEMA_VERSION,
    SessionWorktreeRegistry,
    short_session_id,
)


@pytest.fixture
def registry(tmp_path: Path) -> SessionWorktreeRegistry:
    """A registry pointed at a per-test temp file (no XDG side-effects)."""
    return SessionWorktreeRegistry(path=tmp_path / "session-worktrees.json")


def _sample_metadata() -> dict:
    return {"hook_pid": 1234, "claude_session_id_full": "0190f8a4-b9c1-7def-a012-3456789abcde"}


def _register_sample(registry: SessionWorktreeRegistry, key: str) -> None:
    registry.register(
        session_id_short=key,
        worktree_path=f"/Users/les/worktrees/agent-{key}",
        branch=f"worktree-agent-{key}",
        repo_path="/Users/les/Projects/mahavishnu",
        repo_nickname="mahavishnu",
        metadata=_sample_metadata(),
    )


# ── short_session_id ────────────────────────────────────────────


def test_short_session_id_first_8_hex_of_valid_uuid() -> None:
    """Valid UUID: returns the first 8 hex chars."""
    full = "0190f8a4-b9c1-7def-a012-3456789abcde"
    assert short_session_id(full) == "0190f8a4"


def test_short_session_id_returns_empty_for_invalid_uuid() -> None:
    """Malformed input returns empty string (fail-closed)."""
    for bad in ("", "not-a-uuid", "12345", None, "abc-def"):
        assert short_session_id(bad) == ""


# ── register ─────────────────────────────────────────────────────


def test_register_creates_entry(registry: SessionWorktreeRegistry) -> None:
    """Empty registry: register creates the file with the entry."""
    _register_sample(registry, "a0c5d2a0")
    assert registry.path.exists()
    record = registry.get("a0c5d2a0")
    assert record is not None
    assert record["worktree_path"] == "/Users/les/worktrees/agent-a0c5d2a0"
    assert record["branch"] == "worktree-agent-a0c5d2a0"
    assert record["state"] == "active"


def test_register_is_idempotent_and_refreshes_last_seen_at(
    registry: SessionWorktreeRegistry,
) -> None:
    """Re-registering the same key preserves created_at and refreshes last_seen_at."""
    _register_sample(registry, "a0c5d2a0")
    first = registry.get("a0c5d2a0")
    created_at_first = first["created_at"]

    # Sleep so timestamps would differ if last_seen_at gets refreshed.
    import time

    time.sleep(0.05)

    _register_sample(registry, "a0c5d2a0")
    second = registry.get("a0c5d2a0")
    assert second["created_at"] == created_at_first, "created_at must be preserved"
    assert second["last_seen_at"] != first["last_seen_at"], (
        "last_seen_at must be refreshed on re-register"
    )


def test_register_empty_short_id_raises(registry: SessionWorktreeRegistry) -> None:
    """Empty ``session_id_short`` is a hard error — no silent coerce."""
    with pytest.raises(ValueError, match="session_id_short"):
        registry.register(
            session_id_short="",
            worktree_path="/x",
            branch="b",
            repo_path="/r",
            repo_nickname="r",
        )


def test_register_sets_chmod_0600_on_file_and_0700_on_parent(
    registry: SessionWorktreeRegistry, tmp_path: Path
) -> None:
    """First write hardens permissions to deny world-read."""
    _register_sample(registry, "a0c5d2a0")
    file_mode = registry.path.stat().st_mode & 0o777
    parent_mode = registry.path.parent.stat().st_mode & 0o777
    assert file_mode == 0o600, f"file mode {oct(file_mode)}"
    assert parent_mode == 0o700, f"parent mode {oct(parent_mode)}"


def test_register_refuses_symlink_target(
    registry: SessionWorktreeRegistry, tmp_path: Path
) -> None:
    """Pre-planted symlink at the registry path is rejected (CWE-59)."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    target = real_dir / "real.json"
    target.write_text("{}")
    # Replace the (empty) registry path with a symlink to an outside file.
    if registry._path.exists() or registry._path.is_symlink():
        registry._path.unlink()
    registry._path.symlink_to(target)

    with pytest.raises(OSError):
        _register_sample(registry, "a0c5d2a0")


# ── get ──────────────────────────────────────────────────────────


def test_get_unknown_returns_none(registry: SessionWorktreeRegistry) -> None:
    """Missing key returns None, not KeyError."""
    assert registry.get("nope") is None


# ── mark_abandoned ───────────────────────────────────────────────


def test_mark_abandoned_flips_state_and_sets_timestamp(
    registry: SessionWorktreeRegistry,
) -> None:
    """Active → abandoned; ``abandoned_at`` populated."""
    _register_sample(registry, "a0c5d2a0")
    registry.mark_abandoned("a0c5d2a0")
    record = registry.get("a0c5d2a0")
    assert record["state"] == "abandoned"
    assert record["abandoned_at"] is not None
    assert record["abandoned_at"].endswith("Z")  # UTC ISO with Z


def test_mark_abandoned_unknown_key_is_noop(
    registry: SessionWorktreeRegistry,
) -> None:
    """Missing key: no error, no write side-effects."""
    registry.mark_abandoned("never-existed")
    # No exception, no file created (registry was empty to start).
    assert not registry.path.exists()


# ── remove ───────────────────────────────────────────────────────


def test_remove_deletes_entry(registry: SessionWorktreeRegistry) -> None:
    """Remove drops the entry; subsequent get returns None."""
    _register_sample(registry, "a0c5d2a0")
    registry.remove("a0c5d2a0")
    assert registry.get("a0c5d2a0") is None


def test_remove_unknown_is_noop(registry: SessionWorktreeRegistry) -> None:
    """Removing a key that never existed is a no-op, no error."""
    registry.remove("never-existed")  # does not raise


# ── Phase B: edge cases (Test review #7, #8, #9) ────────────────────


def test_corrupt_json_quarantine_end_to_end(
    registry: SessionWorktreeRegistry, tmp_path: Path
) -> None:
    """End-to-end recovery: corrupt JSON → quarantine → fresh read.

    Per Test review #7 (2026-07-20): the existing tests only proved
    that corrupt JSON raises JSONDecodeError and that quarantine
    renames a file. The integrated path (catch → quarantine → fresh
    read succeeds) was not pinned.
    """
    import json

    import pytest as _pytest

    # Write corrupt JSON
    registry.path.write_text("{this is not json")

    # Read raises JSONDecodeError
    with _pytest.raises(json.JSONDecodeError):
        registry.get("anything")

    # Caller quarantines, then reads fresh (empty)
    backup = registry.quarantine_corrupt_file()
    assert backup is not None
    assert backup.exists()
    assert not registry.path.exists()
    assert registry.get("anything") is None

    # Now register a new entry succeeds against the fresh empty registry.
    _register_sample(registry, "fresh")
    assert registry.get("fresh") is not None


def test_quarantine_corrupt_file_missing_path(
    tmp_path: Path,
) -> None:
    """quarantine_corrupt_file on a missing path → None (no error).

    Per Test review #7 (2026-07-20): missing-file branch was
    untested.
    """
    registry = SessionWorktreeRegistry(path=tmp_path / "nope.json")
    assert registry.quarantine_corrupt_file() is None


def test_older_schema_version_is_read_only(
    registry: SessionWorktreeRegistry,
) -> None:
    """schema_version < SUPPORTED → empty read-only registry.

    Per Test review #8 (2026-07-20): the older-version branch was
    untested. Mirrors the future-version branch: refuse to write.
    """
    import json

    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps({
        "schema_version": SUPPORTED_SCHEMA_VERSION - 1,  # hypothetical v0
        "updated_at": "2026-07-01T00:00:00.000Z",
        "sessions": {"legacy": {"state": "active"}},
    }))

    assert registry.get("legacy") is None  # read returns empty

    # Write attempt is a no-op
    _register_sample(registry, "new")
    # File is NOT modified
    data = json.loads(registry.path.read_text())
    assert data["schema_version"] == SUPPORTED_SCHEMA_VERSION - 1


def test_missing_schema_version_is_writable(
    registry: SessionWorktreeRegistry,
) -> None:
    """Missing schema_version → legacy file, treated as writable.

    Per Test review #8 (2026-07-20): missing-version branch was
    untested.
    """
    import json

    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps({
        "updated_at": "2026-07-01T00:00:00.000Z",
        "sessions": {},
    }))

    # Write should normalize schema_version
    _register_sample(registry, "x")
    data = json.loads(registry.path.read_text())
    assert data["schema_version"] == SUPPORTED_SCHEMA_VERSION


def test_non_dict_sessions_treated_as_empty(
    registry: SessionWorktreeRegistry,
) -> None:
    """``sessions`` field is a list (not dict) → empty registry, writable.

    Per Test review #8 (2026-07-20): wrong-shape branch was untested.
    """
    import json

    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps({
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "updated_at": "2026-07-01T00:00:00.000Z",
        "sessions": ["not", "a", "dict"],
    }))

    assert registry.get("anything") is None  # empty
    _register_sample(registry, "x")  # writable
    assert registry.get("x") is not None


def test_string_schema_version_is_read_only(
    registry: SessionWorktreeRegistry,
) -> None:
    """``schema_version`` is a string instead of int → refuse to write.

    Per Test review #8 (2026-07-20): wrong-type branch was untested.
    Previously this could raise TypeError on comparison; we now treat
    it as unknown-version → read-only.
    """
    import json

    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps({
        "schema_version": "one",  # string instead of int
        "updated_at": "2026-07-01T00:00:00.000Z",
        "sessions": {},
    }))

    # Read returns empty (no crash)
    assert registry.get("anything") is None

    # Write is a no-op (no crash)
    _register_sample(registry, "x")
    # File should be unchanged
    data = json.loads(registry.path.read_text())
    assert data["schema_version"] == "one"


def test_unsupported_schema_version_logs_stderr_diagnostic(
    registry: SessionWorktreeRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unknown schema_version → refuse to write + emit one-line stderr.

    Per Security audit finding #4 (2026-07-20): the silent read-only
    behavior is a DoS-with-no-diagnostic. Operators should see WHY
    writes are being refused.
    """
    import json

    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(json.dumps({
        "schema_version": 999,  # way newer than supported
        "updated_at": "2026-07-01T00:00:00.000Z",
        "sessions": {},
    }))

    # Read triggers the diagnostic
    registry.get("anything")
    err = capsys.readouterr().err
    assert "refusing to write" in err
    assert "schema_version=999" in err


def test_age_filter_older_than_days_active(
    registry: SessionWorktreeRegistry,
) -> None:
    """older_than_days filters active entries by last_seen_at.

    Per Test review #9 (2026-07-20): age filter behavior was
    untested. Uses monkeypatched utcnow_iso for determinism.
    """


    _register_sample(registry, "old")
    # Backdate last_seen_at via direct manipulation
    data = json.loads(registry.path.read_text())
    data["sessions"]["old"]["last_seen_at"] = "2020-01-01T00:00:00.000Z"
    registry.path.write_text(json.dumps(data))

    _register_sample(registry, "new")  # last_seen_at = now

    # older_than_days=30 days, only "old" qualifies (year 2020 vs now)
    old_entries = registry.list_active(
        state="active", older_than_days=30
    )
    assert {e["session_id_short"] for e in old_entries} == {"old"}


def test_age_filter_older_than_days_abandoned(
    registry: SessionWorktreeRegistry,
) -> None:
    """older_than_days filters abandoned entries by abandoned_at."""

    # Register and abandon with a backdated timestamp
    _register_sample(registry, "x")
    registry.mark_abandoned("x", abandoned_at="2020-01-01T00:00:00.000Z")

    old_entries = registry.list_active(
        state="abandoned", older_than_days=30
    )
    assert {e["session_id_short"] for e in old_entries} == {"x"}


def test_age_filter_older_than_days_zero(
    registry: SessionWorktreeRegistry,
) -> None:
    """older_than_days=0 → all entries older than now qualify (i.e., all)."""

    _register_sample(registry, "a")
    _register_sample(registry, "b")
    registry.mark_abandoned("a", abandoned_at="2020-01-01T00:00:00.000Z")
    registry.mark_abandoned("b", abandoned_at="2020-01-01T00:00:00.000Z")

    pruned = registry.list_active(state="abandoned", older_than_days=0)
    assert {e["session_id_short"] for e in pruned} == {"a", "b"}


def test_age_filter_negative_treated_as_no_filter(
    registry: SessionWorktreeRegistry,
) -> None:
    """older_than_days=-1 → treated as no filter (matches all)."""
    _register_sample(registry, "a")
    registry.mark_abandoned("a")

    all_entries = registry.list_active(
        state="abandoned", older_than_days=-1
    )
    assert {e["session_id_short"] for e in all_entries} == {"a"}


def test_age_filter_invalid_timestamp_returns_false(
    registry: SessionWorktreeRegistry,
) -> None:
    """Malformed timestamp on an entry → entry is excluded, no crash."""
    import json

    _register_sample(registry, "broken")
    data = json.loads(registry.path.read_text())
    data["sessions"]["broken"]["last_seen_at"] = "not-an-iso-timestamp"
    registry.path.write_text(json.dumps(data))

    # No exception; broken entry excluded from older-than-1-days filter.
    old_entries = registry.list_active(state="active", older_than_days=1)
    assert {e["session_id_short"] for e in old_entries} == set()


# ── list_active ─────────────────────────────────────────────────


def test_list_active_returns_only_active_by_default(
    registry: SessionWorktreeRegistry,
) -> None:
    """Default ``state="active"`` excludes abandoned."""
    _register_sample(registry, "a0c5d2a0")
    _register_sample(registry, "b1d6e3f1")
    registry.mark_abandoned("b1d6e3f1")

    active = registry.list_active()
    assert [e["session_id_short"] for e in active] == ["a0c5d2a0"]


def test_list_active_state_none_returns_all(
    registry: SessionWorktreeRegistry,
) -> None:
    """``state=None`` returns both active and abandoned."""
    _register_sample(registry, "a0c5d2a0")
    _register_sample(registry, "b1d6e3f1")
    registry.mark_abandoned("b1d6e3f1")

    assert {e["session_id_short"] for e in registry.list_active(state=None)} == {
        "a0c5d2a0",
        "b1d6e3f1",
    }


# ── Schema migration policy ──────────────────────────────────────


def test_future_schema_version_returns_empty_no_write(
    registry: SessionWorktreeRegistry,
) -> None:
    """File with schema_version > supported → empty registry, no writes."""
    future_version = SUPPORTED_SCHEMA_VERSION + 10
    registry.path.write_text(
        json.dumps(
            {
                "schema_version": future_version,
                "sessions": {
                    "a0c5d2a0": {"worktree_path": "/etc/cron.d/foo"}
                },
            }
        )
    )
    # Reading should return None (no session visible).
    assert registry.get("a0c5d2a0") is None

    # Writing should not overwrite the unknown-version file.
    _register_sample(registry, "a0c5d2a0")
    data = json.loads(registry.path.read_text())
    assert data["schema_version"] == future_version, (
        "unknown-version file must NOT be overwritten"
    )


def test_corrupt_json_raises_for_caller_to_quarantine(
    registry: SessionWorktreeRegistry,
) -> None:
    """Corrupt JSON raises — caller decides quarantine policy."""
    registry.path.write_text("this is not json {{{")
    with pytest.raises(json.JSONDecodeError):
        registry.get("anything")


def test_quarantine_corrupt_file_renames_and_returns_backup(
    registry: SessionWorktreeRegistry,
) -> None:
    """``quarantine_corrupt_file`` returns the backup path and moves the file aside."""
    registry.path.write_text("not json")
    backup = registry.quarantine_corrupt_file()
    assert backup is not None
    assert backup.exists()
    assert not registry.path.exists()
    assert ".corrupt-" in backup.name


# ── short_session_id ────────────────────────────────────────────


def testshort_session_id_distinct_across_uuids() -> None:
    """Different UUIDs produce different short ids (collision check)."""
    seen = set()
    for i in range(100):
        u = uuid.uuid4()
        short = short_session_id(str(u))
        assert short not in seen, f"collision on {u} -> {short}"
        seen.add(short)
        assert len(short) == 8
