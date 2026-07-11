"""Bodai EventBridge subscriber — Mahavishnu-side consumer of Oneiric EventBridge.

This module is the Mahavishnu-side consumer for the unified Bodai activity
event stream. It consumes ``oneiric.runtime.events.EventEnvelope`` objects
from Oneiric EventBridge (Redis Streams transport) and persists them to a
local queue file at ``~/.mahavishnu/bodai-event-queue.json`` (atomic write,
cap at 100 entries, oldest dropped first).

Phase 5's ``.claude/hooks/mahavishnu-activity-stream.py`` is the
WebSocket-based transition state (Mahavishnu-only). This module is the
EventBridge-based steady state, replacing the Phase 5 hook in Phase 6.4
of the Bodai observability plan. See
``docs/plans/2026-07-11-phase-6-bodai-observability.md`` and
``.claude/decisions/bodai-observability-pattern.md`` for the operational
pattern this module implements.

The canonical envelope is the Oneiric msgspec ``EventEnvelope``
(``oneiric.runtime.events.EventEnvelope``) — fields are ``topic``,
``payload``, and ``headers``. The headers dictionary carries
``source``, ``event_id``, ``version``, ``timestamp``, and any
component-specific metadata. This module does not modify or re-export
the canonical envelope.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import socket
from typing import TYPE_CHECKING, Any

from oneiric.runtime.events import EventEnvelope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

DEFAULT_QUEUE_CAP = 100
DEFAULT_PER_EVENT_TIMEOUT_SECONDS = 30.0
DEFAULT_RECONNECT_BACKOFF_SECONDS = 2.0
DEFAULT_RECONNECT_BACKOFF_MAX_SECONDS = 30.0
DEFAULT_XREADGROUP_BLOCK_MS = 5000
DEFAULT_XREADGROUP_COUNT = 10
STREAM_NAME = "bodai:events"
SOURCE_UNKNOWN = "unknown"

_logger = logging.getLogger(__name__)


def _default_queue_path() -> Path:
    """Return the default queue-file location under ``~/.mahavishnu/``."""
    override = os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu" / "bodai-event-queue.json"


def _resolve_queue_path(queue_path: Path | str | None) -> Path:
    """Return the effective queue path, defaulting to ``~/.mahavishnu/...``.

    Accepts both ``Path`` objects and ``str`` for caller convenience. Strings
    are converted via ``Path(...)``; ``~`` is expanded.
    """
    if queue_path is None:
        return _default_queue_path()
    if isinstance(queue_path, Path):
        return queue_path.expanduser()
    return Path(queue_path).expanduser()


def _default_consumer_name() -> str:
    """Return a stable per-host consumer name for Redis Streams."""
    try:
        return socket.gethostname()
    except OSError:
        return "mahavishnu-bodai-subscriber"


def _read_queue(path: Path) -> list[dict[str, Any]]:
    """Read the queue file atomically. Returns ``[]`` if the file is missing or unreadable."""
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


def _write_queue_atomic(path: Path, envelopes: list[dict[str, Any]]) -> None:
    """Write the queue file atomically via tmp + rename. Mirrors Phase 5 hook pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(envelopes, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def append_to_queue(
    envelope_dict: dict[str, Any],
    *,
    queue_path: Path | None = None,
    queue_cap: int = DEFAULT_QUEUE_CAP,
) -> None:
    """Append an envelope dict to the queue file, dropping oldest entries past the cap.

    Atomic write: the queue file is rewritten via tmp + rename so concurrent
    readers (e.g., the Phase 6 PostToolUse hook) never observe a partial file.
    """
    path = _resolve_queue_path(queue_path)
    envelopes = _read_queue(path)
    envelopes.append(envelope_dict)
    if len(envelopes) > queue_cap:
        envelopes = envelopes[-queue_cap:]
    _write_queue_atomic(path, envelopes)


def format_bodai_summary(envelope: EventEnvelope) -> str:
    """Return a one-line ``[source] event_type key=value`` summary.

    The summary format is what Claude Code will surface inline after a tool
    invocation. The component prefix comes from
    ``envelope.headers['source']`` (set by the EventBridge producer) and the
    event_type is ``envelope.topic``. Trailing key=value pairs come from the
    payload dict, sorted for determinism.

    Example outputs:
        ``[mahavishnu] workflow_completed workflow_id=wid_abc``
        ``[akosha] aggregation_completed suite=quality``
        ``[crackerjack] test_run_completed passed=42 failed=0``

    Missing headers or payload fields fall back to ``[unknown] unknown``;
    this function never raises so a malformed envelope cannot abort the
    subscriber loop.
    """
    headers = envelope.headers if isinstance(envelope.headers, dict) else {}
    payload = envelope.payload if isinstance(envelope.payload, dict) else {}

    source = headers.get("source") if isinstance(headers, dict) else None
    source_str = str(source) if source else SOURCE_UNKNOWN
    topic_str = str(envelope.topic) if envelope.topic else SOURCE_UNKNOWN

    parts: list[str] = [f"[{source_str}]", topic_str]
    for key in sorted(payload.keys()):
        value = payload[key]
        if isinstance(value, (bool, int, float, str)):
            parts.append(f"{key}={value}")
        elif value is None:
            parts.append(f"{key}=null")
        else:
            try:
                parts.append(f"{key}={json.dumps(value, sort_keys=True)}")
            except (TypeError, ValueError):
                parts.append(f"{key}={value!s}")

    return " ".join(parts)


def _envelope_to_dict(envelope: EventEnvelope) -> dict[str, Any]:
    """Serialize an ``EventEnvelope`` into the queue's plain-dict shape."""
    return {
        "topic": str(envelope.topic),
        "payload": dict(envelope.payload) if isinstance(envelope.payload, dict) else {},
        "headers": dict(envelope.headers) if isinstance(envelope.headers, dict) else {},
        "received_at": asyncio.get_event_loop().time(),
    }


def _decode_envelope(message_payload: dict[str, Any]) -> EventEnvelope:
    """Decode a Redis-stream message payload into an ``EventEnvelope``.

    Accepts either a pre-parsed ``envelope`` field (canonical JSON envelope)
    or ``topic`` + ``payload`` + ``headers`` fields as published by the
    Mahavishnu Redis publisher (``RedisEventTransport.publish`` stores the
    full envelope under the ``envelope`` key as canonical JSON).
    """
    envelope_blob = message_payload.get("envelope")
    if isinstance(envelope_blob, (bytes, bytearray)):
        envelope_blob = envelope_blob.decode("utf-8")
    if isinstance(envelope_blob, str) and envelope_blob:
        data = json.loads(envelope_blob)
    else:
        topic = message_payload.get("topic") or message_payload.get("event_type")
        payload_raw = message_payload.get("payload", "{}")
        headers_raw = message_payload.get("headers", "{}")
        if isinstance(payload_raw, (bytes, bytearray)):
            payload_raw = payload_raw.decode("utf-8")
        if isinstance(headers_raw, (bytes, bytearray)):
            headers_raw = headers_raw.decode("utf-8")
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
        headers = json.loads(headers_raw) if isinstance(headers_raw, str) else {}
        data = {"topic": topic, "payload": payload, "headers": headers}

    if not isinstance(data, dict):
        raise ValueError("envelope JSON did not deserialize to a dict")
    topic_value = data.get("topic")
    if not isinstance(topic_value, str) or not topic_value:
        raise ValueError("envelope payload missing 'topic'")
    return EventEnvelope(
        topic=str(topic_value),
        payload=dict(data.get("payload") or {}),
        headers=dict(data.get("headers") or {}),
    )


async def subscribe_to_bodai_events(
    callback: Callable[[EventEnvelope], Awaitable[None]],
    *,
    redis_url: str = "redis://localhost:6379/0",
    consumer_group: str = "mahavishnu-claude-observers",
    consumer_name: str | None = None,
    queue_path: Path | None = None,
    queue_cap: int = DEFAULT_QUEUE_CAP,
    per_event_timeout_seconds: float = DEFAULT_PER_EVENT_TIMEOUT_SECONDS,
    cancellation_token: asyncio.Event | None = None,
    stream_name: str = STREAM_NAME,
    xreadgroup_block_ms: int = DEFAULT_XREADGROUP_BLOCK_MS,
    client_factory: Callable[..., Any] | None = None,
) -> None:
    """Subscribe to the Bodai EventBridge stream and persist each envelope to the queue.

    Blocks until ``cancellation_token`` is set. Mirrors Phase 5's
    loop-until-dry error-trapping: a callback exception never aborts the
    subscription — it is logged at WARNING and the next envelope proceeds.

    The transport is Redis Streams via ``redis.asyncio.client.Redis`` using a
    consumer group. Each message is decoded as an ``EventEnvelope``, the
    caller-supplied ``callback`` is invoked, and the envelope dict is
    appended to the local queue file via :func:`append_to_queue`. Messages
    are acknowledged (XACK) after the callback completes successfully.

    Args:
        callback: Async function invoked for each decoded envelope.
        redis_url: Redis connection URL (defaults to local dev Redis).
        consumer_group: Name of the Redis Streams consumer group to join.
        consumer_name: Name for this consumer within the group. Defaults to
            ``socket.gethostname()``.
        queue_path: Local queue-file path. Defaults to
            ``~/.mahavishnu/bodai-event-queue.json``. Override via the
            ``MAHAVISHNU_BODAI_QUEUE_PATH`` env var when omitted.
        queue_cap: Maximum number of envelopes retained in the queue file.
        per_event_timeout_seconds: Per-callback timeout. The callback is
            awaited with this ceiling; a timeout is logged and the message
            is not acked (so another consumer can retry).
        cancellation_token: Stop signal. Production uses a signal handler;
            tests pass an ``asyncio.Event`` to break the loop deterministically.
        stream_name: Redis stream key (defaults to ``bodai:events``).
        xreadgroup_block_ms: Redis XREADGROUP BLOCK parameter (milliseconds).
            Default 5000ms. Tests typically override with a small value (e.g.
            ``10``) so the loop unblocks quickly when the mock returns no
            data and ``cancellation_token`` is set.
    """
    name = consumer_name or _default_consumer_name()

    if client_factory is not None:
        client = client_factory(redis_url)
        effective_queue_path = _resolve_queue_path(queue_path)
    else:
        try:
            import redis.asyncio as aioredis  # type: ignore[import-not-found]
        except ImportError:
            _logger.warning(
                "bodai.subscriber: redis.asyncio is not installed; "
                "subscriber will idle until cancellation",
            )
            if cancellation_token is not None:
                await cancellation_token.wait()
            else:
                await asyncio.Event().wait()
            return

        client = aioredis.from_url(redis_url, decode_responses=False)
        effective_queue_path = _resolve_queue_path(queue_path)

    try:
        try:
            await client.xgroup_create(
                name=stream_name,
                groupname=consumer_group,
                id="$",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                _logger.debug(
                    "bodai.subscriber: consumer group already exists",
                    extra={"stream": stream_name, "group": consumer_group},
                )
            else:
                _logger.warning(
                    "bodai.subscriber: xgroup_create failed: %s",
                    exc,
                    extra={"stream": stream_name, "group": consumer_group},
                )

        backoff = DEFAULT_RECONNECT_BACKOFF_SECONDS
        while True:
            if cancellation_token is not None and cancellation_token.is_set():
                break

            try:
                response = await client.xreadgroup(
                    groupname=consumer_group,
                    consumername=name,
                    streams={stream_name: ">"},
                    count=DEFAULT_XREADGROUP_COUNT,
                    block=xreadgroup_block_ms,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.warning(
                    "bodai.subscriber: xreadgroup error: %s",
                    exc,
                    exc_info=True,
                )
                try:
                    if cancellation_token is not None:
                        await asyncio.wait_for(
                            cancellation_token.wait(), timeout=backoff
                        )
                        break
                    await asyncio.sleep(backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2.0, DEFAULT_RECONNECT_BACKOFF_MAX_SECONDS)
                continue

            backoff = DEFAULT_RECONNECT_BACKOFF_SECONDS

            if not response:
                continue

            for _stream_key, entries in response:
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    message_id = entry[0]
                    if isinstance(message_id, (bytes, bytearray)):
                        message_id = message_id.decode("utf-8")
                    raw_fields = entry[1]
                    if not isinstance(raw_fields, dict):
                        continue
                    payload: dict[str, Any] = {}
                    for field_key, field_value in raw_fields.items():
                        key_str = (
                            field_key.decode("utf-8")
                            if isinstance(field_key, (bytes, bytearray))
                            else str(field_key)
                        )
                        if isinstance(field_value, (bytes, bytearray)):
                            field_value = field_value.decode("utf-8")
                        payload[key_str] = field_value

                    try:
                        envelope = _decode_envelope(payload)
                    except Exception as exc:
                        _logger.warning(
                            "bodai.subscriber: failed to decode envelope "
                            "(message not acked for retry): %s",
                            exc,
                            exc_info=True,
                            extra={"message_id": message_id},
                        )
                        continue

                    try:
                        await asyncio.wait_for(
                            callback(envelope),
                            timeout=per_event_timeout_seconds,
                        )
                    except TimeoutError:
                        _logger.warning(
                            "bodai.subscriber: callback timed out after %.1fs; "
                            "not acking message_id=%s",
                            per_event_timeout_seconds,
                            message_id,
                        )
                        continue
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _logger.exception(
                            "bodai.subscriber: callback raised for "
                            "message_id=%s; proceeding to next envelope",
                            message_id,
                        )

                    try:
                        append_to_queue(
                            _envelope_to_dict(envelope),
                            queue_path=effective_queue_path,
                            queue_cap=queue_cap,
                        )
                    except Exception:
                        _logger.exception(
                            "bodai.subscriber: failed to append envelope "
                            "to queue path=%s",
                            effective_queue_path,
                        )

                    try:
                        await client.xack(stream_name, consumer_group, message_id)
                    except Exception:
                        _logger.exception(
                            "bodai.subscriber: xack failed for message_id=%s",
                            message_id,
                        )
    finally:
        try:
            await client.aclose()
        except Exception:
            try:
                await client.close()
            except Exception:
                pass


__all__ = [
    "DEFAULT_QUEUE_CAP",
    "DEFAULT_PER_EVENT_TIMEOUT_SECONDS",
    "STREAM_NAME",
    "append_to_queue",
    "format_bodai_summary",
    "subscribe_to_bodai_events",
]