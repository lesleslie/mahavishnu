"""Canonical bridge handler for all Bodai hook channels.

Per spec §4.13 — hook coordination via Oneiric event bus.
Per spec §4.13.3 — sync-blocking events (``PreToolUse``,
``SubagentStop``, ``UserPromptSubmit``, ``Stop``,
``UserPromptExpansion``) preserve their exit codes.

Import contract: this module is the single canonical entry.
Bridges at ``.claude/hooks/<event>`` and ``~/.qwen/hooks/<event>``
each call ``handle(event_name, harness=..., payload=...)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Any, Protocol

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Cache dependency probe (SRE observability — oneiric 0.23.1+)
# ---------------------------------------------------------------------------
#
# oneiric dropped its ``oneiric[cache]`` extras spec; coredis is now
# only available via a PEP 735 group in oneiric's source pyproject,
# which does NOT propagate to consumers. ``oneiric.adapters.queue.
# redis_streams`` lazy-imports coredis inside its methods (so
# module-level imports of the bridge succeed either way); the FIRST
# publish is where the ImportError surfaces. The bridge's per-publish
# ``except Exception`` then dumps a full stack trace via
# ``logger.exception`` on every hook invocation, drowning the
# operator signal in noise.
#
# Probe coredis at module load. If missing:
#   - log+print a one-shot warning telling the operator which
#     dependency group to install;
#   - dedup the warning across processes via a sentinel file in
#     ``~/.mahavishnu/.cache_warning_emitted`` (1-hour TTL) so a
#     busy hook session doesn't print it hundreds of times;
#   - demote identical subsequent publish failures to
#     ``logger.debug`` inside ``_publish`` so the hook log stays
#     legible.
_CACHE_DEPS_AVAILABLE: bool
_CACHE_DEPS_ERROR: str | None
try:
    import coredis  # noqa: F401  - oneiric lazy-imports this transitively

    _CACHE_DEPS_AVAILABLE = True
    _CACHE_DEPS_ERROR = None
except ImportError as exc:
    _CACHE_DEPS_AVAILABLE = False
    _CACHE_DEPS_ERROR = str(exc)


def _emit_cache_availability_warning() -> None:
    """One-shot-per-process-or-sentinel warning when coredis is missing.

    Writes ``~/.mahavishnu/.cache_warning_emitted`` with a 1-hour TTL
    so a session with hundreds of hook invocations doesn't print the
    warning hundreds of times. Re-fires after the TTL or when the
    sentinel is unreadable.
    """
    if _CACHE_DEPS_AVAILABLE:
        return
    sentinel = Path.home() / ".mahavishnu" / ".cache_warning_emitted"
    dedup_seconds = 3600
    try:
        if sentinel.exists() and (time.time() - sentinel.stat().st_mtime) < dedup_seconds:
            return
    except OSError:
        pass
    msg = (
        "hook_bridge: coredis is NOT installed; every hook publish will "
        "silently fail (oneiric 0.23.1+ lazy-imports coredis inside its "
        "redis_streams adapter; the ImportError only surfaces on first "
        "publish, and the bridge swallows it to keep hooks non-blocking). "
        "Install via:\n"
        "    uv sync --group cache     # lean install\n"
        "    uv sync --group dev       # test/dev (includes cache)\n"
        f"Underlying ImportError: {_CACHE_DEPS_ERROR}"
    )
    logger.warning(msg)
    # No explicit ``print(..., file=sys.stderr)`` — Python's logging
    # module ships a ``lastResort`` handler that writes WARNING+ to
    # stderr when the root logger has no configured handlers (the
    # common case for fresh ``python -c`` and hook scripts). An
    # additional ``print`` here would duplicate the message; trust
    # ``logger.warning`` to route to stderr in fresh contexts and to
    # the operator's configured handlers in production.
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(str(time.time()))
    except OSError:
        pass


_emit_cache_availability_warning()


# Exception types we've already logged this process — demote identical
# subsequent failures to ``logger.debug`` so the hook log stays legible
# even when the cache dep is missing across hundreds of hook events.
# Dedup by type (not message) so a transient Redis-down error doesn't
# suppress a later genuine ImportError, or vice versa.
_PUBLISH_LOGGED_EXC_TYPES: set[type] = set()


# ---------------------------------------------------------------------------
# Canonical envelope (spec §4.13.2)
# ---------------------------------------------------------------------------


@dataclass
class CanonicalEnvelope:
    """Canonical hook-event envelope per spec §4.13.2.

    Fields populated from each harness's stdin JSON via
    :func:`_normalize`. ``caller_session_id`` is the cross-correlation
    key per spec §4.8 "Audit cross-correlation" — joins audit ↔ OTel
    ↔ hook-bus ↔ session log.
    """

    event: str
    harness: str
    session_id: str
    cwd: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_use_id: str | None = None  # Claude `toolu_xxx`, Qwen `toolu_xxx`
    tool_call_id: str | None = None  # Qwen `call_xxx`, optional
    permission_mode: str | None = None  # default|plan|acceptEdits|auto|dontAsk|bypassPermissions
    agent_id: str | None = None  # subagent fields
    agent_type: str | None = None
    effort: str | None = None  # `{ level: low|medium|high|xhigh|max }` (Claude-only)
    timestamp: str | None = None  # ISO 8601; always set
    caller_session_id: str | None = None  # cross-correlation key per spec §4.8
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Normalisation + bus helpers
# ---------------------------------------------------------------------------


def _normalize(harness: str, raw: dict[str, Any]) -> CanonicalEnvelope:
    """Normalize Claude/Qwen/git JSON to canonical envelope per
    spec §4.13.2.

    Populates all 15 fields. Missing fields default to ``None`` (or
    empty string for the always-present trio ``event``, ``harness``,
    ``session_id``, ``cwd``).
    """
    raw_dict = raw if isinstance(raw, dict) else {}
    effort_value = raw_dict.get("effort")
    if isinstance(effort_value, dict):
        effort_value = effort_value.get("level")
    return CanonicalEnvelope(
        event=str(raw_dict.get("hook_event_name") or raw_dict.get("event") or "?"),
        harness=harness,
        session_id=str(raw_dict.get("session_id") or ""),
        cwd=str(raw_dict.get("cwd") or ""),
        tool_name=raw_dict.get("tool_name"),
        tool_input=raw_dict.get("tool_input"),
        tool_use_id=raw_dict.get("tool_use_id"),
        tool_call_id=raw_dict.get("tool_call_id"),
        permission_mode=raw_dict.get("permission_mode"),
        agent_id=raw_dict.get("agent_id"),
        agent_type=raw_dict.get("agent_type"),
        effort=effort_value,
        timestamp=raw_dict.get("timestamp") or datetime.now(UTC).isoformat(),
        caller_session_id=raw_dict.get("caller_session_id"),
        raw=raw_dict,
    )


def _publish(*, channel: str, envelope: CanonicalEnvelope) -> None:
    """Publish to ``oneiric.adapters.queue.redis_streams``.

    Per spec §4.8 "Bus publish error tracking": failure modes (Redis
    Streams unreachable, adapter missing) increment
    ``hook_bridge_feed.errors_total`` (and the sub-counter
    ``publish_failures_total``) BEFORE the exception is swallowed.
    The bridge remains non-blocking on the hook hot path; tracking
    failures is observational.

    Fire-and-forget from sync context: most queue adapters expose
    ``async def init`` + ``async def publish`` coroutines; the
    bridge calls them from sync hook entry points. The bridge
    drives both to completion in a transient loop when no loop
    is running, or schedules ``create_task`` when one is. Init
    must complete before publish (the adapter raises
    ``LifecycleError: <adapter>-client-not-initialized`` if its
    underlying client isn't ready).

    Refs: ``docs/superpowers/specs/2026-09-14-mcp-mcp-decomposition-
    design.md`` §4.8.
    """
    import asyncio

    def _drive(coro: object) -> None:
        """Run ``coro`` to completion, or schedule-and-forget if a
        loop is running. Errors propagate to the caller's except.
        """
        if not asyncio.iscoroutine(coro):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(coro)
        else:
            # No loop running — drive the coroutine to completion
            # in a transient loop. Blocking briefly is acceptable;
            # spec §4.13.3 only mandates that SYNC-BLOCKING events
            # (PreToolUse etc.) preserve their exit codes, not that
            # the bus publish be non-blocking on the caller.
            asyncio.run(coro)

    async def _init_and_publish() -> None:
        """Single-coroutine init → publish.

        coredis 6.x binds the connection pool to the event loop.
        ``asyncio.run(coro)`` creates a fresh loop for each call; if
        ``init()`` runs in loop A (where ``__aenter__`` initialises
        the pool), and ``publish()`` runs in loop B (where the pool
        is uninitialised for this context), the publish raises
        ``RuntimeError: Connection pool is not initialized or has
        exited``. Keeping both calls in one coroutine + one
        ``asyncio.run`` keeps the pool initialisation alive.
        """
        init = getattr(adapter, "init", None)
        if init is not None:
            await init()
        await adapter.publish(channel=channel, payload=envelope.__dict__)

    try:
        # The bus reader (``read_bodai_events_since``) defaults to the
        # ``bodai:events`` stream. The oneiric queue adapter defaults
        # to ``oneiric-queue`` — different stream, so bridges would
        # publish successfully but the slash command (``/bodai-status``)
        # would never see them. Read the model's actual default from
        # ``RedisStreamsQueueSettings.model_fields`` rather than trying
        # to import a constant that does NOT exist on the oneiric
        # side (``STREAM_NAME`` lived only in
        # ``mahavishnu.core.events.bodai_subscriber`` — pre-fix this
        # file imported it from oneiric and the ImportError was
        # silently swallowed by the outer ``try/except Exception``,
        # dropping every publish). When the defaults already match,
        # skip the override entirely.
        #
        # URL handling: ``bodai_subscriber`` honors
        # ``MAHAVISHNU_BODAI_REDIS_URL``; pre-fix the publisher
        # hardcoded ``redis://localhost:6379/0``, so any environment
        # where the env var was set to a non-localhost host silently
        # diverged (subscriber reads remote, publisher writes local).
        # Read the same env var here so producer + consumer share one
        # transport. Empty string / unset → fall back to the model's
        # own default (which is itself ``redis://localhost:6379/0``
        # in oneiric).
        import os

        from oneiric.adapters.bootstrap import queued_publisher
        from oneiric.adapters.queue.redis_streams import RedisStreamsQueueSettings

        stream_default = RedisStreamsQueueSettings.model_fields["stream"].default
        url_default = RedisStreamsQueueSettings.model_fields["url"].default
        env_url = os.environ.get("MAHAVISHNU_BODAI_REDIS_URL", "").strip()

        settings_kwargs: dict[str, str] = {}
        if stream_default != "bodai:events":
            settings_kwargs["stream"] = "bodai:events"
        if env_url and env_url != url_default:
            settings_kwargs["url"] = env_url

        adapter = (
            queued_publisher(settings=RedisStreamsQueueSettings(**settings_kwargs))
            if settings_kwargs
            else queued_publisher()
        )
        _drive(_init_and_publish())
    except Exception as exc:
        if type(exc) in _PUBLISH_LOGGED_EXC_TYPES:
            # Identical failure mode already logged this process — keep
            # the hook log legible by demoting subsequent identical
            # failures to debug. Dedup is by exception type so a
            # transient Redis-down error doesn't suppress a later
            # genuine cache import error (or vice versa).
            logger.debug(
                "hook_bridge: publish still failing (deduplicated) "
                "channel=%r; first failure already logged this process",
                channel,
            )
        else:
            _PUBLISH_LOGGED_EXC_TYPES.add(type(exc))
            logger.exception(
                "hook_bridge: publish to channel=%r failed; hook caller not blocked",
                channel,
            )
        # Track the failure on the bridge's own ComponentHealth
        # feed when available; absent the feed (e.g. before the
        # first MCP tool registers the feed), the tracking itself
        # is no-op. Never block the hook hot path.
        try:
            from mahavishnu.bodai_hook_bridge import _health_monitor

            if _health_monitor is not None:
                feed = _health_monitor.get_feed("hook_bridge_feed")
                if feed is not None:
                    feed.errors_total = getattr(feed, "errors_total", 0) + 1
                    feed.publish_failures_total = getattr(feed, "publish_failures_total", 0) + 1
        except ImportError, AttributeError:
            pass
        return


def _channel_for(event: str) -> str:
    """Map event name to bus channel per spec §4.13.4.

    CamelCase → kebab-case. ``PostToolUse`` → ``post-tool-use``,
    ``PreToolUse`` → ``pre-tool-use``, ``UserPromptSubmit`` →
    ``user-prompt-submit``. Single-word events (``Stop``) pass
    through lowercased.
    """
    return "bodai.hooks." + re.sub(r"(?<!^)(?=[A-Z])", "-", event).lower()


# ---------------------------------------------------------------------------
# Per-event handlers (preserve sync-blocking semantics for §4.13.3 events)
# ---------------------------------------------------------------------------


def handle_post_tool_use(env: CanonicalEnvelope) -> int:
    """Drain pending envelopes and emit one log line per envelope.

    Body is thin in Task 1 — the existing
    ``bodai-activity-post-tool-use.py`` body moves here in a
    follow-up task. For now, return 0 (success) so callers and
    tests don't break.
    """
    return 0


def handle_session_start(env: CanonicalEnvelope) -> int:
    """Auto-provision worktree + capture jot session info.

    Body is thin in Task 1 — the existing
    ``worktree-session-isolation.py`` SessionStart arm +
    ``jot-session-start.py`` body move here in a follow-up task.
    """
    return 0


def handle_session_end(env: CanonicalEnvelope) -> int:
    """Mark worktree abandoned + drain final envelopes.

    Body is thin in Task 1 — the existing
    ``bodai-activity-subscriber.py`` + ``worktree-session-isolation
    .py`` SessionEnd arm bodies move here in a follow-up task.
    """
    return 0


def handle_user_prompt_submit(env: CanonicalEnvelope) -> int:
    """Capture the prompt for the jot log.

    Sync-blocking per spec §4.13.3. Body is thin in Task 1.
    """
    return 0


def handle_pre_tool_use(env: CanonicalEnvelope) -> int:
    """Sync-blocking policy guard per spec §4.13.3.

    Returns exit 2 to block the call when ``license_guard`` denies
    the operation. ``license_guard`` lives in
    ``mahavishnu.hook_guards`` and is planned for a future task —
    until it ships, the bridge falls back to ``0`` (permissive
    default) so the hook hot path is never blocked on a missing
    optional dependency. The bridge's delegation contract is
    pinned by ``tests/unit/test_bodai_hook_bridge.py``.
    """
    try:
        from mahavishnu.hook_guards import license_guard

        return license_guard(env)
    except ImportError:
        logger.debug(
            "hook_bridge: mahavishnu.hook_guards.license_guard not "
            "installed; PreToolUse returns 0 (permissive default). "
            "Polling guard lands in a future task."
        )
        return 0


def handle_subagent_stop(env: CanonicalEnvelope) -> int:
    """Sync-blocking per spec §4.13.3. Exit 2 = block the return."""
    return 0


def handle_stop(env: CanonicalEnvelope) -> int:
    """Sync-blocking per spec §4.13.3. Exit 2 = block the model
    from stopping.

    Default permissive (return 0). A future cancellation guard
    may inspect ``env`` and return 2 to block stop. Per spec
    §4.13.3, blocking semantics never depend on the bus
    round-trip.
    """
    return 0


def handle_user_prompt_expansion(env: CanonicalEnvelope) -> int:
    """Sync-blocking per spec §4.13.3. Exit 2 = block the expansion."""
    return 0


def handle_unknown(env: CanonicalEnvelope) -> int:
    """Fallback for unknown event names. Returns 0 + still publishes
    so subscribers can audit unknown events (forward-compat signal
    for new harness events).
    """
    return 0


def handle_post_tool_use_failure(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): tool call completed but failed.

    No Claude equivalent. Permissive default (return 0); the bridge
    publishes the failure envelope so subscribers can audit tool
    failure rates per source.
    """
    return 0


def handle_session_delete(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): explicit session deletion event.

    Distinct from ``SessionEnd`` (session normal exit) — ``SessionDelete``
    fires when the user/host deletes the session record. Permissive
    default; subscribers can use this to audit session lifecycle
    churn vs. natural completion.
    """
    return 0


def handle_message_display(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): assistant message about to be displayed.

    Pre-render hook — fired before Qwen renders the assistant turn
    to the user. Permissive default; future content-guard logic could
    inspect ``env.tool_input`` / ``env.payload`` here and return 2
    to block rendering.
    """
    return 0


def handle_stop_failure(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): stop hook returned a non-zero exit.

    Distinct from ``Stop`` (normal stop attempt) — ``StopFailure``
    fires when the model's stop sequence fails (timeout, panic, etc.).
    Permissive default; subscribers can audit stop reliability.
    """
    return 0


def handle_subagent_start(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): subagent invocation starting.

    Mirror of ``SubagentStop`` but at subagent start. Permissive
    default; subscribers can audit subagent launch rate.
    """
    return 0


def handle_pre_compact(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): context about to be compacted.

    Pre-compaction audit hook. Permissive default; future
    context-guard logic could inspect the impending compaction and
    return 2 to block.
    """
    return 0


def handle_post_compact(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): context compacted.

    Post-compaction audit hook. Permissive default; subscribers can
    audit compaction frequency.
    """
    return 0


def handle_permission_request(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): user-facing permission prompt.

    Pre-decision hook — fired when Qwen is about to ask the user for
    permission. Permissive default; a future permission-policy guard
    could inspect the request and return 2 to auto-deny.
    """
    return 0


def handle_permission_denied(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): permission request was denied.

    Post-decision audit hook. Permissive default; subscribers can
    audit denial rate.
    """
    return 0


def handle_todo_created(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): todo item created.

    Audit hook. Permissive default; subscribers can audit todo
    churn rate.
    """
    return 0


def handle_todo_completed(env: CanonicalEnvelope) -> int:
    """Qwen-only (Phase 12b): todo item completed.

    Audit hook. Permissive default; subscribers can audit todo
    completion rate.
    """
    return 0


_EVENT_HANDLERS: dict[str, Callable[[CanonicalEnvelope], int]] = {
    "PostToolUse": handle_post_tool_use,
    "SessionStart": handle_session_start,
    "SessionEnd": handle_session_end,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PreToolUse": handle_pre_tool_use,
    "SubagentStop": handle_subagent_stop,
    "Stop": handle_stop,
    "UserPromptExpansion": handle_user_prompt_expansion,
    # Phase 12b: Qwen-only events (no Claude equivalent).
    # Permissive defaults; each exists so the audit feed can
    # distinguish a Qwen-only event from a forward-compat unknown.
    "PostToolUseFailure": handle_post_tool_use_failure,
    "SessionDelete": handle_session_delete,
    "MessageDisplay": handle_message_display,
    "StopFailure": handle_stop_failure,
    "SubagentStart": handle_subagent_start,
    "PreCompact": handle_pre_compact,
    "PostCompact": handle_post_compact,
    "PermissionRequest": handle_permission_request,
    "PermissionDenied": handle_permission_denied,
    "TodoCreated": handle_todo_created,
    "TodoCompleted": handle_todo_completed,
}


# ---------------------------------------------------------------------------
# Canonical entry point
# ---------------------------------------------------------------------------


def handle(
    event_name: str,
    *,
    harness: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Canonical entry point for all Bodai hooks.

    Args:
        event_name: hook event name (``PostToolUse``, ``PreToolUse``, …)
        harness: ``"claude"`` | ``"qwen"`` | ``"git"`` | ``"codex"``
        payload: raw JSON dict from stdin

    Returns:
        Exit code: ``0`` success, ``2`` blocking error (sync
        preservation per spec §4.13.3).
    """
    env = _normalize(harness, payload or {})
    handler = _EVENT_HANDLERS.get(event_name, handle_unknown)
    exit_code = handler(env)
    # Post-decision bus publish — fire-and-forget; sync events
    # are unaffected by bus latency.
    _publish(channel=_channel_for(event_name), envelope=env)
    return exit_code


# Optional health-monitor accessor used by ``_publish`` to increment
# the bridge's own feed counters. Set by OneiricMCPServer at startup
# via ``setattr(mahavishnu.bodai_hook_bridge, "_health_monitor", hm)``.
# ``_publish`` already handles the unset case (ImportError catch
# below) so module import is safe even without the monitor.
class _HealthMonitorLike(Protocol):
    """Duck-typed protocol describing what ``_health_monitor`` must provide.

    Set externally at runtime via ``setattr``; ``object`` was the previous
    annotation and tripped ty because ``object.get_feed`` doesn't exist.
    ``get_feed`` returns a mutable record with integer fields that the
    bridge increments via ``getattr(..., default=0) + 1``.
    """

    def get_feed(self, name: str) -> Any: ...


_health_monitor: _HealthMonitorLike | None = None  # type: ignore[assignment]


__all__ = [
    "CanonicalEnvelope",
    "_normalize",
    "handle",
    "handle_pre_tool_use",
    "handle_unknown",
]
