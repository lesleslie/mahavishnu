"""Typed conversion boundary for the canonical Oneiric event wire.

Reserved Oneiric headers (per the approved spec):

- ``event_id``: producer-generated UUID/ULID string.
- ``source``: producing component name.
- ``version``: semantic envelope/schema version.
- ``timestamp``: UTC ISO-8601 string.
- ``correlation_id``: optional trace/workflow correlation identifier.
- ``causation_id``: optional parent-event identifier.
- ``metadata``: nested compatibility dictionary for Mahavishnu metadata.

This module is the only conversion path used by Redis and EventBridge
adapters. ``to_mahavishnu_envelope`` exists for the Phase 1 Redis
handlers and legacy tests; new production consumers must use the
Oneiric envelope directly.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
import uuid
from uuid import UUID

import msgspec
from oneiric.runtime.events import EventEnvelope as OneiricEventEnvelope

from mahavishnu.core.errors import EventEnvelopeConversionError
from mahavishnu.core.events.envelope import EventEnvelope as MahavishnuEventEnvelope
from mahavishnu.core.events.observability import (
    record_wire_conversion_failed,
    record_wire_converted,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

REQUIRED_EVENT_HEADERS = frozenset({"event_id", "source", "version", "timestamp"})
OPTIONAL_EVENT_HEADERS = frozenset({"correlation_id", "causation_id", "metadata"})
RESERVED_EVENT_HEADERS = REQUIRED_EVENT_HEADERS | OPTIONAL_EVENT_HEADERS


class OneiricEventPublisherProtocol(Protocol):
    """Publisher boundary for Oneiric wire envelopes."""

    def publish(
        self,
        envelope: OneiricEventEnvelope,
    ) -> Awaitable[object] | object: ...


def _identifier(value: UUID | str | None) -> str | None:
    return str(value) if value is not None else None


def _utc_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat()


def create_oneiric_envelope(
    topic: str,
    payload: dict[str, Any],
    *,
    source: str,
    version: str = "1.0.0",
    event_id: UUID | str | None = None,
    correlation_id: UUID | str | None = None,
    causation_id: UUID | str | None = None,
    timestamp: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    extra_headers: dict[str, Any] | None = None,
) -> OneiricEventEnvelope:
    """Build a canonical Oneiric envelope with reserved headers."""
    collision = RESERVED_EVENT_HEADERS.intersection(extra_headers or {})
    if collision:
        raise EventEnvelopeConversionError(
            direction="create_oneiric",
            reason="reserved_header_collision",
            details={"keys": sorted(collision)},
        )

    headers: dict[str, Any] = {
        "event_id": _identifier(event_id) or str(uuid.uuid4()),
        "source": source,
        "version": version,
        "timestamp": _utc_timestamp(timestamp),
    }

    correlation_value = _identifier(correlation_id)
    if correlation_value is not None:
        headers["correlation_id"] = correlation_value

    causation_value = _identifier(causation_id)
    if causation_value is not None:
        headers["causation_id"] = causation_value

    if metadata is not None:
        headers["metadata"] = deepcopy(metadata)

    if extra_headers:
        headers.update(extra_headers)

    envelope = OneiricEventEnvelope(
        topic=topic,
        payload=deepcopy(payload),
        headers=headers,
    )

    record_wire_converted(
        direction="mahavishnu_to_oneiric",
        source=source,
    )
    return envelope


def to_oneiric_envelope(envelope: MahavishnuEventEnvelope) -> OneiricEventEnvelope:
    """Convert a Mahavishnu Pydantic envelope to the canonical Oneiric envelope."""
    headers: dict[str, Any] = {
        "event_id": str(envelope.event_id),
        "source": envelope.source,
        "version": envelope.version,
        "timestamp": envelope.timestamp.isoformat(),
    }
    if envelope.correlation_id is not None:
        headers["correlation_id"] = str(envelope.correlation_id)
    if envelope.causation_id is not None:
        headers["causation_id"] = str(envelope.causation_id)
    if envelope.metadata:
        headers["metadata"] = deepcopy(envelope.metadata)

    canonical = OneiricEventEnvelope(
        topic=envelope.event_type,
        payload=deepcopy(envelope.payload),
        headers=headers,
    )

    record_wire_converted(
        direction="mahavishnu_to_oneiric",
        source=envelope.source,
    )
    return canonical


def to_mahavishnu_envelope(envelope: OneiricEventEnvelope) -> MahavishnuEventEnvelope:
    """Transitional reverse converter for Phase 1 only.

    Used by Redis transport handlers and the explicit legacy decoder
    branch in the Bodai subscriber. New production consumers must use
    the Oneiric envelope directly.
    """
    headers = envelope.headers

    timestamp_str = headers.get("timestamp", "")
    if not timestamp_str:
        timestamp = datetime.now(UTC)
    else:
        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

    metadata = headers.get("metadata") or {}
    correlation_id = _parse_uuid_or_none(headers.get("correlation_id"))
    causation_id = _parse_uuid_or_none(headers.get("causation_id"))

    record_wire_converted(
        direction="oneiric_to_mahavishnu",
        source=str(headers.get("source", "")),
    )

    return MahavishnuEventEnvelope(
        event_id=UUID(headers["event_id"]),
        event_type=envelope.topic,
        version=headers["version"],
        timestamp=timestamp,
        source=headers["source"],
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=deepcopy(envelope.payload),
        metadata=deepcopy(metadata),
    )


def _parse_uuid_or_none(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    return UUID(str(value))


def encode_oneiric_envelope(envelope: OneiricEventEnvelope) -> str:
    try:
        return msgspec.json.encode(envelope).decode("utf-8")
    except (TypeError, ValueError, msgspec.EncodeError) as exc:
        record_wire_conversion_failed(
            direction="encode_oneiric",
            reason="encode_error",
        )
        raise EventEnvelopeConversionError(
            direction="encode_oneiric",
            reason="encode_error",
            details={"error": str(exc)},
        ) from exc


def decode_oneiric_envelope(raw: str | bytes) -> OneiricEventEnvelope:
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        envelope = msgspec.json.decode(encoded, type=OneiricEventEnvelope)
    except (UnicodeError, msgspec.DecodeError) as exc:
        if isinstance(exc, msgspec.ValidationError):
            record_wire_conversion_failed(
                direction="decode_oneiric",
                reason="non_object_payload_or_headers",
            )
            raise EventEnvelopeConversionError(
                direction="decode_oneiric",
                reason="non_object_payload_or_headers",
                details={"error": str(exc)},
            ) from exc
        record_wire_conversion_failed(
            direction="decode_oneiric",
            reason="malformed_json",
        )
        raise EventEnvelopeConversionError(
            direction="decode_oneiric",
            reason="malformed_json",
            details={"error": str(exc)},
        ) from exc
    return _validate_oneiric_envelope(envelope)


def _validate_oneiric_envelope(envelope: OneiricEventEnvelope) -> OneiricEventEnvelope:
    headers = envelope.headers
    payload = envelope.payload
    topic = envelope.topic

    if not isinstance(headers, dict):
        raise EventEnvelopeConversionError(
            direction="decode_oneiric",
            reason="non_object_payload_or_headers",
            details={"field": "headers"},
        )
    if not isinstance(payload, dict):
        raise EventEnvelopeConversionError(
            direction="decode_oneiric",
            reason="non_object_payload_or_headers",
            details={"field": "payload"},
        )
    if not topic or not isinstance(topic, str):
        raise EventEnvelopeConversionError(
            direction="decode_oneiric",
            reason="missing_required_header",
            details={"key": "topic"},
        )

    for key in REQUIRED_EVENT_HEADERS:
        value = headers.get(key)
        if value is None or value == "":
            raise EventEnvelopeConversionError(
                direction="decode_oneiric",
                reason="missing_required_header",
                details={"key": key},
            )

    timestamp_str = headers["timestamp"]
    try:
        datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EventEnvelopeConversionError(
            direction="decode_oneiric",
            reason="invalid_timestamp",
            details={"error": str(exc)},
        ) from exc

    return envelope
