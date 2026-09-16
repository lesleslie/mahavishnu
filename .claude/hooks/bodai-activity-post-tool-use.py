#!/usr/bin/env python3
"""Bodai activity PostToolUse hook — surfaces fresh Bodai bus activity.

When called via the Claude Code PostToolUse hook (matcher ``mcp__*``),
this script does a one-shot XREAD against the Bodai EventBridge
stream (Redis Streams transport via
``mahavishnu.core.events.bodai_subscriber.read_bodai_events_since``)
and emits one ``[component] event_type key=value`` line per envelope
that has arrived since the last run. The last-seen Redis stream
``message_id`` persists in
``~/.mahavishnu/bodai-post-tool-use-state.json`` so subsequent calls
only surface fresh activity.

Phase 12a Task 5 replaces the previous JSON-queue polling path
(``~/.mahavishnu/bodai-event-queue.json`` written by the now-retired
``bodai-activity-subscriber.py`` daemon). The hook now reads from
the bus directly — one process removed from the lifecycle.

Only envelopes whose ``headers["source"]`` is one of
``{"mahavishnu", "akosha", "crackerjack"}`` are surfaced; envelopes from
unknown sources are logged at DEBUG and skipped (forward-compatibility
for additional Bodai components).

Configuration via environment variables (defaults shown):

* ``MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH`` —
  ``~/.mahavishnu/bodai-post-tool-use-state.json``
* ``MAHAVISHNU_BODAI_REDIS_URL`` — ``redis://localhost:6379/0``
* ``MAHAVISHNU_BODAI_DEBUG`` — set to a truthy value to log DEBUG messages
  to stderr; default off (forward-compatible ``unknown source`` skips).

The script exits 0 on all paths. Failures are logged to stderr so they
are visible to Claude Code but never block tool execution.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

EVENT_NAME: str = "PostToolUse"

ALLOWED_SOURCES: frozenset[str] = frozenset({"mahavishnu", "akosha", "crackerjack"})


def _mahavishnu_home() -> Path:
    override = os.environ.get("MAHAVISHNU_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu"


def _state_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-post-tool-use-state.json"


def _redis_url() -> str:
    return os.environ.get("MAHAVISHNU_BODAI_REDIS_URL", "redis://localhost:6379/0")


def _debug_enabled() -> bool:
    """Return True when ``MAHAVISHNU_BODAI_DEBUG`` is a truthy value."""
    raw = os.environ.get("MAHAVISHNU_BODAI_DEBUG", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _log(message: str) -> None:
    """Write a single line to stderr; Claude Code surfaces hook stderr as Hook output."""
    sys.stderr.write(f"Hook output: {message}\n")
    sys.stderr.flush()


def _log_debug(message: str) -> None:
    if _debug_enabled():
        sys.stderr.write(f"Hook output [DEBUG]: {message}\n")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------


def _read_state() -> dict[str, Any]:
    """Return the post-tool-use state file as a dict.

    Phase 12a Task 5 schema: ``{"last_message_id": str | None}``. The
    legacy JSON-queue state used ``{"last_read_at": float}``; for
    forward compatibility, an old ``last_read_at`` is tolerated and
    discarded (treated as "no cursor" — the next call reads from the
    beginning of the stream and updates the schema).
    """
    path = _state_path()
    if not path.exists():
        return {"last_message_id": None}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"last_message_id": None}
    if not isinstance(data, dict):
        return {"last_message_id": None}
    # Strip legacy fields if present so the file migrates cleanly.
    if "last_message_id" not in data:
        data["last_message_id"] = None
    data.pop("last_read_at", None)
    return data


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


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _envelope_source(envelope: dict[str, Any]) -> str | None:
    headers = envelope.get("headers") if isinstance(envelope, dict) else None
    if not isinstance(headers, dict):
        return None
    source = headers.get("source")
    if isinstance(source, str):
        return source
    return None


def _format_summary(envelope: dict[str, Any]) -> str:
    """Render an envelope as a one-line ``[component] event_type key=value`` summary.

    Mirrors :func:`mahavishnu.core.events.bodai_subscriber.format_bodai_summary`
    so output stays stable across the JSON-queue → bus migration.
    """
    source = _envelope_source(envelope)
    source_str = source if source else "unknown"

    topic = envelope.get("topic")
    topic_str = topic if isinstance(topic, str) and topic else "unknown"

    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    parts: list[str] = [f"[{source_str}]", topic_str]
    for key in sorted(payload.keys()):
        value = payload[key]
        if isinstance(value, bool):
            parts.append(f"{key}={'true' if value else 'false'}")
        elif isinstance(value, (int, float, str)):
            parts.append(f"{key}={value}")
        elif value is None:
            parts.append(f"{key}=null")
        else:
            try:
                parts.append(f"{key}={json.dumps(value, sort_keys=True)}")
            except (TypeError, ValueError):
                parts.append(f"{key}={value!s}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Bus read
# ---------------------------------------------------------------------------


async def _read_new_envelopes(
    *,
    last_message_id: str | None,
    redis_url: str,
) -> list[tuple[str, dict[str, Any]]]:
    """One-shot read of new envelopes from the bus.

    Returns ``[(message_id, envelope_dict), ...]`` for entries with
    Redis stream ``message_id`` strictly greater than ``last_message_id``.
    When ``last_message_id`` is ``None``, reads from the start of the
    stream. Imports :func:`read_bodai_events_since` lazily so the
    hook module loads cleanly even when the bus deps are absent.
    """
    from mahavishnu.core.events.bodai_subscriber import read_bodai_events_since

    return await read_bodai_events_since(
        last_id=last_message_id,
        redis_url=redis_url,
    )


# ---------------------------------------------------------------------------
# Mode: post-tool-use
# ---------------------------------------------------------------------------


def _post_tool_use() -> int:
    """Surface newly-arrived Bodai envelopes to the conversation.

    Reads from the bus (one-shot XREAD), filters envelopes whose
    ``headers["source"]`` is in ``ALLOWED_SOURCES``, formats each
    surviving envelope as ``[component] event_type key=value`` and
    writes the lines to stdout. The cursor advances to the maximum
    message_id surfaced (including unknown-source skips so we don't
    re-evaluate them on subsequent calls).
    """
    state = _read_state()
    last_message_id = state.get("last_message_id")

    try:
        envelopes = asyncio.run(
            _read_new_envelopes(
                last_message_id=last_message_id if isinstance(last_message_id, str) else None,
                redis_url=_redis_url(),
            )
        )
    except Exception as exc:  # noqa: BLE001 - boundary handler preserves the existing exit code
        _log(f"bodai-activity-post-tool-use: bus read failed: {exc}")
        return 0

    if not envelopes:
        return 0

    new_last_id = last_message_id
    surfaced = 0
    skipped_unknown = 0

    for message_id, envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        source = _envelope_source(envelope)
        if source not in ALLOWED_SOURCES:
            skipped_unknown += 1
            _log_debug(
                f"bodai-activity-post-tool-use: skipping envelope from unknown "
                f"source={source!r} topic={envelope.get('topic')!r} message_id={message_id!r}"
            )
            new_last_id = message_id
            continue
        try:
            summary = _format_summary(envelope)
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            _log("bodai-activity-post-tool-use: failed to format envelope")
            new_last_id = message_id
            continue
        print(summary, flush=True)
        surfaced += 1
        new_last_id = message_id

    if new_last_id != last_message_id or surfaced or skipped_unknown:
        state["last_message_id"] = new_last_id
        try:
            _write_state(state)
        except OSError:
            _log("bodai-activity-post-tool-use: failed to persist state")

    if surfaced:
        _log(
            f"bodai-activity-post-tool-use: surfaced={surfaced} "
            f"skipped_unknown={skipped_unknown}"
        )

    return 0


def _run_hook(payload: dict[str, Any]) -> int:
    # The hook is invoked without --mode; it is PostToolUse-only.
    return _post_tool_use()


def main(argv: list[str] | None = None) -> int:
    # Read the Claude Code payload from stdin (augmentation for bridge routing).
    payload_text = sys.stdin.read()
    try:
        payload = json.loads(payload_text) if payload_text else {}
    except json.JSONDecodeError:
        payload = {}
    # Preserve the original exit code from the existing hook logic.
    exit_code = _run_hook(payload)
    # Fire-and-forget bridge routing for bus publish + audit (Option B augmentation).
    # The bridge call is intentionally NOT allowed to influence exit_code — the
    # existing hook semantics (always exit 0) are authoritative per spec §4.13.3.
    try:
        _CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
        if _CLAUDE_PROJECT_DIR:
            sys.path.insert(0, _CLAUDE_PROJECT_DIR)
        from mahavishnu.bodai_hook_bridge import handle
        handle(event_name=EVENT_NAME, harness="claude", payload=payload)
    except Exception as exc:  # noqa: BLE001 - boundary handler preserves the existing exit code
        sys.stderr.write(
            f"Hook output: bodai-activity-post-tool-use: bridge routing failed: {exc}\n"
        )
        sys.stderr.flush()
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
        sys.stderr.write("Hook output: bodai-activity-post-tool-use: unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
