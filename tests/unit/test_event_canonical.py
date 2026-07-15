"""Tests for the canonical Oneiric event-wire conversion boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from mahavishnu.core.errors import EventEnvelopeConversionError
from mahavishnu.core.events.canonical import (
    RESERVED_EVENT_HEADERS,
    create_oneiric_envelope,
    decode_oneiric_envelope,
    encode_oneiric_envelope,
    to_mahavishnu_envelope,
    to_oneiric_envelope,
)
from mahavishnu.core.events.contract import create_event_envelope


def test_factory_preserves_explicit_identity_and_timestamp() -> None:
    event_id = UUID("12345678-1234-4234-9234-123456789012")
    timestamp = datetime(2026, 7, 14, 12, 30, tzinfo=UTC)

    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={"workflow_id": "wf-1"},
        source="mahavishnu",
        event_id=event_id,
        timestamp=timestamp,
        metadata={"adapter": "prefect"},
    )

    assert envelope.headers["event_id"] == str(event_id)
    assert envelope.headers["timestamp"] == timestamp.isoformat()
    assert envelope.headers["metadata"] == {"adapter": "prefect"}


def test_factory_rejects_reserved_extra_header() -> None:
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        create_oneiric_envelope(
            topic="workflow.started",
            payload={},
            source="mahavishnu",
            extra_headers={"source": "forged"},
        )

    assert exc_info.value.details["reason"] == "reserved_header_collision"
    assert "source" in RESERVED_EVENT_HEADERS


def test_pydantic_oneiric_round_trip_preserves_fields() -> None:
    internal = create_event_envelope(
        "workflow.started",
        "mahavishnu",
        payload={"workflow_id": "wf-1"},
        metadata={"adapter": "prefect"},
    )

    canonical = to_oneiric_envelope(internal)
    restored = to_mahavishnu_envelope(canonical)

    assert restored == internal


def test_encode_decode_round_trip() -> None:
    envelope = create_oneiric_envelope(
        topic="workflow.completed",
        payload={"workflow_id": "wf-1"},
        source="mahavishnu",
    )

    assert decode_oneiric_envelope(encode_oneiric_envelope(envelope)) == envelope


# Additional coverage: factory generation, UUID normalization, UTC conversion,
# shallow copies, non-mutation, missing required headers, invalid timestamp,
# malformed JSON, non-dict payload/headers, unsupported nested-value encoding.


def test_factory_generates_event_id_and_utc_timestamp_when_omitted() -> None:
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={"x": 1},
        source="mahavishnu",
    )

    assert isinstance(envelope.headers["event_id"], str)
    UUID(envelope.headers["event_id"])  # parses
    ts = datetime.fromisoformat(envelope.headers["timestamp"].replace("Z", "+00:00"))
    assert ts.tzinfo is not None and ts.utcoffset() == UTC.utcoffset(ts)


def test_factory_normalizes_uuid_to_string() -> None:
    event_id = UUID("12345678-1234-4234-9234-123456789012")
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={},
        source="mahavishnu",
        event_id=event_id,
    )
    assert envelope.headers["event_id"] == str(event_id)


def test_factory_converts_naive_timestamp_to_utc() -> None:
    naive = datetime(2026, 7, 14, 12, 30)
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={},
        source="mahavishnu",
        timestamp=naive,
    )
    ts = datetime.fromisoformat(envelope.headers["timestamp"].replace("Z", "+00:00"))
    assert ts.tzinfo is not None
    assert ts.utcoffset() == UTC.utcoffset(ts)


def test_factory_does_not_mutate_input_metadata() -> None:
    metadata = {"adapter": "prefect"}
    payload = {"x": 1}
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload=payload,
        source="mahavishnu",
        metadata=metadata,
    )

    assert metadata == {"adapter": "prefect"}
    assert payload == {"x": 1}
    assert envelope.headers["metadata"] is not metadata


def test_factory_returns_independent_headers_and_payload_copies() -> None:
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={"x": 1},
        source="mahavishnu",
        metadata={"adapter": "prefect"},
    )

    envelope.headers["event_id"] = "mutated"
    envelope.payload["x"] = 999

    # Subsequent factory call must not see the mutation
    fresh = create_oneiric_envelope(
        topic="workflow.started",
        payload={"x": 1},
        source="mahavishnu",
        metadata={"adapter": "prefect"},
    )
    assert "mutated" not in fresh.headers["event_id"]
    assert fresh.payload["x"] == 1


def test_decode_rejects_missing_required_header() -> None:
    raw = '{"topic":"workflow.started","payload":{},"headers":{"event_id":"abc"}}'
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope(raw)
    assert exc_info.value.details["reason"] == "missing_required_header"


def test_decode_rejects_invalid_timestamp() -> None:
    raw = (
        '{"topic":"workflow.started","payload":{},'
        '"headers":{"event_id":"abc","source":"mahavishnu",'
        '"version":"1.0.0","timestamp":"not-a-date"}}'
    )
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope(raw)
    assert exc_info.value.details["reason"] in {"invalid_timestamp", "malformed_json"}


def test_decode_rejects_malformed_json() -> None:
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope("{not-json")
    assert exc_info.value.details["reason"] == "malformed_json"


def test_decode_rejects_non_utf8_bytes() -> None:
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope(b"\xff\xfe\xff invalid utf-8")
    assert exc_info.value.details["reason"] == "malformed_json"


def test_decode_rejects_non_object_payload() -> None:
    raw = (
        '{"topic":"workflow.started","payload":"not-a-dict",'
        '"headers":{"event_id":"abc","source":"mahavishnu",'
        '"version":"1.0.0","timestamp":"2026-07-14T12:30:00+00:00"}}'
    )
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope(raw)
    assert exc_info.value.details["reason"] == "non_object_payload_or_headers"


def test_decode_rejects_non_object_headers() -> None:
    raw = (
        '{"topic":"workflow.started","payload":{},'
        '"headers":"not-a-dict"}'
    )
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope(raw)
    assert exc_info.value.details["reason"] == "non_object_payload_or_headers"


def test_decode_rejects_topic_source_version_event_id_required() -> None:
    raw = (
        '{"topic":"","payload":{},'
        '"headers":{"event_id":"abc","source":"mahavishnu",'
        '"version":"1.0.0","timestamp":"2026-07-14T12:30:00+00:00"}}'
    )
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        decode_oneiric_envelope(raw)
    assert exc_info.value.details["reason"] in {"missing_required_header", "invalid_topic"}


def test_encoder_rejects_unsupported_nested_value() -> None:
    # msgspec does not encode arbitrary Python objects (e.g. user-defined classes)
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={"x": 1},
        source="mahavishnu",
    )

    class Unsupported:
        pass

    # Inject a value type msgspec can't handle: replace payload
    object.__setattr__(envelope, "payload", {"bad": Unsupported()})

    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        encode_oneiric_envelope(envelope)
    assert exc_info.value.details["reason"] == "encode_error"


def test_decode_supports_z_suffix_timestamp() -> None:
    raw = (
        '{"topic":"workflow.started","payload":{},'
        '"headers":{"event_id":"abc","source":"mahavishnu",'
        '"version":"1.0.0","timestamp":"2026-07-14T12:30:00Z"}}'
    )
    envelope = decode_oneiric_envelope(raw)
    assert envelope.topic == "workflow.started"


def test_to_mahavishnu_envelope_preserves_correlation_causation() -> None:
    correlation_id = UUID("11111111-2222-3333-4444-555555555555")
    causation_id = UUID("66666666-7777-8888-9999-000000000000")
    internal = create_event_envelope(
        "workflow.started",
        "mahavishnu",
        payload={"x": 1},
        correlation_id=correlation_id,
        causation_id=causation_id,
    )

    canonical = to_oneiric_envelope(internal)
    restored = to_mahavishnu_envelope(canonical)

    assert restored.correlation_id == correlation_id
    assert restored.causation_id == causation_id


def test_create_oneiric_envelope_with_correlation_causation() -> None:
    correlation_id = UUID("11111111-2222-3333-4444-555555555555")
    causation_id = UUID("66666666-7777-8888-9999-000000000000")
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={},
        source="mahavishnu",
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    assert envelope.headers["correlation_id"] == str(correlation_id)
    assert envelope.headers["causation_id"] == str(causation_id)
