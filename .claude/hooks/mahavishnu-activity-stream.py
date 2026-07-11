#!/usr/bin/env python3
"""Mahavishnu activity stream — WebSocket subscriber hook for Claude Code.

This single file implements four cooperating behaviours selected by ``--mode``:

* ``session-start`` (default; auto-selected from hook payload when omitted)
  Establishes the subscriber: writes state to
  ``~/.mahavishnu/ws-subscriber-state.json`` and spawns a detached child
  process running ``--mode subscriber`` that maintains the WebSocket
  connection. Idempotent — if a state file already exists and the recorded
  pid is alive, the existing subscriber is reused.

* ``subscriber`` (long-running, detached)
  Connects to ``ws://localhost:8690/global`` and ``ws://localhost:8690/pool:*``,
  appends each received event to ``~/.mahavishnu/ws-event-queue.json`` (capped
  at 100 entries, oldest dropped). Persists the queue atomically via a
  ``*.tmp`` + ``os.replace`` write so concurrent ``post-tool-use`` reads never
  observe a partial file.

* ``post-tool-use``
  Reads the queue, prints one ``[vishnu] ...`` summary line per matching
  event to stdout for every ``mcp__mahavishnu__*`` invocation, and clears
  the queue entries it surfaced. Silently exits 0 when the queue is empty
  or when the tool is not a ``mcp__mahavishnu__*`` call.

* ``session-end``
  Signals the detached subscriber to stop (SIGTERM with a 5-second
  SIGKILL fallback), then deletes the state file and the queue file.

Configuration via environment variables (defaults shown):

* ``MAHAVISHNU_WS_URL``        — ``ws://localhost:8690``
* ``MAHAVISHNU_WS_STATE_PATH`` — ``~/.mahavishnu/ws-subscriber-state.json``
* ``MAHAVISHNU_WS_QUEUE_PATH`` — ``~/.mahavishnu/ws-event-queue.json``
* ``MAHAVISHNU_WS_CHANNELS``   — ``global,workflow:*,pool:*``

The script exits 0 on all paths. Failures are logged to stderr so they are
visible to Claude Code but never block tool execution.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

QUEUE_CAP = 100
SUBSCRIBER_STOP_GRACE_SECONDS = 5.0
SUBSCRIBER_HEARTBEAT_SECONDS = 10.0
WS_RECONNECT_BACKOFF_SECONDS = 2.0
WS_RECONNECT_BACKOFF_MAX_SECONDS = 30.0


def _mahavishnu_home() -> Path:
    """Resolve the Mahavishnu state directory, honouring ``MAHAVISHNU_HOME``."""
    override = os.environ.get("MAHAVISHNU_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu"


def _state_path() -> Path:
    override = os.environ.get("MAHAVISHNU_WS_STATE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "ws-subscriber-state.json"


def _queue_path() -> Path:
    override = os.environ.get("MAHAVISHNU_WS_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "ws-event-queue.json"


def _ws_url() -> str:
    return os.environ.get("MAHAVISHNU_WS_URL", "ws://localhost:8690")


def _channels() -> list[str]:
    raw = os.environ.get("MAHAVISHNU_WS_CHANNELS", "global,workflow:*,pool:*")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _log(message: str) -> None:
    """Write a single line to stderr; Claude Code surfaces hook stderr as Hook output."""
    sys.stderr.write(f"Hook output: {message}\n")
    sys.stderr.flush()


def _log_exception(prefix: str) -> None:
    """Log a full traceback to stderr. Used in except blocks per project convention."""
    import traceback

    traceback.print_exc(file=sys.stderr)
    _log(prefix)


# ---------------------------------------------------------------------------
# Queue persistence
# ---------------------------------------------------------------------------


def _read_queue() -> list[dict[str, Any]]:
    path = _queue_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return data


def _write_queue(events: list[dict[str, Any]]) -> None:
    """Atomically persist the queue so concurrent readers never see a partial file."""
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(events, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        # Best-effort cleanup of the temp file; never raise into the hook
        try:
            tmp.unlink()
        except OSError:
            pass


def _append_event(event: dict[str, Any]) -> None:
    events = _read_queue()
    events.append(event)
    # Cap the queue at QUEUE_CAP — drop the oldest entries first
    if len(events) > QUEUE_CAP:
        events = events[-QUEUE_CAP:]
    _write_queue(events)


# ---------------------------------------------------------------------------
# State file management
# ---------------------------------------------------------------------------


def _read_state() -> dict[str, Any] | None:
    path = _state_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    """Return True if the pid is still running on this host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by another user — treat as alive so we don't
        # accidentally spawn a second subscriber.
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Mode: session-start
# ---------------------------------------------------------------------------


def _session_start() -> int:
    """Spawn (or reuse) the detached WebSocket subscriber."""
    state_path = _state_path()
    queue_path = _queue_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_state()
    if existing and isinstance(existing.get("pid"), int) and _pid_alive(existing["pid"]):
        _log(
            f"activity-stream: reusing existing subscriber "
            f"pid={existing['pid']} channels={existing.get('channels', [])}"
        )
        return 0

    # Stale or missing state — clear any leftover queue before starting fresh
    if queue_path.exists():
        try:
            queue_path.unlink()
        except OSError:
            pass

    state = {
        "pid": os.getpid(),  # placeholder until the child writes its own
        "child_pid": None,
        "ws_url": _ws_url(),
        "channels": _channels(),
        "queue_path": str(queue_path),
        "started_at": time.time(),
        "started_by": os.getpid(),
    }
    _write_state(state)

    # Spawn the detached child that runs --mode subscriber. The child will
    # overwrite the pid field with its own pid and update the heartbeat.
    try:
        child = subprocess.Popen(
            [sys.executable, __file__, "--mode", "subscriber"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd="/",
        )
        state["child_pid"] = child.pid
        _write_state(state)
        _log(
            f"activity-stream: spawned subscriber pid={child.pid} "
            f"url={state['ws_url']} channels={state['channels']}"
        )
    except OSError as exc:
        _log(f"activity-stream: failed to spawn subscriber: {exc}")
        # Don't leave a misleading state file lying around
        try:
            state_path.unlink()
        except OSError:
            pass
        return 0

    return 0


# ---------------------------------------------------------------------------
# Mode: post-tool-use
# ---------------------------------------------------------------------------


def _format_summary(event: dict[str, Any]) -> str | None:
    """Render an event as a one-line ``[vishnu] ...`` summary, or None to skip."""
    event_type = event.get("event_type") or event.get("type") or "event"
    data = event.get("data") if isinstance(event.get("data"), dict) else event

    workflow_id = (
        data.get("workflow_id") if isinstance(data, dict) else None
    ) or event.get("workflow_id")
    stage = (
        data.get("stage_name") if isinstance(data, dict) else None
    ) or event.get("stage_name")
    worker_id = (
        data.get("worker_id") if isinstance(data, dict) else None
    ) or event.get("worker_id")
    status = (
        data.get("status") if isinstance(data, dict) else None
    ) or event.get("status")
    pool_id = (
        data.get("pool_id") if isinstance(data, dict) else None
    ) or event.get("pool_id")

    # Map event type to a short verb for human-readable output
    verb = {
        "workflow.started": "started",
        "workflow.stage_completed": "stage completed",
        "workflow.completed": "completed",
        "workflow.failed": "failed",
        "worker.status_changed": "worker status",
        "pool.status_changed": "pool status",
    }.get(event_type, event_type)

    parts: list[str] = [f"[vishnu]"]
    if workflow_id:
        parts.append(f"workflow {workflow_id} {verb}")
    elif worker_id:
        parts.append(f"worker {worker_id} {verb}")
    elif pool_id:
        parts.append(f"pool {pool_id} {verb}")
    else:
        parts.append(verb)
    if stage:
        parts.append(f"at stage={stage}")
    if status and not workflow_id:
        parts.append(f"status={status}")
    return " ".join(parts)


def _post_tool_use() -> int:
    """Surface queued events to the conversation, then drain the queue."""
    try:
        hook_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return 0

    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    if not tool_name.startswith("mcp__mahavishnu__"):
        return 0

    events = _read_queue()
    if not events:
        return 0

    surfaced = 0
    for event in events:
        try:
            summary = _format_summary(event)
        except Exception:
            _log_exception("activity-stream: failed to format event")
            continue
        if summary:
            print(summary, flush=True)
            surfaced += 1

    # Drain only the events we actually surfaced (always all of them — partial
    # draining would require per-event cursors which the queue file does not
    # support atomically). Keeping the file empty matches the documented contract.
    if surfaced:
        _write_queue([])

    return 0


# ---------------------------------------------------------------------------
# Mode: session-end
# ---------------------------------------------------------------------------


def _session_end() -> int:
    """Stop the subscriber and remove the state and queue files."""
    state = _read_state()
    if state is None:
        # Nothing to clean up — but still best-effort delete the queue file
        _best_effort_unlink(_queue_path())
        return 0

    child_pid = state.get("child_pid") if isinstance(state, dict) else None
    if isinstance(child_pid, int) and child_pid > 0 and _pid_alive(child_pid):
        try:
            os.killpg(os.getpgid(child_pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        # Wait up to SUBSCRIBER_STOP_GRACE_SECONDS for a graceful exit
        deadline = time.monotonic() + SUBSCRIBER_STOP_GRACE_SECONDS
        while time.monotonic() < deadline:
            if not _pid_alive(child_pid):
                break
            time.sleep(0.1)
        # Escalate if the child ignored SIGTERM
        if _pid_alive(child_pid):
            try:
                os.killpg(os.getpgid(child_pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    _best_effort_unlink(_state_path())
    _best_effort_unlink(_queue_path())
    return 0


def _best_effort_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Mode: subscriber (long-running, detached)
# ---------------------------------------------------------------------------


def _event_from_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise a WebSocket protocol message into the queue's event shape."""
    if not isinstance(message, dict):
        return None
    msg_type = message.get("type")
    data = message.get("data")
    if not isinstance(data, dict):
        data = {}
    # Accept either envelope-style ("type": "event", "data": {...})
    # or a bare payload with a "type" field describing the event itself.
    event_type: str
    if msg_type in {"event", "broadcast"}:
        event_type = str(data.get("event_type") or data.get("type") or "unknown")
    elif msg_type:
        event_type = str(msg_type)
    else:
        event_type = str(data.get("event_type") or data.get("type") or "unknown")
    return {
        "event_type": event_type,
        "received_at": time.time(),
        "channel": message.get("room") or data.get("room"),
        "data": data,
    }


async def _run_subscriber() -> int:
    """Long-running task: connect to the WS server and persist events to the queue."""
    state_path = _state_path()
    queue_path = _queue_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    # Refresh the pid field so session-start/--mode session-end can find us.
    # Preserve any earlier fields (channels, url) written by the parent.
    state = _read_state() or {}
    state["pid"] = os.getpid()
    state["queue_path"] = str(queue_path)
    _write_state(state)

    stop = asyncio.Event()

    def _signal_stop(*_args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_stop)
        except (NotImplementedError, RuntimeError):
            # add_signal_handler may not be available on all platforms
            signal.signal(sig, lambda *_: _signal_stop())

    try:
        websockets_mod = await _try_import_websockets()
    except Exception:
        _log_exception("activity-stream: failed to import a WebSocket client library")
        return 0

    if websockets_mod is None:
        _log(
            "activity-stream: neither 'websockets' nor 'aiohttp' is available; "
            "subscriber will idle until one is installed"
        )
        # Idle loop — wait for stop signal so the process stays detached
        await stop.wait()
        return 0

    backoff = WS_RECONNECT_BACKOFF_SECONDS
    while not stop.is_set():
        try:
            async with websockets_mod.connect(  # type: ignore[attr-defined]
                _ws_url(), open_timeout=5.0, ping_interval=20, ping_timeout=20
            ) as ws:
                backoff = WS_RECONNECT_BACKOFF_SECONDS
                # Subscribe to each configured channel
                for channel in _channels():
                    sub = json.dumps(
                        {"type": "subscribe", "data": {"channel": channel}}
                    )
                    try:
                        await ws.send(sub)
                    except Exception:
                        _log_exception(
                            f"activity-stream: failed to send subscribe for {channel}"
                        )
                # Heartbeat updater runs as a sibling task
                heartbeat_task = asyncio.create_task(_heartbeat_loop(state_path, stop))
                try:
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        event = _event_from_message(message)
                        if event is not None:
                            try:
                                _append_event(event)
                            except Exception:
                                _log_exception("activity-stream: failed to append event")
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except (asyncio.CancelledError, Exception):
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            _log_exception("activity-stream: websocket connection error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2.0, WS_RECONNECT_BACKOFF_MAX_SECONDS)

    return 0


async def _heartbeat_loop(state_path: Path, stop: asyncio.Event) -> None:
    """Periodically update the ``last_seen`` field in the state file."""
    while not stop.is_set():
        try:
            state = _read_state() or {}
            state["last_seen"] = time.time()
            _write_state(state)
        except Exception:
            _log_exception("activity-stream: heartbeat write failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=SUBSCRIBER_HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            continue


async def _try_import_websockets() -> Any:
    """Try the lightweight ``websockets`` package first; fall back to ``aiohttp``."""
    try:
        import websockets  # type: ignore[import-not-found]

        return websockets
    except ImportError:
        pass
    try:
        import aiohttp  # type: ignore[import-not-found]

        # Return a thin shim so the call site looks identical
        class _AiohttpShim:
            @staticmethod
            async def connect(url: str, **kwargs: Any) -> Any:
                session = aiohttp.ClientSession()
                ws = await session.ws_connect(url, **kwargs)
                # Close the session when the WS closes
                original_close = ws.close

                async def _close(*a: Any, **kw: Any) -> Any:
                    try:
                        return await original_close(*a, **kw)
                    finally:
                        await session.close()

                ws.close = _close  # type: ignore[method-assign]
                return ws

        return _AiohttpShim
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------


def _detect_mode_from_payload(payload: dict[str, Any]) -> str | None:
    """Return the implied mode based on Claude Code hook payload shape."""
    if "session_id" in payload and "tool_name" not in payload:
        return "session-start" if "cwd" in payload else "session-end"
    if "tool_name" in payload:
        return "post-tool-use"
    return None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mahavishnu WebSocket activity-stream hook"
    )
    parser.add_argument(
        "mode_positional",
        nargs="?",
        choices=("session-start", "post-tool-use", "session-end", "subscriber"),
        default=None,
        help="Hook mode (positional). Equivalent to --mode.",
    )
    parser.add_argument(
        "--mode",
        choices=("session-start", "post-tool-use", "session-end", "subscriber"),
        default=None,
        help="Hook mode; default is auto-detected from the stdin payload.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    mode = args.mode or args.mode_positional

    if mode is None:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        mode = _detect_mode_from_payload(payload) or "session-start"

    if mode == "session-start":
        return _session_start()
    if mode == "post-tool-use":
        return _post_tool_use()
    if mode == "session-end":
        return _session_end()
    if mode == "subscriber":
        return asyncio.run(_run_subscriber())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _log_exception("activity-stream: unhandled error in main")
        sys.exit(0)