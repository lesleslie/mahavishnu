from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys

import pytest

from mahavishnu.hooks import jot_capture
from mahavishnu.jot.events import deserialize

# ---------------------------------------------------------------------------
# _is_capture
# ---------------------------------------------------------------------------


class TestIsCapture:
    def test_double_comma_with_text_is_capture(self) -> None:
        is_cap, body = jot_capture._is_capture(",, hello world")
        assert is_cap is True
        assert body == "hello world"

    def test_leading_whitespace_stripped_before_check(self) -> None:
        is_cap, body = jot_capture._is_capture("   ,, hello")
        assert is_cap is True
        assert body == "hello"

    def test_text_without_prefix_is_not_capture(self) -> None:
        is_cap, body = jot_capture._is_capture("hello world")
        assert is_cap is False
        assert body == ""

    def test_comma_comma_mid_text_is_not_capture(self) -> None:
        is_cap, body = jot_capture._is_capture("say ,, to me")
        assert is_cap is False
        assert body == ""

    def test_double_comma_with_empty_body_is_not_capture(self) -> None:
        is_cap1, _ = jot_capture._is_capture(",,")
        is_cap2, _ = jot_capture._is_capture(",, ")
        is_cap3, _ = jot_capture._is_capture(" ,,")
        assert is_cap1 is False
        assert is_cap2 is False
        assert is_cap3 is False

    def test_body_whitespace_stripped(self) -> None:
        is_cap, body = jot_capture._is_capture(",,   hello world")
        assert is_cap is True
        assert body == "hello world"


# ---------------------------------------------------------------------------
# _build_capture_ctx
# ---------------------------------------------------------------------------


class TestBuildCaptureCtx:
    def test_minimal_ctx(self) -> None:
        ctx = jot_capture._build_capture_ctx(
            stdin_payload={"prompt": ",, test", "session_id": "s1"},
            env={},
            cwd="/tmp",
        )
        assert ctx["cwd"] == "/tmp"
        assert ctx["session_id"] == "s1"
        assert ctx["files"] == []
        assert ctx["env_repo"] is None
        assert ctx["env_branch"] is None

    def test_full_ctx(self) -> None:
        ctx = jot_capture._build_capture_ctx(
            stdin_payload={
                "prompt": ",, test",
                "session_id": "s1",
                "files": ["a.py", "b.py"],
            },
            env={"MAHAVISHNU_REPO": "/r", "MAHAVISHNU_BRANCH": "main"},
            cwd="/work",
        )
        assert ctx == {
            "cwd": "/work",
            "session_id": "s1",
            "files": ["a.py", "b.py"],
            "env_repo": "/r",
            "env_branch": "main",
        }


# ---------------------------------------------------------------------------
# _do_hook — passthrough cases
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_passthrough_no_comma_comma(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": "hello world", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0
        assert json.loads(captured_stdout.getvalue()) == stdin_payload
        assert not (tmp_path / ".mahavishnu" / "jot" / "log.jsonl").exists()

    def test_passthrough_empty_body(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",,", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0
        assert not (tmp_path / ".mahavishnu" / "jot" / "log.jsonl").exists()


# ---------------------------------------------------------------------------
# _do_hook — capture success
# ---------------------------------------------------------------------------


class TestCapture:
    def test_capture_writes_event_and_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Successful capture: log file created with one event, exit 2, stderr echo."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",, hello world", "session_id": "sess_xyz"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)
        monkeypatch.setattr(sys, "stderr", captured_stderr)

        exit_code = jot_capture._do_hook()
        assert exit_code == 2
        assert captured_stdout.getvalue() == ""

        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        content = log.read_text()
        lines = [line for line in content.split("\n") if line.strip()]
        assert len(lines) == 1

        event = deserialize(lines[0])
        assert event.text == "hello world"
        assert event.op == "capture"
        assert event.ctx["session_id"] == "sess_xyz"

        stderr_text = captured_stderr.getvalue()
        assert "jot " in stderr_text
        assert "captured" in stderr_text

    def test_capture_redacts_secrets(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {
            "prompt": ",, my key is AKIAIOSFODNN7EXAMPLE",
            "session_id": "s1",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        jot_capture._do_hook()

        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        content = log.read_text()
        assert "AKIAIOSFODNN7EXAMPLE" not in content
        assert "[REDACTED:secret:" in content

    def test_capture_hlc_monotonic_across_calls(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        for i in range(3):
            stdin_payload = {"prompt": f",, jot {i}", "session_id": "s1"}
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
            monkeypatch.setattr(sys, "stdout", io.StringIO())
            monkeypatch.setattr(sys, "stderr", io.StringIO())
            jot_capture._do_hook()

        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        lines = [deserialize(line) for line in log.read_text().split("\n") if line.strip()]
        assert len(lines) == 3
        for prev, curr in zip(lines, lines[1:]):
            assert (curr.hlc.wall_ms, curr.hlc.ctr) > (prev.hlc.wall_ms, prev.hlc.ctr)


# ---------------------------------------------------------------------------
# B8: 300-char shape gate
# ---------------------------------------------------------------------------


class TestShapeGate:
    def test_long_body_captures_and_returns_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Body > 300 chars → capture written AND exit 0 (not 2)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        long_body = "x" * 350
        stdin_payload = {"prompt": f",, {long_body}", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)
        monkeypatch.setattr(sys, "stderr", captured_stderr)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

        # But the event IS in the log
        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        lines = [line for line in log.read_text().split("\n") if line.strip()]
        assert len(lines) == 1

    def test_multiline_body_captures_and_returns_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Body with '\\n' → capture AND exit 0."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        multiline = "line one\nline two\nline three"
        stdin_payload = {"prompt": f",, {multiline}", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)
        monkeypatch.setattr(sys, "stderr", captured_stderr)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()

    def test_short_body_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Short body (<300 chars, no \\n) → exit 2 (block prompt)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",, short jot", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        exit_code = jot_capture._do_hook()
        assert exit_code == 2


# ---------------------------------------------------------------------------
# B6: stderr-before-log ordering
# ---------------------------------------------------------------------------


class TestEchoBeforeLog:
    def test_stderr_failure_aborts_before_log_write(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If stderr fails, NO log entry should be written."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",, hello", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())

        # Replace stderr with a broken stream
        class BrokenStderr:
            def write(self, s: str) -> int:
                raise OSError(9, "Bad file descriptor")

            def flush(self) -> None:
                pass

        monkeypatch.setattr(sys, "stderr", BrokenStderr())

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

        # No log entry should exist
        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        assert not log.exists() or log.read_text() == ""


# ---------------------------------------------------------------------------
# H1: missing failure-mode tests
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_mkdir_permission_denied_passthrough(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """mkdir PermissionError → exit 0 + errors.log entry (H1)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        # Force jot_dir's mkdir to raise PermissionError
        from pathlib import Path as PathLib

        original_mkdir = PathLib.mkdir

        def fake_mkdir(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "jot" in str(self):
                raise PermissionError(13, "Permission denied", str(self))
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(PathLib, "mkdir", fake_mkdir)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

    def test_disk_full_on_write_passthrough(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ENOSPC on log write → exit 0 + errors.log entry (H1)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        # Patch _write_log_line directly to raise ENOSPC, simulating disk full.
        # This isolates the test to the log write path (not also affecting
        # node_init or errors.log writes).
        def failing_write_log_line(line: str) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(jot_capture, "_write_log_line", failing_write_log_line)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# Existing fail-open behavior (preserve + extend)
# ---------------------------------------------------------------------------


class TestFailOpen:
    def test_invalid_json_stdin_passthrough(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(sys, "stdin", io.StringIO("not valid json"))

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

        errors_log = tmp_path / ".mahavishnu" / "jot" / "errors.log"
        assert errors_log.exists()
        content = errors_log.read_text()
        assert "jot_capture" in content

    def test_missing_prompt_field_passthrough(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s1"})))
        captured_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0
        errors_log = tmp_path / ".mahavishnu" / "jot" / "errors.log"
        assert not errors_log.exists()

    def test_log_write_failure_passthrough(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        original_open = os.open

        def fake_open(path, flags, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "log.jsonl" in str(path):
                raise PermissionError(13, "Permission denied", str(path))
            return original_open(path, flags, mode, *args, **kwargs)

        monkeypatch.setattr(os, "open", fake_open)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_calls_do_hook_and_returns_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() invokes _do_hook() and returns its exit code as int.

        The `if __name__ == "__main__"` block at module level calls sys.exit(main()).
        When imported (e.g., from tests), main() just returns the int.
        """
        monkeypatch.setattr(jot_capture, "_do_hook", lambda: 2)
        assert jot_capture.main() == 2

    def test_main_returns_0_for_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jot_capture, "_do_hook", lambda: 0)
        assert jot_capture.main() == 0
