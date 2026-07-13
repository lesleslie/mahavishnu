"""Integration tests for the Phase 6 Bodai activity hooks.

Per the Phase 6 plan (Section 5, Phase 6.4):
docs/plans/2026-07-11-phase-6-bodai-observability.md#phase-64-replace-phase-5-hook--settings-wiring

The hooks under test live at:

- ``.claude/hooks/bodai-activity-subscriber.py`` — SessionStart spawns the
  detached EventBridge subscriber; SessionEnd cleans up the child + state file.
- ``.claude/hooks/bodai-activity-post-tool-use.py`` — drains the queue and
  emits ``[component] event_type key=value`` summaries to stdout.

These tests cover the four Exit Criteria sections of Phase 6.4 task 6.4.1
end-to-end against the actual hook scripts (with env-var overrides so
filesystem isolation is preserved per-test).

Marker: ``integration`` per ``CLAUDE.md`` Test conventions.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import uuid

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
SUBSCRIBER_HOOK = HOOKS_DIR / "bodai-activity-subscriber.py"
POST_TOOL_USE_HOOK = HOOKS_DIR / "bodai-activity-post-tool-use.py"


def _load_module(path: Path) -> Any:
    """Import a hook script via importlib under a uniquely-named module."""
    unique = f"bodai_hook_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    """Wire MAHAVISHNU_BODAI_* paths to fresh tmp files."""
    monkeypatch.delenv("MAHAVISHNU_HOME", raising=False)
    state = tmp_path / "bodai-subscriber-state.json"
    queue = tmp_path / "bodai-event-queue.json"
    ptu_state = tmp_path / "bodai-post-tool-use-state.json"
    monkeypatch.setenv("MAHAVISHNU_BODAI_STATE_PATH", str(state))
    monkeypatch.setenv("MAHAVISHNU_BODAI_QUEUE_PATH", str(queue))
    monkeypatch.setenv(
        "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH", str(ptu_state)
    )
    return state, queue, ptu_state


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------


@pytest.fixture
def subscriber_module(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Load bodai-activity-subscriber.py with a clean MAHAVISHNU_BODAI_* env."""
    for key in (
        "MAHAVISHNU_HOME",
        "MAHAVISHNU_BODAI_STATE_PATH",
        "MAHAVISHNU_BODAI_QUEUE_PATH",
        "MAHAVISHNU_BODAI_REDIS_URL",
        "MAHAVISHNU_BODAI_CONSUMER_GROUP",
    ):
        monkeypatch.delenv(key, raising=False)
    return _load_module(SUBSCRIBER_HOOK)


@pytest.fixture
def post_tool_use_module(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Load bodai-activity-post-tool-use.py with a clean MAHAVISHNU_BODAI_* env."""
    for key in (
        "MAHAVISHNU_HOME",
        "MAHAVISHNU_BODAI_QUEUE_PATH",
        "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH",
        "MAHAVISHNU_BODAI_DEBUG",
    ):
        monkeypatch.delenv(key, raising=False)
    return _load_module(POST_TOOL_USE_HOOK)


# ---------------------------------------------------------------------------
# Test 1: SessionStart writes the state file with the spawned child pid
# ---------------------------------------------------------------------------


def test_subscriber_session_start_spawns_detached_task(
    subscriber_module: Any,
    isolated_env: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling ``_session_start`` should write the state file containing the
    child pid returned from ``subprocess.Popen``. We replace ``subprocess.Popen``
    with a stub so the test does not spawn a real child process.
    """
    state_path, _queue_path, _ptu_state = isolated_env

    # Stub subprocess.Popen so no real child is spawned.
    class _FakeChild:
        pid = 999_999

    monkeypatch.setattr(
        subscriber_module.subprocess, "Popen", lambda *a, **kw: _FakeChild()
    )

    rc = subscriber_module._session_start()
    assert rc == 0, "session_start must exit 0"

    assert state_path.exists(), (
        f"session_start should write the state file at {state_path}; "
        f"file is missing"
    )
    state = json.loads(state_path.read_text())
    assert state.get("child_pid") == 999_999, (
        f"state file should record the spawned child pid; got {state!r}"
    )
    assert state.get("redis_url"), (
        f"state file should record redis_url; got {state!r}"
    )
    assert state.get("consumer_group"), (
        f"state file should record consumer_group; got {state!r}"
    )
    assert state.get("queue_path"), (
        f"state file should record queue_path; got {state!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: PostToolUse emits [component] event_type key=value for new events
# ---------------------------------------------------------------------------


def test_post_tool_use_emits_recent_events(
    post_tool_use_module: Any,
    isolated_env: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Seed the queue with 3 envelopes (one per component) plus 1 unknown
    source envelope. ``_post_tool_use`` should emit the 3 component lines
    and skip the unknown (forward-compatibility).
    """
    _state_path, queue_path, ptu_state_path = isolated_env

    base_at = time.time() + 1000.0
    envelopes = [
        {
            "topic": "workflow.completed",
            "payload": {"workflow_id": "wid_abc", "status": "success"},
            "headers": {"source": "mahavishnu"},
            "received_at": base_at + 1,
        },
        {
            "topic": "aggregation_completed",
            "payload": {"suite": "quality"},
            "headers": {"source": "akosha"},
            "received_at": base_at + 2,
        },
        {
            "topic": "test_run_completed",
            "payload": {"passed": 42, "failed": 0},
            "headers": {"source": "crackerjack"},
            "received_at": base_at + 3,
        },
        {
            "topic": "unknown_event",
            "payload": {"foo": "bar"},
            "headers": {"source": "future-component"},
            "received_at": base_at + 4,
        },
    ]
    queue_path.write_text(json.dumps(envelopes))

    rc = post_tool_use_module._post_tool_use()
    assert rc == 0, "post_tool_use must exit 0"

    captured = capsys.readouterr().out
    # Payload keys are alphabetically sorted by format_bodai_summary,
    # so 'status' precedes 'workflow_id' in the output.
    assert "[mahavishnu] workflow.completed status=success workflow_id=wid_abc" in captured, (
        f"expected mahavishnu summary on stdout; got {captured!r}"
    )
    assert "[akosha] aggregation_completed suite=quality" in captured, (
        f"expected akosha summary on stdout; got {captured!r}"
    )
    assert "[crackerjack] test_run_completed failed=0 passed=42" in captured, (
        f"expected crackerjack summary on stdout; got {captured!r}"
    )
    # The unknown source envelope must NOT have produced a stdout line.
    assert "[future-component]" not in captured, (
        f"unknown-source envelope should be skipped; got {captured!r}"
    )

    # State should be persisted with the new cursor
    assert ptu_state_path.exists(), (
        f"post_tool_use should persist state; missing at {ptu_state_path}"
    )
    state = json.loads(ptu_state_path.read_text())
    assert state["last_read_at"] == base_at + 4, (
        f"cursor should advance to the max received_at; got {state!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: SessionEnd cleans up the state file
# ---------------------------------------------------------------------------


def test_session_end_cleans_up_state_file(
    subscriber_module: Any,
    isolated_env: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run ``_session_end`` against a state file with a non-existent pid;
    verify the state file is deleted and the kill path is skipped.
    """
    state_path, _queue_path, _ptu_state = isolated_env

    # A pid that's definitely not running — _session_end should skip kill
    state_path.write_text(
        json.dumps(
            {
                "pid": 999_999_999,  # extremely unlikely to be a live pid
                "child_pid": 999_999_999,
                "redis_url": "redis://localhost:6379/0",
                "consumer_group": "mahavishnu-claude-observers",
            }
        )
    )

    # Force _pid_alive to return False deterministically
    monkeypatch.setattr(subscriber_module, "_pid_alive", lambda _pid: False)

    rc = subscriber_module._session_end()
    assert rc == 0, "session_end must exit 0"

    assert not state_path.exists(), (
        f"SessionEnd should delete the state file at {state_path}; still present"
    )


# ---------------------------------------------------------------------------
# Test 4: PostToolUse only emits events newer than the stored cursor
# ---------------------------------------------------------------------------


def test_post_tool_use_only_emits_new_events(
    post_tool_use_module: Any,
    isolated_env: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Run ``_post_tool_use`` twice against the same queue. The second run
    must produce no stdout output because the cursor has already advanced
    past every envelope.
    """
    _state_path, queue_path, _ptu_state_path = isolated_env

    base_at = time.time() + 5000.0
    envelopes = [
        {
            "topic": "workflow.completed",
            "payload": {"workflow_id": "wid_xyz"},
            "headers": {"source": "mahavishnu"},
            "received_at": base_at + 1,
        },
        {
            "topic": "test_run_completed",
            "payload": {"passed": 10, "failed": 0},
            "headers": {"source": "crackerjack"},
            "received_at": base_at + 2,
        },
    ]
    queue_path.write_text(json.dumps(envelopes))

    # First run: emit everything
    rc1 = post_tool_use_module._post_tool_use()
    assert rc1 == 0
    first_out = capsys.readouterr().out
    assert "[mahavishnu] workflow.completed workflow_id=wid_xyz" in first_out, (
        f"first run must emit the mahavishnu line; got {first_out!r}"
    )
    assert "[crackerjack] test_run_completed failed=0 passed=10" in first_out, (
        f"first run must emit the crackerjack line; got {first_out!r}"
    )

    # Second run: nothing new since the cursor was advanced past every
    # envelope, so stdout should be empty.
    rc2 = post_tool_use_module._post_tool_use()
    assert rc2 == 0
    second_out = capsys.readouterr().out
    assert second_out == "", (
        f"second run must NOT re-emit already-surfaced envelopes; "
        f"got {second_out!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: CLI entry point smoke test — both hooks are executable and exit 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hook, args",
    [
        (SUBSCRIBER_HOOK, ["session-end"]),
    ],
)
def test_subscriber_hook_cli_exits_zero(
    hook: Path, args: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke-test that the subscriber hook's CLI entry point runs without
    raising. ``session-end`` is the cheapest path: it never spawns a child
    when no state file is present.
    """
    monkeypatch.delenv("MAHAVISHNU_BODAI_STATE_PATH", raising=False)
    monkeypatch.delenv("MAHAVISHNU_BODAI_QUEUE_PATH", raising=False)
    result = subprocess.run(
        [sys.executable, str(hook), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"hook {hook.name} should exit 0; got {result.returncode}\n"
        f"stderr={result.stderr}"
    )


def test_post_tool_use_hook_cli_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Smoke-test the post-tool-use hook with a fresh empty environment."""
    ptu_state = tmp_path / "bodai-post-tool-use-state.json"
    queue = tmp_path / "bodai-event-queue.json"
    monkeypatch.setenv("MAHAVISHNU_BODAI_QUEUE_PATH", str(queue))
    monkeypatch.setenv(
        "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH", str(ptu_state)
    )
    result = subprocess.run(
        [sys.executable, str(POST_TOOL_USE_HOOK)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"hook should exit 0; got {result.returncode}\n"
        f"stderr={result.stderr}"
    )
    assert result.stdout == "", (
        f"empty queue should produce no stdout; got {result.stdout!r}"
    )
