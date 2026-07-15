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

Decoding priority per Redis-stream message:

1. ``envelope=<JSON>`` field → ``decode_oneiric_envelope`` (canonical).
2. Direct ``topic/payload/headers`` triplet → ``create_oneiric_envelope``
   (canonical) using ``headers["source"]`` as the producer source.
3. If canonical decoding fails AND ``MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE``
   is enabled, decode the raw blob via the Pydantic
   ``mahavishnu.core.events.envelope.EventEnvelope.from_json`` and hand
   the Pydantic envelope to the callback unchanged.
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

from mahavishnu.core.events.canonical import (
    create_oneiric_envelope,
    decode_oneiric_envelope,
)
from mahavishnu.core.events.envelope import (
    EventEnvelope as MahavishnuEventEnvelope,
)
from mahavishnu.core.events.observability import (
    record_legacy_decoded,
    record_wire_decode_failed,
)
from mahavishnu.core.errors import EventEnvelopeConversionError

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


def _accept_legacy_wire() -> bool:
    """Return True when the legacy Pydantic wire format should be accepted.

    Controlled by ``MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE``. Default: enabled.
    """
    value = os.environ.get(
        "MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE",
        "true",
    )
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def _coerce_str(value: Any) -> str | None:
    """Decode bytes/bytearray to UTF-8 str; pass through str; drop everything else."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return None


def _coerce_json_object(value: Any) -> dict[str, Any] | None:
    """Parse JSON bytes/str into a dict; return ``None`` for any other shape."""
    raw = _coerce_str(value)
    if raw is None:
        return None
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else None


def _decode_legacy_envelope(raw: str | bytes) -> MahavishnuEventEnvelope:
    """Decode a raw envelope blob via the Pydantic legacy decoder."""
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8")
    else:
        text = raw
    return MahavishnuEventEnvelope.from_json(text)


def _decode_canonical_field(envelope_blob: Any) -> EventEnvelope:
    """Decode a canonical ``envelope=<JSON>`` blob."""
    raw = envelope_blob
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeError as exc:
            raise EventEnvelopeConversionError(
                direction="decode_oneiric",
                reason="non_utf8_json",
                details={"error": str(exc)},
            ) from exc
    return decode_oneiric_envelope(raw)


def _decode_direct_triplet(
    message_payload: dict[str, Any],
) -> EventEnvelope:
    """Decode a direct ``topic/payload/headers`` triplet."""
    topic = message_payload.get("topic")
    payload_obj = _coerce_json_object(message_payload.get("payload", "{}"))
    headers_obj = _coerce_json_object(message_payload.get("headers", "{}"))
    if not topic or payload_obj is None or headers_obj is None:
        raise EventEnvelopeConversionError(
            direction="decode_oneiric",
            reason="no_envelope_data",
            details={
                "has_topic": bool(topic),
                "has_payload": payload_obj is not None,
                "has_headers": headers_obj is not None,
                "keys": sorted(message_payload.keys()),
            },
        )
    source = headers_obj.get("source") or SOURCE_UNKNOWN
    return create_oneiric_envelope(
        topic=str(topic),
        payload=payload_obj,
        source=str(source),
        extra_headers={
            k: v
            for k, v in headers_obj.items()
            if k != "source"
        },
    )


def _decode_with_legacy_fallback(
    *,
    canonical_call: Any,
    fallback_blob: Any,
    canonical_failure_reason: str = "canonical_decode_failed",
) -> EventEnvelope | MahavishnuEventEnvelope:
    """Run a canonical decode; fall back to legacy Pydantic on failure."""
    try:
        return canonical_call()
    except EventEnvelopeConversionError as exc:
        details = exc.details if isinstance(exc.details, dict) else {}
        canonical_reason = str(details.get("reason") or canonical_failure_reason)
        if not _accept_legacy_wire():
            record_wire_decode_failed(
                consumer="bodai_subscriber",
                reason=canonical_reason,
            )
            raise
        try:
            record_legacy_decoded(consumer="bodai_subscriber")
            return _decode_legacy_envelope(fallback_blob)
        except Exception as legacy_exc:
            record_wire_decode_failed(
                consumer="bodai_subscriber",
                reason="legacy_decode_failed",
            )
            raise EventEnvelopeConversionError(
                direction="decode_legacy",
                reason="legacy_decode_failed",
                details={
                    "canonical_reason": canonical_reason,
                    "legacy_error": str(legacy_exc),
                },
            ) from legacy_exc


def _decode_envelope(
    message_payload: dict[str, Any],
) -> EventEnvelope | MahavishnuEventEnvelope:
    """Decode a Redis-stream message payload into an envelope.

    Canonical-first decoding:

    1. If ``envelope=<JSON>`` field is present, call
       :func:`decode_oneiric_envelope`.
    2. Else, if a direct ``topic/payload/headers`` triplet is present, call
       :func:`create_oneiric_envelope` using ``headers["source"]`` as the
       producer source. ``event_type`` is NOT treated as ``topic``.
    3. If canonical decoding fails AND ``MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE``
       is enabled, decode the raw ``envelope`` blob via the Pydantic legacy
       decoder. ``record_legacy_decoded`` is emitted exactly once per legacy
       decode.

    Raises:
        EventEnvelopeConversionError: when canonical decoding fails and
            legacy reads are disabled, or when both paths fail.
    """
    envelope_blob = message_payload.get("envelope")

    if envelope_blob is not None and envelope_blob != b"" and envelope_blob != "":
        return _decode_with_legacy_fallback(
            canonical_call=lambda: _decode_canonical_field(envelope_blob),
            fallback_blob=envelope_blob,
        )

    try:
        return _decode_direct_triplet(message_payload)
    except EventEnvelopeConversionError as exc:
        details = exc.details if isinstance(exc.details, dict) else {}
        canonical_reason = str(details.get("reason") or "direct_triplet_failed")
        record_wire_decode_failed(
            consumer="bodai_subscriber",
            reason=canonical_reason,
        )
        if not _accept_legacy_wire():
            raise
        fallback_blob = (
            envelope_blob
            if isinstance(envelope_blob, (str, bytes, bytearray))
            else json.dumps(message_payload)
        )
        try:
            record_legacy_decoded(consumer="bodai_subscriber")
            return _decode_legacy_envelope(fallback_blob)
        except Exception as legacy_exc:
            raise EventEnvelopeConversionError(
                direction="decode_legacy",
                reason="legacy_decode_failed",
                details={
                    "canonical_reason": canonical_reason,
                    "legacy_error": str(legacy_exc),
                },
            ) from legacy_exc


# ---------------------------------------------------------------------------
# Subscriber helpers (split for pyscn cyclomatic complexity ≤ 10)
# ---------------------------------------------------------------------------


def _create_redis_client(
    redis_url: str,
    client_factory: Callable[..., Any] | None,
) -> Any | None:
    """Return a redis client or ``None`` when redis.asyncio is unavailable.

    A ``None`` return signals the caller to idle until cancellation.
    """
    if client_factory is not None:
        return client_factory(redis_url)
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]
    except ImportError:
        _logger.warning(
            "bodai.subscriber: redis.asyncio is not installed; "
            "subscriber will idle until cancellation",
        )
        return None
    return aioredis.from_url(redis_url, decode_responses=False)


async def _idle_until_cancelled(
    cancellation_token: asyncio.Event | None,
) -> None:
    """Block until the cancellation token is set (or forever)."""
    if cancellation_token is not None:
        await cancellation_token.wait()
    else:
        await asyncio.Event().wait()


async def _ensure_consumer_group(
    client: Any,
    *,
    stream_name: str,
    consumer_group: str,
) -> None:
    """Idempotently create the consumer group; tolerate ``BUSYGROUP``."""
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


async def _read_stream_batch(
    client: Any,
    *,
    consumer_group: str,
    consumer_name: str,
    stream_name: str,
    block_ms: int,
) -> list[Any]:
    """Single XREADGROUP call against the configured stream."""
    return await client.xreadgroup(
        groupname=consumer_group,
        consumername=consumer_name,
        streams={stream_name: ">"},
        count=DEFAULT_XREADGROUP_COUNT,
        block=block_ms,
    )


async def _wait_for_retry_or_cancellation(
    cancellation_token: asyncio.Event | None,
    *,
    delay: float,
) -> bool:
    """Sleep ``delay`` seconds; return ``True`` when cancellation was observed.

    ``False`` indicates the timer elapsed (we should retry).
    """
    if cancellation_token is None:
        await asyncio.sleep(delay)
        return False
    try:
        await asyncio.wait_for(cancellation_token.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


def _normalize_stream_entry(
    entry: object,
) -> tuple[str, dict[str, Any]] | None:
    """Return ``(message_id, payload_dict)`` for a valid Redis-stream entry."""
    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
        return None
    raw_id, raw_fields = entry[0], entry[1]
    if not isinstance(raw_fields, dict):
        return None
    message_id = _coerce_str(raw_id) or str(raw_id)
    payload: dict[str, Any] = {}
    for field_key, field_value in raw_fields.items():
        key_str = _coerce_str(field_key) or str(field_key)
        if isinstance(field_value, (bytes, bytearray)):
            try:
                field_value = field_value.decode("utf-8")
            except UnicodeError:
                continue
        payload[key_str] = field_value
    return message_id, payload


async def _invoke_callback(
    callback: Callable[[Any], Awaitable[None]],
    envelope: Any,
    *,
    timeout_seconds: float,
) -> bool:
    """Invoke the callback with timeout. Returns ``True`` when it ran.

    ``False`` indicates the callback timed out — caller must NOT ack.

    Exception ordering: ``CancelledError`` re-raises (terminates the loop),
    ``asyncio.TimeoutError`` returns ``False`` (allow retry), other
    ``Exception`` is logged at WARNING and returns ``True`` so the
    subscription continues with the next message.
    """
    try:
        await asyncio.wait_for(callback(envelope), timeout=timeout_seconds)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        return False
    except Exception:
        _logger.exception(
            "bodai.subscriber: callback raised; proceeding to next envelope",
        )
        return True
    return True


async def _append_envelope_to_queue(
    envelope: Any,
    *,
    queue_path: Path,
    queue_cap: int,
) -> None:
    """Run the blocking filesystem write through a worker thread."""
    await asyncio.to_thread(
        append_to_queue,
        _envelope_to_dict(envelope),
        queue_path=queue_path,
        queue_cap=queue_cap,
    )


async def _acknowledge_message(
    client: Any,
    *,
    stream_name: str,
    consumer_group: str,
    message_id: str,
) -> None:
    """XACK a single message; log + swallow transport errors so the loop continues."""
    try:
        await client.xack(stream_name, consumer_group, message_id)
    except Exception:
        _logger.exception(
            "bodai.subscriber: xack failed for message_id=%s",
            message_id,
        )


async def _close_redis_client(client: Any) -> None:
    """Close the redis client via ``aclose`` then ``close`` (best-effort)."""
    try:
        await client.aclose()
    except Exception:
        try:
            await client.close()
        except Exception:
            pass


async def _process_stream_entry(
    client: Any,
    entry: object,
    *,
    callback: Callable[[Any], Awaitable[None]],
    queue_path: Path,
    queue_cap: int,
    per_event_timeout_seconds: float,
    stream_name: str,
    consumer_group: str,
) -> None:
    """Decode → invoke → append → ack a single Redis-stream entry."""
    normalized = _normalize_stream_entry(entry)
    if normalized is None:
        return
    message_id, payload = normalized

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
        return

    callback_ran = await _invoke_callback(
        callback,
        envelope,
        timeout_seconds=per_event_timeout_seconds,
    )
    if not callback_ran:
        _logger.warning(
            "bodai.subscriber: callback timed out after %.1fs; "
            "not acking message_id=%s",
            per_event_timeout_seconds,
            message_id,
        )
        return

    try:
        await _append_envelope_to_queue(
            envelope, queue_path=queue_path, queue_cap=queue_cap,
        )
    except Exception:
        _logger.exception(
            "bodai.subscriber: failed to append envelope to queue path=%s",
            queue_path,
        )

    await _acknowledge_message(
        client,
        stream_name=stream_name,
        consumer_group=consumer_group,
        message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def _process_response(
    response: list[Any],
    *,
    client: Any,
    callback: Callable[[Any], Awaitable[None]],
    queue_path: Path,
    queue_cap: int,
    per_event_timeout_seconds: float,
    stream_name: str,
    consumer_group: str,
) -> None:
    """Decode → invoke → append → ack each entry returned by ``xreadgroup``."""
    for _stream_key, entries in response:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            await _process_stream_entry(
                client,
                entry,
                callback=callback,
                queue_path=queue_path,
                queue_cap=queue_cap,
                per_event_timeout_seconds=per_event_timeout_seconds,
                stream_name=stream_name,
                consumer_group=consumer_group,
            )


async def _run_subscription_loop(
    client: Any,
    *,
    consumer_name: str,
    consumer_group: str,
    stream_name: str,
    xreadgroup_block_ms: int,
    callback: Callable[[Any], Awaitable[None]],
    queue_path: Path,
    queue_cap: int,
    per_event_timeout_seconds: float,
    cancellation_token: asyncio.Event | None,
) -> None:
    """Coordinator loop: cancel → read → retry → iterate → close.

    Owns the loop and backoff; delegates all per-message work to helpers.
    """
    backoff = DEFAULT_RECONNECT_BACKOFF_SECONDS
    while True:
        if cancellation_token is not None and cancellation_token.is_set():
            break

        try:
            response = await _read_stream_batch(
                client,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
                stream_name=stream_name,
                block_ms=xreadgroup_block_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning(
                "bodai.subscriber: xreadgroup error: %s",
                exc,
                exc_info=True,
            )
            cancelled = await _wait_for_retry_or_cancellation(
                cancellation_token, delay=backoff,
            )
            if cancelled:
                break
            backoff = min(backoff * 2.0, DEFAULT_RECONNECT_BACKOFF_MAX_SECONDS)
            continue

        backoff = DEFAULT_RECONNECT_BACKOFF_SECONDS

        if not response:
            # Yield to the event loop so cancellation_token and other tasks
            # can progress when the transport returns immediately (mock or
            # idle stream). The Redis BLOCK timeout provides the natural
            # yield in production; this explicit sleep covers the
            # always-empty-response case (tests, idle streams).
            await asyncio.sleep(0)
            continue

        await _process_response(
            response,
            client=client,
            callback=callback,
            queue_path=queue_path,
            queue_cap=queue_cap,
            per_event_timeout_seconds=per_event_timeout_seconds,
            stream_name=stream_name,
            consumer_group=consumer_group,
        )


async def subscribe_to_bodai_events(
    callback: Callable[[Any], Awaitable[None]],
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
    client = _create_redis_client(redis_url, client_factory)
    effective_queue_path = _resolve_queue_path(queue_path)
    if client is None:
        await _idle_until_cancelled(cancellation_token)
        return

    try:
        await _ensure_consumer_group(
            client,
            stream_name=stream_name,
            consumer_group=consumer_group,
        )
        await _run_subscription_loop(
            client,
            consumer_name=name,
            consumer_group=consumer_group,
            stream_name=stream_name,
            xreadgroup_block_ms=xreadgroup_block_ms,
            callback=callback,
            queue_path=effective_queue_path,
            queue_cap=queue_cap,
            per_event_timeout_seconds=per_event_timeout_seconds,
            cancellation_token=cancellation_token,
        )
    finally:
        await _close_redis_client(client)


__all__ = [
    "DEFAULT_QUEUE_CAP",
    "DEFAULT_PER_EVENT_TIMEOUT_SECONDS",
    "STREAM_NAME",
    "append_to_queue",
    "format_bodai_summary",
    "subscribe_to_bodai_events",
]