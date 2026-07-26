"""MCP tools for the durable-worker contract.

Exposes seven FastMCP tools that proxy to a :class:`DurableWorkerManager`:

* ``launch_worker`` — spawn a worker backed by a tmux session.
* ``send_input`` — type text into the worker's pane.
* ``capture_output`` — snapshot the tmux pane buffer.
* ``worker_status`` — return the durable record plus live pane info.
* ``wait_for_state`` — poll until a target lifecycle state is reached.
* ``cancel_worker`` — soft-cancel the worker (with optional SIGKILL fallback).
* ``worker_revoke`` — mark the worker reaped (optionally with force kill).

The functions are defined at module level (so tests can patch the global
``_durable_manager`` and call them directly), and the
``register_worker_contract_tools`` helper attaches them to a FastMCP app
via ``@app.tool()``.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..workers.contract.manager import DurableWorkerManager


# Module-level reference set by ``register_worker_contract_tools`` and
# patchable by tests. Reading from a module global keeps the FastMCP tool
# functions free of bound state, which simplifies test isolation.
_durable_manager: DurableWorkerManager | None = None


# Match CSI escape sequences (colors, cursor moves) so we can strip ANSI
# from pane snapshots. Mirrors ``mahavishnu.workers.contract.tmux_adapter``
# without forcing the runtime to import the tmux adapter for callers that
# never capture output.
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    """Strip ANSI CSI escape sequences from ``text``."""
    return _ANSI_RE.sub("", text)


def _state_value(state: Any) -> str:
    """Return ``state`` as a plain string, unwrapping Enum ``.value`` when present."""
    if state is None:
        return "missing"
    value = getattr(state, "value", None)
    return value if isinstance(value, str) else str(state)


def _tmux_payload(record: Any) -> dict[str, Any] | None:
    """Return ``record.tmux`` as a dict when present."""
    tmux = getattr(record, "tmux", None)
    if tmux is None:
        return None
    if hasattr(tmux, "model_dump"):
        dumped: Any = tmux.model_dump()
        return dumped if isinstance(dumped, dict) else None
    return tmux if isinstance(tmux, dict) else None


async def launch_worker(
    prompt: str,
    *,
    worker_type: str = "terminal-claude",
    backend: str = "claude_tui",
    command: list[str] | None = None,
    worker_id: str | None = None,
    pty: bool = True,
    session_mode: str = "managed_tmux",
    max_wait_ms: int = 30_000,
    model: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Spawn a durable worker with a tmux-backed session.

    Spec §7.1: ``session_mode`` drives tmux reuse vs. managed session.
    ``current_tmux`` reuses the caller's session (TMUX env var set),
    ``managed_tmux`` creates a private Mahavishnu-owned session, and
    ``no_tmux`` falls back to the legacy PTY/backend path with a sentinel
    return so callers can route accordingly.
    """
    if _durable_manager is None:
        return {"worker_id": None, "state": "manager_unconfigured"}

    if session_mode == "no_tmux":
        # Backwards-compatible fallback. Falls through to legacy path.
        return {"worker_id": None, "state": "no_tmux"}

    effective_command = command or ["claude"]
    window_name = (
        metadata.get("window_name", "main") if isinstance(metadata, dict) else "main"
    )
    result = _durable_manager.spawn(
        worker_type=worker_type,
        backend=backend,
        command=effective_command,
        worker_id=worker_id,
        window_name=window_name,
        max_wait_ms=max_wait_ms,
    )
    return {
        "worker_id": result.worker_id,
        "state": _state_value(result.record.state),
        "tmux": _tmux_payload(result.record),
        "pty": pty,
        "session_mode": session_mode,
        "model": model,
        "metadata": metadata or {},
    }


async def send_input(worker_id: str, input: str, *, submit: bool = True) -> dict:
    """Deliver text to the worker's pane. ``accepted=False`` means the worker
    is in a state that cannot accept input (already reaped, missing pane, etc.).
    """
    if _durable_manager is None:
        return {"accepted": False, "byte_offset": 0}
    accepted = _durable_manager.send_input(worker_id, input, submit=submit)
    return {"accepted": accepted, "byte_offset": 0}


async def capture_output(
    worker_id: str,
    *,
    since_offset: int = 0,
    max_bytes: int = 65_536,
    strip_ansi: bool = True,
) -> dict:
    """Return a fresh pane snapshot bounded by ``since_offset`` and ``max_bytes``."""
    if _durable_manager is None:
        return {
            "worker_id": worker_id,
            "text": "",
            "next_offset": since_offset,
            "truncated": False,
            "pane_alive": False,
        }
    result = _durable_manager.capture_output(
        worker_id, since_offset=since_offset, max_bytes=max_bytes
    )
    text = getattr(result, "text", "") or ""
    if strip_ansi and text:
        text = _strip_ansi(text)
    return {
        "worker_id": worker_id,
        "text": text,
        "next_offset": getattr(result, "next_offset", since_offset),
        "truncated": getattr(result, "truncated", False),
        "pane_alive": getattr(result, "pane_alive", False),
    }


async def worker_status(worker_id: str) -> dict:
    """Return the durable record for ``worker_id`` with live pane metadata.

    ``pane_command`` is fetched via :meth:`DurableWorkerManager.pane_command`
    when available. If the manager does not implement it (e.g. older
    revisions) the field silently falls back to ``None`` rather than crash
    the status call.
    """
    if _durable_manager is None:
        return {"worker_id": worker_id, "state": "manager_unconfigured"}

    record = _durable_manager.status(worker_id)
    if record is None:
        return {"worker_id": worker_id, "state": "not_found"}

    # uptime is best-effort: a malformed record (missing or None dates)
    # should not crash the status call.
    uptime_seconds = 0
    try:
        delta = record.last_seen_at - record.created_at
        uptime_seconds = int(delta.total_seconds())
    except (AttributeError, TypeError, ValueError):
        uptime_seconds = 0

    last_activity = getattr(record, "last_seen_at", None)
    last_activity_iso = last_activity.isoformat() if last_activity is not None else None

    pane_command: str | None = None
    pane_fn = getattr(_durable_manager, "pane_command", None)
    if pane_fn is not None and getattr(record, "tmux", None) is not None:
        try:
            pane_command = pane_fn(worker_id)
        except Exception:
            pane_command = None

    return {
        "worker_id": record.worker_id,
        "state": _state_value(record.state),
        "exit_code": getattr(record, "last_exit_code", None),
        "uptime_seconds": uptime_seconds,
        "last_activity_iso": last_activity_iso,
        "pane_command": pane_command,
        "tmux": _tmux_payload(record),
        "claude_session": getattr(record, "claude_session", None),
        "error": None,
    }


async def wait_for_state(
    worker_id: str,
    until_state: str,
    timeout_ms: int = 30_000,
    poll_interval_ms: int = 250,
    include_output: bool = False,
) -> dict:
    """Poll the durable record until it reaches ``until_state`` or times out.

    When ``include_output`` is True, the response carries incremental pane
    output captured during the wait (``output_during_wait``), matching F9.
    """
    if _durable_manager is None:
        return {"worker_id": worker_id, "state": "manager_unconfigured", "elapsed_ms": 0}

    from mahavishnu.workers.contract.state import WorkerLifecycleState

    target = WorkerLifecycleState(until_state)
    loop = asyncio.get_event_loop()
    start = loop.time()
    deadline = start + timeout_ms / 1000.0
    captured = ""
    last_offset = 0
    while loop.time() < deadline:
        record = _durable_manager.status(worker_id)
        if record is None:
            return {"worker_id": worker_id, "state": "missing", "elapsed_ms": 0}
        if include_output:
            out = _durable_manager.capture_output(
                worker_id, since_offset=last_offset, max_bytes=4_096
            )
            new_text = getattr(out, "text", "") or ""
            if new_text:
                captured += new_text
                last_offset = getattr(out, "next_offset", last_offset)
        if record.state == target:
            return {
                "worker_id": worker_id,
                "state": _state_value(record.state),
                "elapsed_ms": int((loop.time() - start) * 1000),
                "output_during_wait": captured if include_output else None,
            }
        await asyncio.sleep(poll_interval_ms / 1000.0)
    record = _durable_manager.status(worker_id)
    return {
        "worker_id": worker_id,
        "state": _state_value(record.state) if record else "missing",
        "elapsed_ms": timeout_ms,
        "timed_out": True,
        "output_during_wait": captured if include_output else None,
    }


async def cancel_worker(
    worker_id: str, *, signal: str = "soft", grace_ms: int = 5_000
) -> dict:
    """Cancel a worker gracefully. ``signal="SIGKILL"`` escalates after grace.

    The response always carries ``exit_code`` (F10) so callers can
    distinguish a graceful exit from a hard kill.
    """
    if _durable_manager is None:
        return {"killed": False, "exit_code": None}
    killed = _durable_manager.cancel(worker_id, signal=signal, grace_ms=grace_ms)
    record = _durable_manager.status(worker_id)
    return {
        "killed": killed,
        "exit_code": getattr(record, "last_exit_code", None) if record else None,
    }


async def worker_revoke(worker_id: str, *, force: bool = False) -> dict:
    """Reap a durable worker record. With ``force=True`` the underlying
    pane is SIGKILL'd before the record is reaped.

    ``attach_command`` (F16) is returned for operator convenience but is
    NEVER auto-executed by Mahavishnu; the caller must issue the command in
    their own shell.
    """
    if _durable_manager is None:
        return {"revoked": False, "force": force, "attach_command": None}
    if force:
        _durable_manager.cancel(worker_id, signal="SIGKILL", grace_ms=1_000)
    else:
        _durable_manager.reap(worker_id)
    record = _durable_manager.status(worker_id)
    attach_command: str | None = None
    if record is not None and getattr(record, "tmux", None) is not None:
        attach_command = getattr(record.tmux, "attach_command", None)
    return {
        "revoked": True,
        "force": force,
        "attach_command": attach_command,
    }


def register_worker_contract_tools(
    app: Any, durable_manager: DurableWorkerManager | None
) -> None:
    """Register the worker-contract tool group on a FastMCP ``app``.

    Each module-level tool function is attached to ``app`` via the
    ``@app.tool()`` decorator. Defining the functions at module scope
    (rather than nested inside this register function) keeps the
    introspection signature intact and lets tests patch ``_durable_manager``
    and call the function directly without going through the FastMCP app.
    """
    global _durable_manager
    _durable_manager = durable_manager

    app.tool()(launch_worker)
    app.tool()(send_input)
    app.tool()(capture_output)
    app.tool()(worker_status)
    app.tool()(wait_for_state)
    app.tool()(cancel_worker)
    app.tool()(worker_revoke)
