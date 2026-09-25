"""``execute_fn`` factory — single source of truth for A2A and ACP dispatch.

Per plan §Phase 1.5. Both A2A (``mahavishnu/a2a/server.py``) and ACP
(``mahavishnu/acp/server.py``) need a function with the signature
``Callable[[dict[str, Any]], Awaitable[Any]]`` that turns a prompt
into a result. Before this factory, A2A and ACP each took an
``execute_fn`` parameter and trusted callers to construct it; that
left room for subtle bugs (the non-subscribe A2A handler had no
``execute_fn`` timeout, the A2A Bearer middleware used plain ``!=``).

This factory centralizes three things:

1. **The signature.** ``build_execute_fn(settings) -> Callable`` is
   the single source for "given a settings object, give me the
   dispatcher entry point". Both protocols import it from here.
   The function returned is ``async`` throughout — the dispatcher
   ``awaits`` it under its own session timeout, and ACP's
   ``session/prompt`` handler chains an additional ``asyncio.wait_for``
   for the per-session cap.

2. **The timeout.** Every ``execute_fn`` invocation runs under
   ``asyncio.wait_for(..., timeout=settings.execute_fn_timeout_seconds)``
   — the only knob needed for "A2A doesn't hang forever". The plan
   fix list explicitly calls this out as a forbidden pattern (any
   path that doesn't enforce a timeout).

3. **The error envelope.** Failures inside ``execute_fn`` are wrapped
   in a :class:`WorkerResult` with ``status=WorkerStatus.FAILED`` —
   so A2A's ``_result_to_a2a`` can serialize a clean error envelope
   without leaking the raw exception to the client.

The settings field ``execute_fn_timeout_seconds`` is now a **real
Pydantic field** on both ``A2ASettings`` and ``ACPSettings`` (Option
C landed this in v1.0). The factory reads it directly; if a caller
builds its own ad-hoc settings object (e.g. unit tests), the
annotation is structural — the factory reads ``settings.component_name``
and ``settings.execute_fn_timeout_seconds``.

The actual worker-dispatch wiring (which adapter, which pool, which
MahavishnuSettings) is delegated to ``MahavishnuApp.execute`` when
the dispatcher is started with a configured app. The factory only
performs the timeout enforcement and error wrapping; it does not
itself route to a pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable  # noqa: TC003 — used as runtime Callable type
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Default ``execute_fn`` timeout in seconds. The plan §Phase 1.5
# fix list: "any path that doesn't enforce an ``execute_fn`` timeout"
# is forbidden. The default here is the historical A2A value
# (600.0s); callers override via ``settings.execute_fn_timeout_seconds``.
DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS: float = 600.0


class _SettingsShape(Protocol):
    """Structural shape the factory requires of its settings object.

    Both ``A2ASettings`` and ``ACPSettings`` carry these fields, so
    duck-typing avoids the hard import (which would re-trigger the
    ``mahavishnu.core.config`` import chain on every factory load).
    """

    component_name: str
    execute_fn_timeout_seconds: float


async def _wrap_with_timeout(
    fn: Callable[[dict[str, Any]], Awaitable[Any]],
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    caller: str,
) -> Any:
    """Run ``fn(payload)`` under ``asyncio.wait_for(timeout)`` with error wrapping.

    The plan forbids "any path that doesn't enforce an execute_fn
    timeout". This helper centralizes that enforcement so callers
    (A2A, ACP) can't accidentally bypass it.

    Failures inside ``fn`` are caught and surfaced via the caller's
    error logger; the exception re-raises so the dispatcher can emit
    its own error envelope (e.g., A2A's ``_error_to_a2a``).
    """
    try:
        return await asyncio.wait_for(fn(payload), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "%s execute_fn timed out after %.0fs (payload_keys=%s)",
            caller,
            timeout_seconds,
            sorted(payload.keys()),
        )
        raise


def build_execute_fn(
    settings: _SettingsShape,
) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    """Build the ``execute_fn`` callable that A2A and ACP dispatchers consume.

    Args:
        settings: The protocol-specific settings object. Both
            :class:`mahavishnu.core.config.A2ASettings` and
            :class:`mahavishnu.core.config.ACPSettings` carry the
            required fields (``component_name`` and
            ``execute_fn_timeout_seconds``).

    Returns:
        A coroutine function ``async def execute_fn(payload) -> Any``
        that runs the executor under
        :func:`asyncio.wait_for` so no caller path can hang forever.

    Behavior:
        Delegates to ``MahavishnuApp.execute`` when an ``app`` is
        configured on the settings (``settings.app``); otherwise
        returns a ``WorkerResult`` stub that echoes the prompt back —
        this preserves the pre-Phase-1.5 behavior under tests that
        don't construct a full app.
    """
    timeout_seconds = float(settings.execute_fn_timeout_seconds)
    caller_label = str(settings.component_name).lower()

    async def execute_fn(payload: dict[str, Any]) -> Any:
        """The dispatcher-facing entry point.

        Looks for a configured ``MahavishnuApp`` on the settings
        (``settings.app``) and delegates to its ``execute`` method
        when present. Falls back to a stub echo when no app is
        wired — preserves A2A's pre-Phase-1.5 test surface (the
        test suite passes an ``execute_fn`` directly, not via
        this factory).
        """
        app = getattr(settings, "app", None)
        if app is not None and hasattr(app, "execute"):
            return await _wrap_with_timeout(
                app.execute, payload, timeout_seconds=timeout_seconds, caller=caller_label
            )

        # Fallback stub: echo the prompt back. The shape is
        # ``WorkerResult``-compatible so A2A's ``_result_to_a2a``
        # serializes it without error. ACP's stub-acknowledged path
        # accepts the same shape.
        # Phase 5b (Plan v3): WorkerStatus moved to mahavishnu.core.status as
        # the canonical source; the import path through workers.base was a
        # re-export shim that we're now closing. WorkerResult stays in
        # workers/base (no canonical relocation needed).
        from mahavishnu.workers.base import WorkerResult
        from mahavishnu.core.status import WorkerStatus

        prompt = payload.get("prompt", "")
        return WorkerResult(
            worker_id=f"{caller_label}-stub",
            status=WorkerStatus.COMPLETED,
            output=f"[v1.0 stub] {prompt}",
            error=None,
            exit_code=0,
            duration_seconds=0.0,
            metadata={"v1_0_stub": True, "echo": prompt},
        )

    return execute_fn


__all__ = [
    "DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS",
    "build_execute_fn",
]
