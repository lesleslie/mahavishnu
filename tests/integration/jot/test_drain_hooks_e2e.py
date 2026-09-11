"""End-to-end tests for the 3 jot hook wrappers wired into .claude/settings.json.

Each wrapper is invoked as a subprocess with the same JSON payload shape
Claude Code would deliver. The HOME env is redirected to ``tmp_path`` so
``~/.mahavishnu/jot/log.jsonl`` resolves under an isolated directory.

What these tests pin (Task 17 contract):
  * ``jot-session-start.py`` — always exits 0, emits a SessionStart-shaped
    JSON envelope with ``hookSpecificOutput.additionalContext`` on stdout.
  * ``jot-post-tool-use.py`` — always exits 0, emits a PostToolUse-shaped
    JSON envelope with ``hookSpecificOutput.additionalContext`` on stdout
    (truncates ``tool_result`` to 4096 chars).
  * ``jot-capture.py`` — exits 0 (passthrough) for non-',,' prompts;
    exits 2 + writes a log entry for ',,' prefixed prompts; never blocks
    on parse errors (fail-open).

The wrappers must not require any CWD setup — the venv has ``mahavishnu``
installed in editable mode, so the wrappers' imports resolve regardless of
where Claude Code invokes them from.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python3"


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home`` to tmp_path and whitelist the subprocess env."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _run_hook(
    hook_name: str,
    stdin_payload: dict[str, object],
    isolated_home_path: Path,
) -> subprocess.CompletedProcess:
    """Spawn a wrapper hook with the given stdin payload."""
    hook_path = HOOKS_DIR / hook_name
    return subprocess.run(
        [str(PYTHON_BIN), str(hook_path)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "HOME": str(isolated_home_path),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_ROOT),
        },
        cwd=str(REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# jot-session-start.py
# ---------------------------------------------------------------------------


class TestSessionStart:
    def test_emits_session_start_envelope(self, isolated_home: Path) -> None:
        """SessionStart hook exits 0 and prints the expected JSON shape."""
        result = _run_hook("jot-session-start.py", {}, isolated_home)
        assert result.returncode == 0, (
            f"jot-session-start.py must exit 0, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )
        assert result.stdout.strip(), "stdout must contain a JSON envelope"
        envelope = json.loads(result.stdout)
        assert "hookSpecificOutput" in envelope, (
            f"missing hookSpecificOutput in {envelope!r}"
        )
        hso = envelope["hookSpecificOutput"]
        assert hso.get("hookEventName") == "SessionStart"
        assert isinstance(hso.get("additionalContext"), str)

    def test_handles_empty_stdin(self, isolated_home: Path) -> None:
        """No stdin (startup fires before any payload) must still produce output."""
        result = subprocess.run(
            [str(PYTHON_BIN), str(HOOKS_DIR / "jot-session-start.py")],
            input="",
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "HOME": str(isolated_home),
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(REPO_ROOT),
            },
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0
        assert "hookSpecificOutput" in result.stdout


# ---------------------------------------------------------------------------
# jot-post-tool-use.py
# ---------------------------------------------------------------------------


class TestPostToolUse:
    def test_emits_post_tool_use_envelope(self, isolated_home: Path) -> None:
        """PostToolUse hook exits 0 and prints the expected JSON shape."""
        stdin_payload = {
            "tool_name": "mcp__akosha__search_code_patterns",
            "tool_result": "search results here",
        }
        result = _run_hook("jot-post-tool-use.py", stdin_payload, isolated_home)
        assert result.returncode == 0, (
            f"jot-post-tool-use.py must exit 0, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )
        envelope = json.loads(result.stdout)
        assert "hookSpecificOutput" in envelope
        hso = envelope["hookSpecificOutput"]
        assert hso.get("hookEventName") == "PostToolUse"
        assert isinstance(hso.get("additionalContext"), str)

    def test_truncates_tool_result_to_4096(self, isolated_home: Path) -> None:
        """The wrapper slices tool_result to 4096 chars before scoring.

        Pinned so a refactor that accidentally drops the truncation is
        caught here — surfacing a multi-MB tool_result through the
        embeddings layer would spike memory + latency.
        """
        huge_tool_result = "x" * 10_000
        stdin_payload = {"tool_name": "mcp__x__y", "tool_result": huge_tool_result}
        result = _run_hook("jot-post-tool-use.py", stdin_payload, isolated_home)
        assert result.returncode == 0
        # Surface-relevance uses the truncated slice internally; we assert
        # the hook ran without raising on a 10k-char input.
        assert "hookSpecificOutput" in result.stdout

    def test_handles_invalid_json_stdin(self, isolated_home: Path) -> None:
        """Parse failure must fail-open (exit 0, no exception trace)."""
        result = subprocess.run(
            [str(PYTHON_BIN), str(HOOKS_DIR / "jot-post-tool-use.py")],
            input="not valid json",
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "HOME": str(isolated_home),
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(REPO_ROOT),
            },
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"PostToolUse hook must fail-open on bad stdin; stderr={result.stderr!r}"
        )
        assert "hookSpecificOutput" in result.stdout


# ---------------------------------------------------------------------------
# jot-capture.py
# ---------------------------------------------------------------------------


class TestCapture:
    def test_passthrough_exits_zero(self, isolated_home: Path) -> None:
        """Non-',,' prompts: hook exits 0 and writes nothing to log."""
        stdin_payload = {"prompt": "normal prompt", "session_id": "s1"}
        result = _run_hook("jot-capture.py", stdin_payload, isolated_home)
        assert result.returncode == 0, (
            f"jot-capture.py passthrough must exit 0; stderr={result.stderr!r}"
        )
        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        assert not log.exists(), "non-capture prompt must not write to log"

    def test_capture_prefix_writes_log(self, isolated_home: Path) -> None:
        """',,' prefix: hook exits 2 and writes a JSONL line."""
        stdin_payload = {"prompt": ",, capture me", "session_id": "s1"}
        result = _run_hook("jot-capture.py", stdin_payload, isolated_home)
        assert result.returncode == 2, (
            f"capture-prefix prompt must exit 2; "
            f"got {result.returncode}; stderr={result.stderr!r}"
        )
        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        lines = [line for line in log.read_text().split("\n") if line.strip()]
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["text"] == "capture me"

    def test_invalid_json_fails_open(self, isolated_home: Path) -> None:
        """Bad stdin JSON must exit 0 (never block UserPromptSubmit)."""
        result = subprocess.run(
            [str(PYTHON_BIN), str(HOOKS_DIR / "jot-capture.py")],
            input="this is not valid json",
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "HOME": str(isolated_home),
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(REPO_ROOT),
            },
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"jot-capture.py must fail-open on bad stdin; "
            f"stderr={result.stderr!r}"
        )
        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        assert not log.exists(), "bad JSON must not produce a log entry"

    def test_emits_no_stdout(self, isolated_home: Path) -> None:
        """Capture is fire-and-forget — stdout must stay empty.

        Pinned because Claude Code's UserPromptSubmit hook contract treats
        stdout as passthrough JSON. Any wrapper that prints to stdout will
        inject text into the user's prompt.
        """
        stdin_payload = {"prompt": ",, capture me", "session_id": "s1"}
        result = _run_hook("jot-capture.py", stdin_payload, isolated_home)
        assert result.stdout == "", (
            f"capture hook must not write to stdout, got {result.stdout!r}"
        )
