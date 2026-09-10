from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

HOOK_PATH = Path(__file__).parents[3] / "mahavishnu" / "hooks" / "jot_capture.py"


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set HOME to tmp_path so ~/.mahavishnu/jot/ resolves there."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _run_hook(stdin_payload: dict, isolated_home_path: Path) -> subprocess.CompletedProcess:
    """Spawn the hook as a subprocess with the given stdin payload."""
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(isolated_home_path)},
    )


class TestSubprocess:
    def test_capture_happy_path(self, isolated_home: Path) -> None:
        stdin_payload = {"prompt": ",, hello from subprocess", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 2
        assert result.stdout == ""
        assert "jot " in result.stderr
        assert "captured" in result.stderr

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        lines = [line for line in log.read_text().split("\n") if line.strip()]
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["text"] == "hello from subprocess"

    def test_passthrough_no_prefix(self, isolated_home: Path) -> None:
        stdin_payload = {"prompt": "just a normal prompt", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 0
        assert json.loads(result.stdout) == stdin_payload

    def test_passthrough_empty_body(self, isolated_home: Path) -> None:
        stdin_payload = {"prompt": ",,", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 0
        assert not (isolated_home / ".mahavishnu" / "jot" / "log.jsonl").exists()

    def test_invalid_json_stdin_fails_open(self, isolated_home: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="this is not valid json",
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "HOME": str(isolated_home)},
        )

        assert result.returncode == 0

        errors_log = isolated_home / ".mahavishnu" / "jot" / "errors.log"
        assert errors_log.exists()
        content = errors_log.read_text()
        assert "jot_capture" in content

    def test_directory_created_with_0o700(self, isolated_home: Path) -> None:
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        _run_hook(stdin_payload, isolated_home)

        jot_dir = isolated_home / ".mahavishnu" / "jot"
        mode = stat.S_IMODE(jot_dir.stat().st_mode)
        assert mode == 0o700

    def test_log_file_created_with_0o600(self, isolated_home: Path) -> None:
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        _run_hook(stdin_payload, isolated_home)

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        mode = stat.S_IMODE(log.stat().st_mode)
        assert mode == 0o600

    def test_multiple_captures_monotonic_hlc(self, isolated_home: Path) -> None:
        for i in range(3):
            stdin_payload = {"prompt": f",, jot {i}", "session_id": "s1"}
            _run_hook(stdin_payload, isolated_home)

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        lines = [json.loads(line) for line in log.read_text().split("\n") if line.strip()]
        assert len(lines) == 3
        for prev, curr in zip(lines, lines[1:]):
            prev_hlc = prev["hlc"]
            curr_hlc = curr["hlc"]
            assert (curr_hlc["wall_ms"], curr_hlc["ctr"]) > (
                prev_hlc["wall_ms"],
                prev_hlc["ctr"],
            )

    def test_shape_gate_long_body_returns_0(self, isolated_home: Path) -> None:
        """B8: long body (>300 chars) → exit 0 AND log entry written."""
        long_body = "x" * 350
        stdin_payload = {"prompt": f",, {long_body}", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 0

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        lines = [line for line in log.read_text().split("\n") if line.strip()]
        assert len(lines) == 1
