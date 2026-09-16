#!/usr/bin/env python3
"""Bodai activity subscriber — EventBridge-based hook for Claude Code.

This single file implements three cooperating behaviours selected by ``--mode``:

* ``session-start`` (default; auto-selected from hook payload when omitted)
  Establishes the subscriber: writes state to
  ``~/.mahavishnu/bodai-subscriber-state.json`` and spawns a detached child
  process running ``--mode subscriber`` that subscribes to the Bodai
  EventBridge stream. Idempotent — if a state file already exists and the
  recorded pid is alive, the existing subscriber is reused.

* ``subscriber`` (long-running, detached)
  Awaits ``mahavishnu.core.events.bodai_subscriber.subscribe_to_bodai_events``
  using the configured Redis URL and consumer group. Each envelope is
  appended to ``~/.mahavishnu/bodai-event-queue.json`` (capped at 100,
  oldest dropped) by the subscriber.

* ``session-end``
  Signals the detached subscriber to stop (SIGTERM with a 5-second
  SIGKILL fallback), then deletes the state file.

Configuration via environment variables (defaults shown):

* ``MAHAVISHNU_BODAI_REDIS_URL``       — ``redis://localhost:6379/0``
* ``MAHAVISHNU_BODAI_STATE_PATH``      — ``~/.mahavishnu/bodai-subscriber-state.json``
* ``MAHAVISHNU_BODAI_QUEUE_PATH``      — ``~/.mahavishnu/bodai-event-queue.json``
* ``MAHAVISHNU_BODAI_CONSUMER_GROUP``  — ``mahavishnu-claude-observers``
* ``MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE`` — ``true`` (1/true/yes/on enable;
  0/false/no/off disable). Read by
  ``mahavishnu.core.events.bodai_subscriber._accept_legacy_wire`` to gate
  fallback decoding to the Pydantic ``EventEnvelope`` wire format when
  canonical decoding fails.

The script exits 0 on all paths. Failures are logged to stderr so they
are visible to Claude Code but never block tool execution.

Phase 12 Task 2 (option B): augments the original hook with bridge
routing to ``mahavishnu.bodai_hook_bridge.handle`` for bus publish +
audit. The existing logic is preserved verbatim — bridge failure can
never alter the authoritative exit code (spec §4.13.3).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)

from mahavishnu.bodai_hook_bridge import handle

SUBSCRIBER_STOP_GRACE_SECONDS = 5.0

# Map internal --mode values to canonical bridge event names.
# ``subscriber`` is a long-running detached process and is not a Claude
# hook event; it has no bridge routing.
_MODE_TO_EVENT: dict[str, str] = {
    "session-start": "SessionStart",
    "session-end": "SessionEnd",
}


def _mahavishnu_home() -> Path:
    """Resolve the Mahavishnu state directory, honouring ``MAHAVISHNU_HOME``."""
    override = os.environ.get("MAHAVISHNU_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu"


def _state_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_STATE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-subscriber-state.json"


def _queue_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-event-queue.json"


def _redis_url() -> str:
    return os.environ.get("MAHAVISHNU_BODAI_REDIS_URL", "redis://localhost:6379/0")


def _consumer_group() -> str:
    return os.environ.get(
        "MAHAVISHNU_BODAI_CONSUMER_GROUP", "mahavishnu-claude-observers"
    )


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


def _best_effort_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Mode: session-start
# ---------------------------------------------------------------------------


def _session_start() -> int:
    """Spawn (or reuse) the detached EventBridge subscriber."""
    state_path = _state_path()
    queue_path = _queue_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_state()
    if existing and isinstance(existing.get("pid"), int) and _pid_alive(existing["pid"]):
        _log(
            f"bodai-activity-subscriber: reusing existing subscriber "
            f"pid={existing['pid']} redis_url={existing.get('redis_url', '')} "
            f"consumer_group={existing.get('consumer_group', '')}"
        )
        return 0

    state = {
        "pid": os.getpid(),  # placeholder until the child writes its own
        "child_pid": None,
        "redis_url": _redis_url(),
        "consumer_group": _consumer_group(),
        "queue_path": str(queue_path),
        "started_at": time.time(),
        "started_by": os.getpid(),
    }
    _write_state(state)

    # Spawn the detached child that runs --mode subscriber. The child will
    # overwrite the pid field with its own pid on entry.
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
            f"bodai-activity-subscriber: spawned subscriber pid={child.pid} "
            f"redis_url={state['redis_url']} consumer_group={state['consumer_group']}"
        )
    except OSError as exc:
        _log(f"bodai-activity-subscriber: failed to spawn subscriber: {exc}")
        # Don't leave a misleading state file lying around
        try:
            state_path.unlink()
        except OSError:
            pass
        return 0

    return 0


# ---------------------------------------------------------------------------
# Mode: session-end
# ---------------------------------------------------------------------------


def _session_end() -> int:
    """Stop the subscriber and remove the state file.

    The queue file at ``~/.mahavishnu/bodai-event-queue.json`` is
    intentionally preserved across sessions so PostToolUse calls early in a
    new session still see envelopes that arrived near the end of the prior
    session (the consumer-group backlog survives the subscriber restart).
    """
    state = _read_state()
    if state is None:
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
    return 0


# ---------------------------------------------------------------------------
# Mode: subscriber (long-running, detached)
# ---------------------------------------------------------------------------


async def _run_subscriber() -> int:
    """Long-running task: subscribe to Bodai EventBridge and persist envelopes.

    Lazy import: hooks may be invoked via system Python without the
    mahavishnu package on ``sys.path``. We add the repo root (two parents
    up from this file at ``.claude/hooks/<file>.py``) so the project import
    resolves even when running outside a project venv.
    """
    state_path = _state_path()
    queue_path = _queue_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.parent.mkdir(parents=True, exist_ok=True)

    repo_root = str(Path(__file__).resolve().parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from mahavishnu.core.events.bodai_subscriber import (  # type: ignore[import-not-found]
            subscribe_to_bodai_events,
        )
    except ImportError as exc:
        _log(
            f"bodai-activity-subscriber: mahavishnu not importable: {exc}; "
            "subscriber will idle until cancelled"
        )
        # Idle until SIGTERM so the detached process stays alive but does
        # not crash Claude Code's hook chain
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                signal.signal(sig, lambda *_: stop.set())
        try:
            await stop.wait()
        except Exception:  # noqa: BLE001 - executor boundary; logs and re-raises or returns
            _log_exception("bodai-activity-subscriber: idle wait interrupted")
        return 0

    # Refresh pid field so session-end can find this child
    state = _read_state() or {}
    state["pid"] = os.getpid()
    state["redis_url"] = _redis_url()
    state["consumer_group"] = _consumer_group()
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
            signal.signal(sig, lambda *_: _signal_stop())

    # No-op callback: subscribe_to_bodai_events writes each envelope to
    # ``queue_path`` automatically via its built-in queue handling. The
    # task spec describes the system behaviour as "the callback writes
    # each envelope to the queue file" — the subscriber's built-in
    # ``queue_path`` parameter delivers exactly that; the callback only
    # needs to exist to satisfy the coroutine signature.
    async def _callback(_envelope: object) -> None:
        return None

    try:
        await subscribe_to_bodai_events(
            _callback,
            redis_url=_redis_url(),
            consumer_group=_consumer_group(),
            queue_path=queue_path,
            cancellation_token=stop,
        )
    except Exception:  # noqa: BLE001 - executor boundary; logs and re-raises or returns
        _log_exception("bodai-activity-subscriber: subscriber crashed")
    return 0


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------


def _detect_mode_from_payload(payload: dict[str, Any]) -> str | None:
    """Return the implied mode based on Claude Code hook payload shape."""
    if "session_id" in payload and "tool_name" not in payload:
        return "session-start" if "cwd" in payload else "session-end"
    return None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bodai EventBridge activity subscriber hook"
    )
    parser.add_argument(
        "mode_positional",
        nargs="?",
        choices=("session-start", "session-end", "subscriber"),
        default=None,
        help="Hook mode (positional). Equivalent to --mode.",
    )
    parser.add_argument(
        "--mode",
        choices=("session-start", "session-end", "subscriber"),
        default=None,
        help="Hook mode; default is auto-detected from the stdin payload.",
    )
    return parser.parse_args(argv)


def _safe_parse_payload() -> dict[str, object]:
    """Parse stdin JSON; return empty dict on any parse failure.

    Bridges routing uses this payload so the canonical envelope
    reaches the bus regardless of whether the original main() needed
    stdin for mode detection.
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, EOFError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_hook(payload: dict[str, object], argv: list[str] | None) -> int:
    """Original main() body, parameterised on the parsed stdin payload.

    Extracted from the pre-Phase-12 hook so the bridge augmentation
    in main() can fire-and-forget without re-reading stdin.
    """
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    mode = args.mode or args.mode_positional

    if mode is None:
        mode = _detect_mode_from_payload(payload) or "session-start"

    if mode == "session-start":
        return _session_start()
    if mode == "session-end":
        return _session_end()
    if mode == "subscriber":
        return asyncio.run(_run_subscriber())
    return 0


def main(argv: list[str] | None = None) -> int:
    """Bridge-augmented entry point.

    Reads stdin ONCE via :func:`_safe_parse_payload`, runs the original
    hook logic via :func:`_run_hook`, captures the authoritative exit
    code, then fire-and-forgets the bridge routing for the canonical
    envelope. The bridge call's result is intentionally ignored —
    the original exit code is authoritative per spec §4.13.3.

    For ``subscriber`` mode (long-running detached process) the
    bridge routing is skipped — subscriber is an internal lifecycle
    process, not a Claude Code hook event.
    """
    payload = _safe_parse_payload()
    existing_exit_code = _run_hook(payload, argv)

    # Detect mode for bridge routing — derive from argv or payload shape
    # (mirrors _run_hook's dispatch but reads only the result).
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    mode = args.mode or args.mode_positional
    if mode is None:
        mode = _detect_mode_from_payload(payload) or "session-start"
    event_name = _MODE_TO_EVENT.get(mode)
    if event_name is None:
        # ``subscriber`` mode is internal; no bridge routing.
        return existing_exit_code

    # Bridge routing — fire-and-forget. Failures must NEVER alter the
    # authoritative exit code.
    try:
        handle(event_name=event_name, harness="claude", payload=payload)
    except Exception:  # noqa: BLE001 - bridge telemetry is observation-only
        _log("bodai-activity-subscriber: bridge routing failed")
    return existing_exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
        _log_exception("bodai-activity-subscriber: unhandled error in main")
        sys.exit(0)
