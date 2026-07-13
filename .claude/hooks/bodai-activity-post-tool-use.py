#!/usr/bin/env python3
"""Bodai activity PostToolUse hook — drains the queue and emits summaries.

When called via the Claude Code PostToolUse hook (matcher ``mcp__*``),
this script reads ``~/.mahavishnu/bodai-event-queue.json`` and emits one
``[component] event_type key=value`` line per envelope that has arrived
since the last run. The last-read timestamp persists in
``~/.mahavishnu/bodai-post-tool-use-state.json`` so subsequent calls only
surface fresh activity.

Only envelopes whose ``headers["source"]`` is one of
``{"mahavishnu", "akosha", "crackerjack"}`` are surfaced; envelopes from
unknown sources are logged at DEBUG and skipped (forward-compatibility
for additional Bodai components).

Configuration via environment variables (defaults shown):

* ``MAHAVISHNU_BODAI_QUEUE_PATH`` — ``~/.mahavishnu/bodai-event-queue.json``
* ``MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH`` —
  ``~/.mahavishnu/bodai-post-tool-use-state.json``
* ``MAHAVISHNU_BODAI_DEBUG`` — set to a truthy value to log DEBUG messages
  to stderr; default off (forward-compatible ``unknown source`` skips).

The script exits 0 on all paths. Failures are logged to stderr so they
are visible to Claude Code but never block tool execution.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ALLOWED_SOURCES: frozenset[str] = frozenset({"mahavishnu", "akosha", "crackerjack"})


def _mahavishnu_home() -> Path:
    override = os.environ.get("MAHAVISHNU_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu"


def _queue_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-event-queue.json"


def _state_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-post-tool-use-state.json"


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
# Queue + state I/O
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


def _read_state() -> dict[str, Any]:
    """Return the post-tool-use state file as a dict (empty if missing)."""
    path = _state_path()
    if not path.exists():
        return {"last_read_at": 0.0}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"last_read_at": 0.0}
    if not isinstance(data, dict):
        return {"last_read_at": 0.0}
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


def _envelope_received_at(envelope: dict[str, Any]) -> float:
    """Return the envelope's ``received_at`` timestamp; default ``0.0``."""
    value = envelope.get("received_at")
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


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
    but operates directly on the dict shape persisted by ``subscribe_to_bodai_events``
    so this hook has no project-import requirement.
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
# Mode: post-tool-use
# ---------------------------------------------------------------------------


def _post_tool_use() -> int:
    """Surface newly-arrived Bodai envelopes to the conversation.

    Reads the queue, filters envelopes whose ``received_at`` exceeds the
    stored cursor, formats each surviving envelope as
    ``[component] event_type key=value`` and writes the lines to stdout.
    The cursor is updated to the maximum ``received_at`` that was
    surfaced (or kept at its current value when nothing matches).
    """
    state = _read_state()
    last_read_at = float(state.get("last_read_at", 0.0) or 0.0)

    envelopes = _read_queue()
    if not envelopes:
        # Nothing to do; keep the cursor so we don't lose future events
        return 0

    new_max_at = last_read_at
    surfaced = 0
    skipped_unknown = 0

    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        received_at = _envelope_received_at(envelope)
        if received_at <= last_read_at:
            # Already surfaced; skip without bumping the cursor
            continue
        source = _envelope_source(envelope)
        if source not in ALLOWED_SOURCES:
            skipped_unknown += 1
            _log_debug(
                f"bodai-activity-post-tool-use: skipping envelope from unknown "
                f"source={source!r} topic={envelope.get('topic')!r}"
            )
            # Still advance the cursor so we don't keep re-evaluating it
            if received_at > new_max_at:
                new_max_at = received_at
            continue
        try:
            summary = _format_summary(envelope)
        except Exception:
            _log("bodai-activity-post-tool-use: failed to format envelope")
            if received_at > new_max_at:
                new_max_at = received_at
            continue
        print(summary, flush=True)
        surfaced += 1
        if received_at > new_max_at:
            new_max_at = received_at

    if surfaced or skipped_unknown or new_max_at > last_read_at:
        state["last_read_at"] = new_max_at
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


def main(argv: list[str] | None = None) -> int:
    # The hook is invoked without --mode; it is PostToolUse-only.
    return _post_tool_use()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.stderr.write("Hook output: bodai-activity-post-tool-use: unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
