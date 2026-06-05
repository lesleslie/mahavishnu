"""Tests for ``scripts/cleanup_reflection_db.py``.

The script orchestrates three external systems: DuckDB, the OS process
table, and (optionally) the Session-Buddy MCP server. We mock all three
in unit tests so the suite stays hermetic and fast. A real end-to-end
test against an actual ``reflection.duckdb`` is out of scope; the
``--dry-run`` mode exists for that purpose.

What we exercise here:

- ``is_process_alive`` — the POSIX ``kill(pid, 0)`` probe semantics.
- ``validate_health_url`` — CWE-939 / CWE-295 hardening at the URL boundary.
- ``probe_lock`` — DuckDB error-message parsing into ``LockProbe``.
- ``shutdown_session_buddy`` — SIGTERM, escalation to SIGKILL, already-dead.
- ``run_checkpoint`` — vss detection and CHECKPOINT success / failure.
- ``force_release_lock`` — the full high-level orchestrator, including
  idempotency (no-op when the lock is already free).
- ``verify_health`` — happy path, timeout, non-200, and HTTP scheme only.
- CLI — ``--dry-run`` and ``--no-restart`` short-circuit the destructive steps.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ``scripts/`` is added to ``sys.path`` by the project pytest config
# (``pythonpath = ["."]`` in pyproject.toml). Import the script module
# directly so we test the public surface that the CLI also exercises.
import cleanup_reflection_db as crd
from cleanup_reflection_db import (
    ALLOWED_HEALTH_SCHEMES,
    CleanupResult,
    LockProbe,
    force_release_lock,
    is_process_alive,
    probe_lock,
    run_checkpoint,
    shutdown_session_buddy,
    validate_health_url,
    verify_health,
)


# ============================================================================
# is_process_alive
# ============================================================================


class TestIsProcessAlive:
    def test_returns_true_for_current_process(self) -> None:
        """``os.getpid()`` is the safest live PID we can test against."""
        assert is_process_alive(os.getpid()) is True

    def test_returns_false_for_very_high_pid(self) -> None:
        """PIDs are bounded; 999_999_999 is a safe dead value on every POSIX."""
        assert is_process_alive(999_999_999) is False

    def test_returns_true_on_permission_error(self) -> None:
        """``PermissionError`` means the PID exists but is owned by another
        user. We must not treat that as dead — otherwise the script would
        try to clean up a foreign process's lock and fail.
        """
        with patch("cleanup_reflection_db.os.kill", side_effect=PermissionError):
            assert is_process_alive(1) is True

    def test_returns_false_on_generic_oserror(self) -> None:
        with patch("cleanup_reflection_db.os.kill", side_effect=OSError("weird")):
            assert is_process_alive(12345) is False


# ============================================================================
# validate_health_url
# ============================================================================


class TestValidateHealthUrl:
    def test_accepts_http(self) -> None:
        assert validate_health_url("http://127.0.0.1:8678/health") == \
            "http://127.0.0.1:8678/health"

    def test_rejects_https(self) -> None:
        """HTTPS is intentionally disallowed — see ALLOWED_HEALTH_SCHEMES docstring.

        Health checks are local infrastructure probes, not external
        HTTPS endpoints; supporting HTTPS adds SSL-validation attack
        surface (CWE-295) with no real benefit.
        """
        with pytest.raises(ValueError, match="scheme='https'"):
            validate_health_url("https://example.com/health")

    def test_rejects_file_url(self) -> None:
        """CWE-939: urllib-style handlers accept file:// and would read
        arbitrary local files if we let them through.
        """
        with pytest.raises(ValueError, match="scheme='file'"):
            validate_health_url("file:///etc/passwd")

    def test_rejects_ftp(self) -> None:
        with pytest.raises(ValueError, match="scheme='ftp'"):
            validate_health_url("ftp://internal/whatever")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError):
            validate_health_url("")

    def test_scheme_check_is_case_insensitive(self) -> None:
        """``HTTP://`` is normalized to ``http`` and accepted. This matches
        URL scheme handling throughout the Python stdlib (``urlparse``,
        ``urllib``, etc.) and avoids surprising the operator who types
        a capitalised URL.
        """
        assert validate_health_url("HTTP://127.0.0.1/health") == \
            "HTTP://127.0.0.1/health"

    def test_allowed_schemes_constant_is_exactly_http(self) -> None:
        """Pin the policy: only http is allowed. If a future change adds
        https or file, this test will fail and force a deliberate update.
        """
        assert ALLOWED_HEALTH_SCHEMES == frozenset({"http"})


# ============================================================================
# probe_lock
# ============================================================================


class TestProbeLock:
    def test_returns_free_lock_when_db_opens(self, tmp_path: Path) -> None:
        """When duckdb.connect succeeds, the lock is free."""
        fake_db = tmp_path / "free.duckdb"
        # The probe will try to open this file; we mock duckdb to fake
        # success on the first call.
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_con = MagicMock()
            mock_duckdb.connect.return_value = mock_con
            mock_import.return_value = mock_duckdb
            result = probe_lock(fake_db)
        assert result == LockProbe(locked=False, holder_pid=None, stale=False)
        mock_con.close.assert_called_once()

    def test_extracts_pid_from_conflict_message(self) -> None:
        """When duckdb.connect raises, we parse (PID N) out of the message."""
        msg = (
            "IO Error: Could not set lock on file "
            '"/Users/les/.claude/data/reflection.duckdb": Conflicting '
            "lock is held in /usr/bin/python3 (PID 99935) by user les."
        )
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_duckdb.connect.side_effect = Exception(msg)
            mock_import.return_value = mock_duckdb
            with patch("cleanup_reflection_db.is_process_alive", return_value=True):
                result = probe_lock(Path("/tmp/whatever.duckdb"))
        assert result.locked is True
        assert result.holder_pid == 99935
        assert result.stale is False

    def test_marks_lock_holder_stale_when_process_dead(self) -> None:
        msg = "Conflicting lock is held in /usr/bin/python3 (PID 12345) by user les."
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_duckdb.connect.side_effect = Exception(msg)
            mock_import.return_value = mock_duckdb
            with patch("cleanup_reflection_db.is_process_alive", return_value=False):
                result = probe_lock(Path("/tmp/whatever.duckdb"))
        assert result.locked is True
        assert result.holder_pid == 12345
        assert result.stale is True

    def test_reraises_non_lock_errors(self) -> None:
        """Errors that don't look like a lock conflict propagate as-is."""
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_duckdb.connect.side_effect = Exception("Some other error")
            mock_import.return_value = mock_duckdb
            with pytest.raises(Exception, match="Some other error"):
                probe_lock(Path("/tmp/whatever.duckdb"))


# ============================================================================
# shutdown_session_buddy
# ============================================================================


class TestShutdownSessionBuddy:
    def test_returns_true_for_already_dead_process(self) -> None:
        with patch("cleanup_reflection_db.is_process_alive", return_value=False):
            assert shutdown_session_buddy(12345, log=lambda m: None) is True

    def test_returns_true_after_successful_sigterm(self) -> None:
        """The process dies immediately after SIGTERM."""
        with patch("cleanup_reflection_db.is_process_alive") as alive, \
             patch("cleanup_reflection_db.os.kill") as kill:
            alive.side_effect = [True, False]  # alive before, dead after
            assert shutdown_session_buddy(
                12345, timeout=5.0, log=lambda m: None
            ) is True
        kill.assert_called_once_with(12345, __import__("signal").SIGTERM)

    def test_escalates_to_sigkill_on_timeout(self) -> None:
        """If the process refuses to die after SIGTERM, we SIGKILL it.

        We assert on the signal sequence (the externally observable
        behavior) rather than the return value. With ``time.sleep``
        mocked, the spin loop is so fast that the real-time deadline
        elapses immediately, so the function reliably reaches the
        SIGKILL path. The post-SIGKILL ``is_process_alive`` check is
        unimportant for this test — what matters is that we *tried*
        SIGKILL, which is the only way out of an unresponsive process.
        """
        sent_signals: list[int] = []

        def fake_kill(pid, sig):
            sent_signals.append(sig)

        with patch("cleanup_reflection_db.is_process_alive", return_value=True), \
             patch("cleanup_reflection_db.os.kill", side_effect=fake_kill), \
             patch("cleanup_reflection_db.time.sleep"):
            # Tiny timeout so the test is fast. Return value is
            # intentionally not asserted — see docstring.
            shutdown_session_buddy(
                12345, timeout=0.01, log=lambda m: None
            )

        # SIGTERM (15) sent first; if process doesn't die, SIGKILL (9) follows.
        assert sent_signals[0] == 15
        assert 9 in sent_signals

    def test_returns_false_when_process_lingers(self) -> None:
        """Worst case: both signals sent and the process is still alive."""
        with patch("cleanup_reflection_db.is_process_alive", return_value=True), \
             patch("cleanup_reflection_db.os.kill"), \
             patch("cleanup_reflection_db.time.sleep"):
            assert shutdown_session_buddy(
                12345, timeout=0.01, log=lambda m: None
            ) is False

    def test_tolerates_processlookuperror_on_signal(self) -> None:
        """If the process dies between our probe and our kill, don't error."""
        with patch("cleanup_reflection_db.is_process_alive", return_value=True), \
             patch("cleanup_reflection_db.os.kill", side_effect=ProcessLookupError):
            assert shutdown_session_buddy(
                12345, timeout=5.0, log=lambda m: None
            ) is True


# ============================================================================
# run_checkpoint
# ============================================================================


class TestRunCheckpoint:
    def test_succeeds_when_no_vss_needed(self, tmp_path: Path) -> None:
        fake_db = tmp_path / "no_vss.duckdb"
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_con = MagicMock()
            mock_duckdb.connect.return_value = mock_con
            mock_import.return_value = mock_duckdb
            assert run_checkpoint(fake_db, log=lambda m: None) is True
        mock_con.execute.assert_any_call("CHECKPOINT")
        mock_con.close.assert_called_once()

    def test_loads_vss_when_hnsw_indexes_present(self, tmp_path: Path) -> None:
        fake_db = tmp_path / "with_hnsw.duckdb"
        # First CHECKPOINT call fails with HNSW error, then vss loads,
        # then second CHECKPOINT call succeeds.
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_con = MagicMock()
            mock_duckdb.connect.return_value = mock_con
            mock_import.return_value = mock_duckdb

            # First CHECKPOINT fails, second succeeds
            mock_con.execute.side_effect = [
                Exception("Cannot bind index 'x', unknown index type 'HNSW'"),
                None,  # INSTALL vss
                None,  # LOAD vss
                None,  # CHECKPOINT
            ]
            assert run_checkpoint(fake_db, log=lambda m: None) is True

        # Verify the sequence: CHECKPOINT, INSTALL, LOAD, CHECKPOINT
        sql_calls = [c.args[0] for c in mock_con.execute.call_args_list]
        assert sql_calls == ["CHECKPOINT", "INSTALL vss", "LOAD vss", "CHECKPOINT"]

    def test_returns_false_on_open_failure(self, tmp_path: Path) -> None:
        fake_db = tmp_path / "cant_open.duckdb"
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_duckdb.connect.side_effect = OSError("disk error")
            mock_import.return_value = mock_duckdb
            assert run_checkpoint(fake_db, log=lambda m: None) is False

    def test_returns_false_on_unrecoverable_checkpoint_failure(self, tmp_path: Path) -> None:
        """A non-HNSW error during CHECKPOINT propagates as failure."""
        fake_db = tmp_path / "broken.duckdb"
        with patch("cleanup_reflection_db._import_duckdb") as mock_import:
            mock_duckdb = MagicMock()
            mock_con = MagicMock()
            mock_duckdb.connect.return_value = mock_con
            mock_import.return_value = mock_duckdb
            mock_con.execute.side_effect = Exception("disk full")
            assert run_checkpoint(fake_db, log=lambda m: None) is False


# ============================================================================
# verify_health
# ============================================================================


def _payload_response(status: int = 200, body: str = '{"status": "ok"}') -> SimpleNamespace:
    """Build a minimal context-manager that mimics http.client response."""
    resp = SimpleNamespace(status=status)
    resp.read = lambda: body.encode("utf-8")
    return resp


class TestVerifyHealth:
    def test_succeeds_on_200_with_status_ok(self) -> None:
        fake_conn = MagicMock()
        fake_conn.getresponse.return_value = _payload_response(200, '{"status": "ok"}')
        with patch("cleanup_reflection_db._http_get_json", return_value={"status": "ok"}):
            assert verify_health(
                "http://127.0.0.1:8678/health",
                timeout_seconds=0.5,
                log=lambda m: None,
            ) is True

    def test_returns_false_on_timeout(self) -> None:
        with patch("cleanup_reflection_db._http_get_json", return_value=None), \
             patch("cleanup_reflection_db.time.sleep"):
            assert verify_health(
                "http://127.0.0.1:8678/health",
                timeout_seconds=0.1,
                log=lambda m: None,
            ) is False

    def test_returns_false_on_non_ok_status(self) -> None:
        with patch("cleanup_reflection_db._http_get_json", return_value={"status": "degraded"}):
            assert verify_health(
                "http://127.0.0.1:8678/health",
                timeout_seconds=0.1,
                log=lambda m: None,
            ) is False

    def test_raises_on_https_url(self) -> None:
        with pytest.raises(ValueError, match="scheme='https'"):
            verify_health("https://127.0.0.1:8678/health")

    def test_raises_on_file_url(self) -> None:
        with pytest.raises(ValueError, match="scheme='file'"):
            verify_health("file:///etc/passwd")


# ============================================================================
# force_release_lock (high-level orchestrator)
# ============================================================================


class TestForceReleaseLock:
    def test_is_noop_when_lock_is_free(self, tmp_path: Path) -> None:
        """Idempotency: if there's no lock, we do nothing and return cleanly."""
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(False, None, False)):
            result = force_release_lock(
                db_path=tmp_path / "x.duckdb",
                log=lambda m: None,
            )
        assert result.lock_was_held is False
        assert result.checkpoint_ok is True
        assert result.restart_attempted is False
        assert result.new_holder_pid is None

    def test_stops_live_holder_and_checkpoints(self, tmp_path: Path) -> None:
        """Live holder: we shut it down, then run CHECKPOINT."""
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 99935, False)), \
             patch.object(crd, "shutdown_session_buddy", return_value=True), \
             patch.object(crd, "run_checkpoint", return_value=True), \
             patch.object(crd, "restart_session_buddy", return_value=44411), \
             patch.object(crd, "verify_health", return_value=True), \
             patch.object(crd.time, "sleep"):
            result = force_release_lock(
                db_path=tmp_path / "x.duckdb",
                log=lambda m: None,
            )
        assert result.lock_was_held is True
        assert result.holder_pid == 99935
        assert result.holder_was_alive is True
        assert result.checkpoint_ok is True
        assert result.new_holder_pid is not None
        assert result.restart_attempted is True
        assert result.restart_ok is True
        assert result.health_ok is True

    def test_skips_shutdown_when_holder_is_stale(self, tmp_path: Path) -> None:
        """Stale PID: don't even try to kill, just CHECKPOINT and restart."""
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 12345, True)), \
             patch.object(crd, "shutdown_session_buddy") as mock_shutdown, \
             patch.object(crd, "run_checkpoint", return_value=True), \
             patch.object(crd, "restart_session_buddy", return_value=44411), \
             patch.object(crd, "verify_health", return_value=True), \
             patch.object(crd.time, "sleep"):
            result = force_release_lock(
                db_path=tmp_path / "x.duckdb",
                log=lambda m: None,
            )
        assert result.holder_was_alive is False
        assert result.checkpoint_ok is True
        mock_shutdown.assert_not_called()

    def test_aborts_when_shutdown_fails(self, tmp_path: Path) -> None:
        """If we can't kill the live process, we don't try to checkpoint."""
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 99935, False)), \
             patch.object(crd, "shutdown_session_buddy", return_value=False), \
             patch.object(crd, "run_checkpoint") as mock_ckpt:
            result = force_release_lock(
                db_path=tmp_path / "x.duckdb",
                log=lambda m: None,
            )
        assert result.checkpoint_ok is False
        mock_ckpt.assert_not_called()

    def test_no_restart_skips_restart_and_health_check(self, tmp_path: Path) -> None:
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 12345, True)), \
             patch.object(crd, "run_checkpoint", return_value=True), \
             patch.object(crd, "restart_session_buddy") as mock_restart, \
             patch.object(crd, "verify_health") as mock_health:
            result = force_release_lock(
                db_path=tmp_path / "x.duckdb",
                restart=False,
                log=lambda m: None,
            )
        assert result.restart_attempted is False
        assert result.restart_ok is None
        assert result.health_ok is None
        mock_restart.assert_not_called()
        mock_health.assert_not_called()


# ============================================================================
# CLI
# ============================================================================


class TestCLI:
    def test_dry_run_does_not_stop_or_checkpoint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--dry-run must not invoke any destructive subprocess."""
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 99935, True)), \
             patch.object(crd, "shutdown_session_buddy") as mock_shutdown, \
             patch.object(crd, "run_checkpoint") as mock_ckpt, \
             patch.object(crd, "restart_session_buddy") as mock_restart:
            rc = crd.main([
                "--db-path", str(tmp_path / "x.duckdb"),
                "--dry-run",
            ])
        assert rc == 0
        out = capsys.readouterr().err
        assert "DRY RUN" in out
        mock_shutdown.assert_not_called()
        mock_ckpt.assert_not_called()
        mock_restart.assert_not_called()

    def test_dry_run_with_no_lock_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(False, None, False)):
            rc = crd.main([
                "--db-path", str(tmp_path / "x.duckdb"),
                "--dry-run",
            ])
        assert rc == 0

    def test_no_restart_skips_restart_step(self, tmp_path: Path) -> None:
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 12345, True)), \
             patch.object(crd, "run_checkpoint", return_value=True), \
             patch.object(crd, "restart_session_buddy") as mock_restart, \
             patch.object(crd, "verify_health") as mock_health:
            rc = crd.main([
                "--db-path", str(tmp_path / "x.duckdb"),
                "--no-restart",
            ])
        assert rc == 0
        mock_restart.assert_not_called()
        mock_health.assert_not_called()

    def test_quiet_suppresses_all_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--quiet`` silences every ``log()`` call — progress and the
        final summary alike. Operators who want a one-line exit-code
        answer for scripting should use ``--quiet``.
        """
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(False, None, False)):
            rc = crd.main([
                "--db-path", str(tmp_path / "x.duckdb"),
                "--quiet",
            ])
        assert rc == 0
        out = capsys.readouterr().err
        assert "Probing" not in out
        assert "Cleanup complete" not in out
        assert out == ""

    def test_nonzero_exit_on_checkpoint_failure(self, tmp_path: Path) -> None:
        with patch.object(crd, "probe_lock",
                          return_value=LockProbe(True, 12345, True)), \
             patch.object(crd, "run_checkpoint", return_value=False):
            rc = crd.main([
                "--db-path", str(tmp_path / "x.duckdb"),
                "--no-restart",
            ])
        assert rc == 1

    def test_https_health_url_rejected_by_parser(self) -> None:
        """The CLI parser must reject https:// before we ever open a socket."""
        with pytest.raises(SystemExit):
            crd.main([
                "--db-path", "/tmp/x.duckdb",
                "--health-url", "https://example.com/health",
                "--dry-run",
            ])


# ============================================================================
# CleanupResult
# ============================================================================


class TestCleanupResult:
    def test_ok_true_when_all_stages_succeed(self) -> None:
        r = CleanupResult(
            lock_was_held=True,
            holder_pid=12345,
            holder_was_alive=True,
            checkpoint_ok=True,
            new_holder_pid=99,
            restart_attempted=True,
            restart_ok=True,
            health_ok=True,
            duration_seconds=1.0,
        )
        assert r.ok is True

    def test_ok_false_when_checkpoint_failed(self) -> None:
        r = CleanupResult(
            lock_was_held=True,
            holder_pid=12345,
            holder_was_alive=True,
            checkpoint_ok=False,
            new_holder_pid=None,
            restart_attempted=False,
            restart_ok=None,
            health_ok=None,
            duration_seconds=0.5,
        )
        assert r.ok is False

    def test_ok_false_when_restart_failed(self) -> None:
        r = CleanupResult(
            lock_was_held=True,
            holder_pid=12345,
            holder_was_alive=True,
            checkpoint_ok=True,
            new_holder_pid=99,
            restart_attempted=True,
            restart_ok=False,
            health_ok=None,
            duration_seconds=2.0,
        )
        assert r.ok is False

    def test_ok_true_when_no_lock_no_stages_ran(self) -> None:
        """The 'no lock to clean' path is trivially OK."""
        r = CleanupResult(
            lock_was_held=False,
            holder_pid=None,
            holder_was_alive=False,
            checkpoint_ok=True,
            new_holder_pid=None,
            restart_attempted=False,
            restart_ok=None,
            health_ok=None,
            duration_seconds=0.1,
        )
        assert r.ok is True
