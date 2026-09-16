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
import re
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable



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
        event=str(
            raw_dict.get("hook_event_name") or raw_dict.get("event") or "?"
        ),
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

    Refs: ``docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-
    design.md`` §4.8.
    """
    try:
        from oneiric.adapters.bootstrap import queued_publisher

        queued_publisher().publish(channel=channel, payload=envelope.__dict__)
    except Exception:
        logger.exception(
            "hook_bridge: publish to channel=%r failed; "
            "hook caller not blocked",
            channel,
        )
        # Track the failure on the bridge's own ComponentHealth
        # feed when available; absent the feed (e.g. before the
        # first MCP tool registers the feed), the tracking itself
        # is no-op. Never block the hook hot path.
        try:
            from mahavishnu.bodai_hook_bridge import _health_monitor

            feed = _health_monitor.get_feed("hook_bridge_feed")
            if feed is not None:
                feed.errors_total = getattr(feed, "errors_total", 0) + 1
                feed.publish_failures_total = (
                    getattr(feed, "publish_failures_total", 0) + 1
                )
        except (ImportError, AttributeError):
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


_EVENT_HANDLERS: dict[str, Callable[[CanonicalEnvelope], int]] = {
    "PostToolUse": handle_post_tool_use,
    "SessionStart": handle_session_start,
    "SessionEnd": handle_session_end,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PreToolUse": handle_pre_tool_use,
    "SubagentStop": handle_subagent_stop,
    "Stop": handle_stop,
    "UserPromptExpansion": handle_user_prompt_expansion,
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
_health_monitor: object | None = None  # type: ignore[assignment]


__all__ = [
    "CanonicalEnvelope",
    "_normalize",
    "handle",
    "handle_pre_tool_use",
    "handle_unknown",
]
