"""Integration tests for the mahavishnu-activity-stream WebSocket subscriber hook.

Per the ultracode integration plan (Section 5, Phase 5, Task 5.5):
docs/plans/2026-07-11-ultracode-integration-wiring.md#phase-5-worker-activity-surfacing

The hook under test lives at ``.claude/hooks/mahavishnu-activity-stream.py``
(Task 5.4 output). It implements four cooperating behaviours selected by
``--mode``:

- ``session-start`` / Spawns the detached subscriber
- ``subscriber`` (long-running, detached) / Connects to ``ws://.../global``
  and persists events to ``~/.mahavishnu/ws-event-queue.json`` (capped at 100)
- ``post-tool-use`` / Surfaces queued events to the conversation, then drains
- ``session-end`` / Stops the subscriber and removes the state and queue files

These tests exercise the five Exit Criteria listed under Task 5.5, end-to-end
against the actual hook script (with env-var overrides and a real
``websockets`` server fixture where useful).

Marker: ``integration`` per ``CLAUDE.md`` Test conventions.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import websockets

HOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "hooks"
    / "mahavishnu-activity-stream.py"
)


# ---------------------------------------------------------------------------
# Module loader — each test gets a freshly-imported copy of the hook script
# so per-test env-var overrides and monkeypatches stay isolated.
# ---------------------------------------------------------------------------


def _load_hook() -> Any:
    """Import the hook script as a uniquely-named module."""
    unique = f"mahavishnu_activity_stream_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique, str(HOOK_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook spec from {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hook_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Fresh hook module with environment cleaned so tests control every path."""
    monkeypatch.delenv("MAHAVISHNU_HOME", raising=False)
    monkeypatch.delenv("MAHAVISHNU_WS_STATE_PATH", raising=False)
    monkeypatch.delenv("MAHAVISHNU_WS_QUEUE_PATH", raising=False)
    monkeypatch.delenv("MAHAVISHNU_WS_URL", raising=False)
    monkeypatch.delenv("MAHAVISHNU_WS_CHANNELS", raising=False)
    return _load_hook()


@pytest.fixture
def isolated_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Wire MAHAVISHNU_WS_STATE_PATH and MAHAVISHNU_WS_QUEUE_PATH to tmp files."""
    state = tmp_path / "ws-subscriber-state.json"
    queue = tmp_path / "ws-event-queue.json"
    monkeypatch.setenv("MAHAVISHNU_WS_STATE_PATH", str(state))
    monkeypatch.setenv("MAHAVISHNU_WS_QUEUE_PATH", str(queue))
    return state, queue


# ---------------------------------------------------------------------------
# Fake WebSocket server
# ---------------------------------------------------------------------------


class _FakeMahavishnuWSServer:
    """A minimal asyncio WebSocket server for testing the subscriber.

    Captures subscribe envelopes and other received messages. Optionally
    disconnects after N messages so we can exercise the reconnect path.
    """

    def __init__(self) -> None:
        self.subscribes: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []
        self.connection_count: int = 0
        self.disconnect_after_messages: int | None = None
        self._server: Any = None
        self.port: int = 0

    async def _handler(self, ws: Any) -> None:
        self.connection_count += 1
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self.received.append(msg)
                if msg.get("type") == "subscribe":
                    self.subscribes.append(msg)
                if self.disconnect_after_messages is not None:
                    self.disconnect_after_messages -= 1
                    if self.disconnect_after_messages <= 0:
                        await ws.close(code=1011)
                        return
        except websockets.ConnectionClosed:
            return

    async def start(self) -> None:
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        # The server binds an OS-assigned port; capture it.
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass

    def has_subscribe_for(self, channel: str) -> bool:
        return any(
            s.get("data", {}).get("channel") == channel for s in self.subscribes
        )


@pytest.fixture
async def ws_server() -> Any:
    """Yield a running _FakeMahavishnuWSServer bound to a free local port."""
    server = _FakeMahavishnuWSServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@contextmanager
def _redirect_stdin(payload: str):
    """Replace ``sys.stdin`` with a ``StringIO(payload)`` for the block."""
    real = sys.stdin
    sys.stdin = io.StringIO(payload)
    try:
        yield
    finally:
        sys.stdin = real


# ---------------------------------------------------------------------------
# Test 1: SessionStart -> subscriber connects to the global channel
# ---------------------------------------------------------------------------


async def test_subscriber_connects_to_global_channel(
    hook_module: Any,
    isolated_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    ws_server: Any,
) -> None:
    """On SessionStart (which auto-spawns ``--mode subscriber``), verify
    the hook connects to the configured WS URL and sends a subscribe
    envelope for the ``global`` channel.
    """
    state_path, _queue_path = isolated_paths
    monkeypatch.setenv("MAHAVISHNU_WS_URL", f"ws://127.0.0.1:{ws_server.port}")
    monkeypatch.setenv("MAHAVISHNU_WS_CHANNELS", "global")

    task = asyncio.create_task(hook_module._run_subscriber())
    try:
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if ws_server.has_subscribe_for("global"):
                break
        # Give the subscriber a beat to finish its initial state write
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # (a) subscriber wrote the state file with its pid on entry
    assert state_path.exists(), (
        f"subscriber should write state file with pid on entry; got "
        f"{state_path.exists()=}"
    )
    state = json.loads(state_path.read_text())
    assert state.get("pid"), (
        f"state file must record the subscriber pid; got {state!r}"
    )

    # (b) the server received at least one subscribe envelope for /global
    assert ws_server.has_subscribe_for("global"), (
        f"subscriber must send subscribe envelope for the 'global' channel "
        f"on SessionStart; got subscribes={ws_server.subscribes!r}"
    )

    # (c) connection happened against the right URL
    assert ws_server.connection_count >= 1, (
        f"subscriber should connect at least once; got "
        f"connection_count={ws_server.connection_count}"
    )


# ---------------------------------------------------------------------------
# Test 2: Queue cap at QUEUE_CAP (100), oldest dropped first
# ---------------------------------------------------------------------------


def test_subscriber_maintains_event_queue_cap_at_100(
    hook_module: Any, isolated_paths: tuple[Path, Path]
) -> None:
    """Feed 150 events; queue must be capped at ``QUEUE_CAP`` (100) with
    oldest entries dropped first.
    """
    _state_path, _queue_path = isolated_paths

    # Sanity-check the constant matches the documented contract
    assert hook_module.QUEUE_CAP == 100, (
        f"QUEUE_CAP must be 100 per the documented contract; "
        f"got {hook_module.QUEUE_CAP}"
    )

    # Feed 150 events with monotonically-increasing payload indices
    for i in range(150):
        hook_module._append_event(
            {
                "event_type": "workflow.completed",
                "received_at": float(i),
                "data": {"i": i, "workflow_id": f"wid_{i:03d}"},
            }
        )

    events = hook_module._read_queue()
    assert len(events) == hook_module.QUEUE_CAP, (
        f"queue must be capped at QUEUE_CAP={hook_module.QUEUE_CAP}; "
        f"got {len(events)}"
    )

    indices = [e["data"]["i"] for e in events]
    assert indices == sorted(indices), (
        f"queue must retain newest events in insertion order; got indices={indices}"
    )
    # Oldest 50 events (indices 0..49) should be dropped; 50..149 retained
    assert indices[0] == 50 and indices[-1] == 149, (
        f"oldest 50 events should be dropped; expected indices 50..149, "
        f"got first={indices[0]} last={indices[-1]}"
    )


# ---------------------------------------------------------------------------
# Test 3: PostToolUse surfaces matching event with [vishnu] summary
# ---------------------------------------------------------------------------


def test_post_tool_use_emits_summary_for_matching_event(
    hook_module: Any,
    isolated_paths: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Simulate a ``PostToolUse`` hook with a recent ``workflow_completed``
    event; verify the hook emits ``[vishnu] workflow wid_abc completed``
    to the conversation and drains the queue.
    """
    _state_path, _queue_path = isolated_paths

    # Seed the queue with one workflow_completed event
    hook_module._write_queue(
        [
            {
                "event_type": "workflow.completed",
                "received_at": 0.0,
                "data": {"workflow_id": "wid_abc", "status": "success"},
            }
        ]
    )

    payload = json.dumps({"tool_name": "mcp__mahavishnu__pool_route_execute"})
    with _redirect_stdin(payload):
        rc = hook_module._post_tool_use()

    assert rc == 0, "hook must exit 0 on the post-tool-use path"
    captured = capsys.readouterr().out
    assert "[vishnu] workflow wid_abc completed" in captured, (
        f"expected '[vishnu] workflow wid_abc completed' on stdout; "
        f"got: {captured!r}"
    )

    # Queue must be drained after surfacing
    assert hook_module._read_queue() == [], (
        "queue must be drained after surfacing events"
    )


# ---------------------------------------------------------------------------
# Test 4: Disconnect handled gracefully — WARNING logged and reconnect attempted
# ---------------------------------------------------------------------------


async def test_subscriber_handles_ws_disconnect_gracefully(
    hook_module: Any,
    isolated_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    ws_server: Any,
) -> None:
    """Mock a mid-stream disconnect; verify the hook logs a WARNING and
    reconnects on the next attempt.
    """
    _state_path, _queue_path = isolated_paths

    monkeypatch.setenv("MAHAVISHNU_WS_URL", f"ws://127.0.0.1:{ws_server.port}")
    monkeypatch.setenv("MAHAVISHNU_WS_CHANNELS", "global")

    # Compress the backoff so the reconnect attempt completes inside the test
    monkeypatch.setattr(hook_module, "WS_RECONNECT_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(hook_module, "WS_RECONNECT_BACKOFF_MAX_SECONDS", 0.05)

    # Disconnect after the first message on each connection (forces reconnect)
    ws_server.disconnect_after_messages = 1

    # Capture _log_exception invocations (the disconnect path calls this)
    captured_exceptions: list[str] = []
    monkeypatch.setattr(
        hook_module,
        "_log_exception",
        lambda prefix: captured_exceptions.append(prefix),
    )

    task = asyncio.create_task(hook_module._run_subscriber())
    try:
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            # At least one reconnect happened (count >= 2)
            if ws_server.connection_count >= 2:
                break
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # Hook should have reconnected at least once after the forced drop
    assert ws_server.connection_count >= 2, (
        f"hook should reconnect after disconnect; got "
        f"connection_count={ws_server.connection_count}"
    )

    # At least one disconnect error should have been reported via _log_exception
    assert captured_exceptions, (
        "expected _log_exception to be invoked on disconnect path; got nothing"
    )
    assert any("websocket connection error" in entry for entry in captured_exceptions), (
        f"expected a 'websocket connection error' WARNING; got "
        f"{captured_exceptions!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: SessionEnd cleans up the state file
# ---------------------------------------------------------------------------


def test_session_end_cleans_up_state_file(
    hook_module: Any,
    isolated_paths: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a ``SessionEnd`` hook; verify the state file (and queue
    file) are deleted.
    """
    state_path, queue_path = isolated_paths

    # Seed both files so we can prove they get removed (not just untouched)
    state_path.write_text(
        json.dumps(
            {
                "pid": 0,
                "child_pid": 0,  # 0 → _session_end skips the kill path
                "ws_url": "ws://127.0.0.1:0",
                "channels": ["global"],
            }
        )
    )
    queue_path.write_text(json.dumps([{"event_type": "noop", "data": {}}]))

    # Make any pid-alive check return False so session_end skips the kill loop
    monkeypatch.setattr(hook_module, "_pid_alive", lambda _pid: False)

    rc = hook_module._session_end()
    assert rc == 0, "session_end must exit 0"

    assert not state_path.exists(), (
        f"SessionEnd must delete the state file at {state_path}; "
        f"file still present"
    )
    assert not queue_path.exists(), (
        f"SessionEnd must also clean up the queue file at {queue_path}; "
        f"file still present"
    )
