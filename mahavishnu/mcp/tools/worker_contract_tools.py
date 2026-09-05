"""MCP tools for the durable-worker contract.

Exposes nine FastMCP tools that proxy to a :class:`DurableWorkerManager`:

* ``launch_worker`` — spawn a worker backed by a tmux session.
* ``send_input`` — type text into the worker's pane.
* ``capture_output`` — snapshot the tmux pane buffer.
* ``worker_status`` — return the durable record plus live pane info.
* ``wait_for_state`` — poll until a target lifecycle state is reached.
* ``cancel_worker`` — soft-cancel the worker (with optional SIGKILL fallback).
* ``worker_revoke`` — mark the worker reaped (optionally with force kill).
* ``worker_run_with_settle`` — spawn a worker AND register a settle record
  in state=``proposed`` BEFORE any file is written. The settle record is
  persisted to Dhara (with dead-letter fallback) prior to launch so a
  process crash cannot leave a worker writing files without an audit trail.
* ``worker_settle`` — drive a settle run through its lifecycle:
  ``select | apply | release | discard``. ``apply`` shells out to
  ``git merge-file`` (never a hand-rolled algorithm); conflicts surface
  as structured :class:`MergeConflictError` payloads.

The functions are defined at module level (so tests can patch the global
``_durable_manager`` and call them directly), and the
``register_worker_contract_tools`` helper attaches them to a FastMCP app
via ``@app.tool()``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...workers.contract.manager import DurableWorkerManager

from mahavishnu.core.errors import ValidationError
from mahavishnu.observability.worker_metrics import WorkerMetrics
from mahavishnu.settle.merge import (
    MergeConflictError,
    MergeFailureError,
    MergeResult,
    merge_three_way,
)
from mahavishnu.settle.persistence import (
    load_record,
    persist_initial_async,
    persist_transition,
)
from mahavishnu.settle.state_machine import (
    Binding,
    SettleAction,
    SettleRunRecord,
    SettleTransitionError,
    initial_record,
    legal_next,
    transition,
)

logger = logging.getLogger(__name__)

# Module-level reference set by ``register_worker_contract_tools`` and
# patchable by tests. Reading from a module global keeps the FastMCP tool
# functions free of bound state, which simplifies test isolation.
_durable_manager: DurableWorkerManager | None = None

# Optional Dhara backend for settle persistence. May be ``None`` in tests or
# in deployments without Dhara configured — in which case the persistence
# helpers fall back to the local dead-letter file (see
# ``mahavishnu.settle.persistence``).
_settle_dhara: Any = None

# Spec §14 success-criteria instrumentation. Singleton per module; thread-safe.
_metrics = WorkerMetrics()


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
    _metrics.record("launch_worker")
    if _durable_manager is None:
        return {"worker_id": None, "state": "manager_unconfigured"}

    if session_mode == "no_tmux":
        # Backwards-compatible fallback. Falls through to legacy path.
        return {"worker_id": None, "state": "no_tmux"}

    effective_command = command or ["claude"]
    window_name = metadata.get("window_name", "main") if isinstance(metadata, dict) else "main"
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
    _metrics.record("send_input")
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
    _metrics.record("capture_output")
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
    _metrics.record("worker_status")
    if _durable_manager is None:
        return {"worker_id": worker_id, "state": "manager_unconfigured"}

    record = _durable_manager.status(worker_id)
    if record is None:
        return {"worker_id": worker_id, "state": "not_found"}

    # uptime is best-effort: a malformed record (missing, None, or
    # non-datetime ``last_seen_at`` / ``created_at``) must not crash the
    # status call. The isoformat call below is in the same try block
    # because the same malformed ``last_seen_at`` would also raise
    # there (``str.isoformat()`` doesn't exist). One guard, one
    # fallback path — keeps the contract uniform.
    uptime_seconds = 0
    last_activity_iso: str | None = None
    try:
        delta = record.last_seen_at - record.created_at
        uptime_seconds = int(delta.total_seconds())
        last_activity = getattr(record, "last_seen_at", None)
        last_activity_iso = last_activity.isoformat() if last_activity is not None else None
    except AttributeError, TypeError, ValueError:
        uptime_seconds = 0
        last_activity_iso = None

    pane_command: str | None = None
    pane_fn = getattr(_durable_manager, "pane_command", None)
    if pane_fn is not None and getattr(record, "tmux", None) is not None:
        try:
            pane_command = pane_fn(worker_id)
        except Exception:  # noqa: BLE001 - MCP boundary must preserve all operation failures
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
    _metrics.record("wait_for_state")
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


async def cancel_worker(worker_id: str, *, signal: str = "soft", grace_ms: int = 5_000) -> dict:
    """Cancel a worker gracefully. ``signal="SIGKILL"`` escalates after grace.

    The response always carries ``exit_code`` (F10) so callers can
    distinguish a graceful exit from a hard kill.
    """
    _metrics.record("cancel_worker")
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
    _metrics.record("worker_revoke")
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
    if attach_command:
        _metrics.record_attach()
    return {
        "revoked": True,
        "force": force,
        "attach_command": attach_command,
    }


def register_worker_contract_tools(
    app: Any,
    durable_manager: DurableWorkerManager | None,
    settle_dhara: Any = None,
) -> None:
    """Register the worker-contract tool group on a FastMCP ``app``.

    Each module-level tool function is attached to ``app`` via the
    ``@app.tool()`` decorator. Defining the functions at module scope
    (rather than nested inside this register function) keeps the
    introspection signature intact and lets tests patch ``_durable_manager``
    and call the function directly without going through the FastMCP app.

    ``settle_dhara`` is an optional :class:`DharaStateBackend` used for
    settle-record persistence. When ``None``, settle writes fall through
    to the local dead-letter file at
    ``~/.mahavishnu/settle-dead-letter/{run_ref}.json``.
    """
    global _durable_manager
    global _settle_dhara
    _durable_manager = durable_manager
    _settle_dhara = settle_dhara

    app.tool()(launch_worker)
    app.tool()(send_input)
    app.tool()(capture_output)
    app.tool()(worker_status)
    app.tool()(wait_for_state)
    app.tool()(cancel_worker)
    app.tool()(worker_revoke)
    app.tool()(worker_run_with_settle)
    app.tool()(worker_settle)


# ---------------------------------------------------------------------------
# Settle tools (Phase 2)
# ---------------------------------------------------------------------------


def _bindings_from_payload(raw_bindings: list[dict[str, str]]) -> tuple[Binding, ...]:
    """Normalize the JSON-friendly ``bindings`` payload into ``Binding`` tuples."""
    out: list[Binding] = []
    for idx, raw in enumerate(raw_bindings):
        if not isinstance(raw, dict):
            raise TypeError(f"bindings[{idx}] must be a dict, got {type(raw).__name__}")
        path_v = raw.get("path")
        base_v = raw.get("base", "")
        if not isinstance(path_v, str) or not path_v:
            raise TypeError(f"bindings[{idx}].path must be a non-empty string")
        if not isinstance(base_v, str):
            raise TypeError(f"bindings[{idx}].base must be a string")
        out.append(Binding(path=path_v, base=base_v))
    return tuple(out)


async def worker_run_with_settle(
    task_signature: str,
    bindings: list[dict[str, str]],
    *,
    worker_type: str = "terminal-claude",
    backend: str = "claude_tui",
    command: list[str] | None = None,
    worker_id: str | None = None,
    session_mode: str = "managed_tmux",
    max_wait_ms: int = 30_000,
    model: str | None = None,
    metadata: dict | None = None,
    run_ref: str | None = None,
) -> dict:
    """Spawn a durable worker AND register a settle record BEFORE any file write.

    The settle record (state=``proposed``) is persisted to Dhara (with
    local dead-letter fallback) before ``launch_worker`` is invoked, so
    a process crash cannot leave a worker writing files without an
    audit trail. The returned ``run_ref`` is the durable handle for
    subsequent :func:`worker_settle` calls.

    The ``bindings`` payload is a JSON-friendly list of ``{"path": str,
    "base": str}`` dicts — ``path`` is the binding's location relative
    to the worker repo, ``base`` is the pre-run content snapshot used
    for the 3-way merge during ``apply``.
    """
    _metrics.record("worker_run_with_settle")
    if not isinstance(task_signature, str) or not task_signature:
        return {
            "run_ref": None,
            "worker_id": None,
            "state": "manager_unconfigured",
            "error": "task_signature must be a non-empty string",
        }
    if not isinstance(bindings, list) or not bindings:
        return {
            "run_ref": None,
            "worker_id": None,
            "state": "manager_unconfigured",
            "error": "bindings must be a non-empty list",
        }
    if _durable_manager is None:
        return {
            "run_ref": None,
            "worker_id": None,
            "state": "manager_unconfigured",
        }
    try:
        binding_tuple = _bindings_from_payload(bindings)
    except (TypeError, ValidationError) as exc:
        return {
            "run_ref": None,
            "worker_id": None,
            "state": "invalid_bindings",
            "error": str(exc),
        }

    import uuid

    effective_run_ref = run_ref or f"settle-{uuid.uuid4().hex[:12]}"
    record = initial_record(
        run_ref=effective_run_ref,
        worker_id=worker_id or "<pending>",
        task_signature=task_signature,
        bindings=binding_tuple,
    )

    # Persistence BEFORE any worker file write. Mirrors the
    # ``dispatch_to_pool`` "persist before file write" contract from
    # ``docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md``.
    await persist_initial_async(record, dhara=_settle_dhara)

    launch_result = await launch_worker(
        prompt=task_signature,
        worker_type=worker_type,
        backend=backend,
        command=command,
        worker_id=worker_id,
        session_mode=session_mode,
        max_wait_ms=max_wait_ms,
        model=model,
        metadata=metadata,
    )
    # Re-stamp the record with the actual worker_id if it changed during launch.
    if launch_result.get("worker_id") and launch_result["worker_id"] != record.worker_id:
        restamped = SettleRunRecord(
            run_ref=record.run_ref,
            worker_id=str(launch_result["worker_id"]),
            task_signature=record.task_signature,
            bindings=record.bindings,
            state=record.state,
            created_at=record.created_at,
            updated_at=record.updated_at,
            transitions=record.transitions,
        )
        await persist_transition(restamped, dhara=_settle_dhara)
        record = restamped

    return {
        "run_ref": record.run_ref,
        "worker_id": record.worker_id,
        "state": record.state.value,
        "bindings": [b.path for b in record.bindings],
        "task_signature": record.task_signature,
        "launch": launch_result,
    }


async def worker_settle(
    run_ref: str,
    action: str,
    *,
    actor: str = "system",
    bindings_content: dict[str, str] | None = None,
    bindings_theirs: dict[str, str] | None = None,
) -> dict:
    """Drive a settle run through its lifecycle.

    ``action`` is one of ``select | apply | release | discard``. The
    state machine (:mod:`mahavishnu.settle.state_machine`) enforces
    legal transitions and raises :class:`SettleTransitionError` for
    illegal ones.

    For ``apply``, callers must pass ``bindings_content`` — a mapping of
    ``path -> ours`` (the worker's candidate content for each binding).
    Each binding is 3-way merged with ``git merge-file`` against the
    base snapshot captured at ``worker_run_with_settle`` time. Conflicts
    surface as a structured :class:`MergeConflictError` payload (the
    merged-with-markers text is returned so the caller can decide how
    to proceed).

    ``bindings_theirs`` is an optional mapping of ``path -> theirs`` for
    the 3-way merge. When omitted, ``theirs`` defaults to the binding's
    ``base`` (the "first apply" case — ours is adopted cleanly when it
    differs from base in non-overlapping ways).
    """
    _metrics.record("worker_settle")
    if not isinstance(run_ref, str) or not run_ref:
        return {
            "run_ref": run_ref,
            "action": action,
            "state": "invalid_run_ref",
            "error": "run_ref must be a non-empty string",
        }
    try:
        action_enum = SettleAction(action)
    except ValueError:
        return {
            "run_ref": run_ref,
            "action": action,
            "state": "invalid_action",
            "error": f"action must be one of {[a.value for a in SettleAction]}",
        }

    record = await load_record(run_ref, dhara=_settle_dhara)
    if record is None:
        return {
            "run_ref": run_ref,
            "action": action,
            "state": "not_found",
            "error": f"no settle record for run_ref={run_ref!r}",
        }

    # ``apply`` is special — it must run git merge-file BEFORE the state
    # transition. We do the merge against a copy so a failed merge
    # leaves the prior state intact.
    merge_payload: dict[str, Any] | None = None
    if action_enum == SettleAction.APPLY:
        if not isinstance(bindings_content, dict) or not bindings_content:
            return {
                "run_ref": run_ref,
                "action": action_enum.value,
                "state": "missing_bindings_content",
                "error": "apply requires bindings_content={path: ours}",
            }
        merge_payload = await _apply_merge(record, bindings_content, theirs=bindings_theirs)
        if isinstance(merge_payload, dict) and merge_payload.get("error"):
            return {
                "run_ref": run_ref,
                "action": action_enum.value,
                "state": merge_payload["error"],
                **merge_payload,
            }

    try:
        new_record = transition(record, action_enum, actor=actor)
    except SettleTransitionError as exc:
        return {
            "run_ref": run_ref,
            "action": action_enum.value,
            "state": "illegal_transition",
            "error": str(exc),
            "current_state": exc.details.get("current_state"),
        }

    await persist_transition(new_record, dhara=_settle_dhara)

    response: dict[str, Any] = {
        "run_ref": new_record.run_ref,
        "action": action_enum.value,
        "state": new_record.state.value,
        "transitions": list(new_record.transitions),
        "legal_next": [a.value for a in legal_next(new_record.state)],
    }
    if merge_payload is not None:
        response["merge"] = merge_payload
    return response


async def _apply_merge(
    record: SettleRunRecord,
    bindings_content: dict[str, str],
    *,
    theirs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run ``git merge-file`` for every binding in the record.

    Returns ``{"merged": {path: merged_content}, "conflict_count": N}``
    on full success. If ANY binding conflicts, returns
    ``{"error": "merge_conflict", "conflicts": [{path, merged, conflict_count}, ...]}``
    so the caller can see which paths failed.

    Note: NO state transition is performed here. The caller
    (:func:`worker_settle`) decides whether to commit the transition
    after seeing the merge result. This keeps the audit trail honest —
    a failed apply does NOT advance the state machine.

    ``theirs`` is the optional third input to the 3-way merge. When a
    path is missing from ``theirs`` (or ``theirs`` is None), ``theirs``
    defaults to ``binding.base`` — the "first apply" case where ours is
    adopted cleanly when it differs from base in non-overlapping ways.
    Pass ``theirs`` to simulate concurrent edits that diverge from
    base (the canonical conflict scenario).
    """
    merged_results: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    fatal: list[dict[str, Any]] = []

    theirs_map = theirs or {}

    for binding in record.bindings:
        ours = bindings_content.get(binding.path)
        if ours is None:
            fatal.append(
                {
                    "path": binding.path,
                    "error": "missing_ours",
                    "detail": "bindings_content must contain an entry for every binding.path",
                }
            )
            continue
        theirs_content = theirs_map.get(binding.path, binding.base)
        try:
            result: MergeResult = await merge_three_way(
                base=binding.base,
                ours=ours,
                theirs=theirs_content,
                label=binding.path,
            )
        except MergeConflictError as exc:
            conflicts.append(
                {
                    "path": binding.path,
                    "merged": exc.merged,
                    "base": exc.base,
                    "ours": exc.ours,
                    "theirs": exc.theirs,
                }
            )
        except MergeFailureError as exc:
            fatal.append({"path": binding.path, "error": "merge_failure", "detail": str(exc)})
        else:
            merged_results.append({"path": binding.path, "merged": result.merged})

    if fatal:
        return {"error": "merge_failure", "failures": fatal, "conflicts": conflicts}
    if conflicts:
        return {"error": "merge_conflict", "conflicts": conflicts}
    return {
        "merged": {m["path"]: m["merged"] for m in merged_results},
        "conflict_count": 0,
    }
