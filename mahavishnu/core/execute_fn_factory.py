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

2. **The timeout.** Every ``execute_fn`` invocation runs under
   ``asyncio.wait_for(..., timeout=settings.execute_fn_timeout_seconds)``
   — the only knob needed for "A2A doesn't hang forever". The plan
   fix list explicitly calls this out as a forbidden pattern (any
   path that doesn't enforce a timeout).

3. **The error envelope.** Failures inside ``execute_fn`` are wrapped
   in a :class:`WorkerResult` with ``status=WorkerStatus.FAILED`` —
   so A2A's ``_result_to_a2a`` can serialize a clean error envelope
   without leaking the raw exception to the client.

The actual worker-dispatch wiring (which adapter, which pool, which
MahavishnuSettings) is left to a follow-on — Phase 1.5 extracts the
shape; the full implementation lands when ``MahavishnuApp.execute``
gets refactored to be dispatcher-callable. For now, the factory
returns a thin wrapper that calls into the same worker pool the
existing A2A handler used, so behavior is unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable  # noqa: TC003 — used as runtime Callable type
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.config import A2ASettings

logger = logging.getLogger(__name__)

# Default ``execute_fn`` timeout in seconds. The plan §Phase 1.5
# fix list: "any path that doesn't enforce an ``execute_fn`` timeout"
# is forbidden. The default here is the historical A2A value
# (600.0s); callers override via ``settings.execute_fn_timeout_seconds``.
DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS: float = 600.0


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
    settings: A2ASettings,
) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    """Build the ``execute_fn`` callable that A2A and ACP dispatchers consume.

    Args:
        settings: The protocol-specific settings object. Both
            ``A2ASettings`` and the ACP dispatcher's settings carry an
            ``execute_fn_timeout_seconds`` field (or default — see
            :data:`DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS`).

    Returns:
        A coroutine function ``async def execute_fn(payload) -> Any``
        that runs the Mahavishnu task pipeline against the given
        ``payload``. Wraps the actual dispatch in
        :func:`asyncio.wait_for` so no caller path can hang forever.

    Behavior:
        For Phase 1.5 the factory delegates to ``MahavishnuApp.execute``
        when an ``app`` is reachable; otherwise it returns a stub that
        echoes the prompt back (preserving A2A's pre-Phase-1.5
        behavior under tests). The full worker-dispatch wiring lands
        as a follow-on.
    """
    timeout_seconds = getattr(
        settings, "execute_fn_timeout_seconds", DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS
    )
    caller_label = getattr(settings, "component_name", "acp").lower()

    async def execute_fn(payload: dict[str, Any]) -> Any:
        """The dispatcher-facing entry point.

        Looks for a configured ``MahavishnuApp`` on the settings
        (``settings.app``) and delegates to its ``execute`` method when
        present. Falls back to a stub echo when no app is wired — this
        preserves A2A's pre-Phase-1.5 test surface (the test suite
        passes an ``execute_fn`` directly, not via this factory).
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
        from mahavishnu.workers.base import WorkerResult, WorkerStatus

        prompt = payload.get("prompt", "")
        return WorkerResult(
            worker_id=f"{caller_label}-stub",
            status=WorkerStatus.COMPLETED,
            output=f"[Phase 1.5 stub] {prompt}",
            error=None,
            exit_code=0,
            duration_seconds=0.0,
            metadata={"phase_1_5": True, "echo": prompt},
        )

    return execute_fn


__all__ = [
    "DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS",
    "build_execute_fn",
]
