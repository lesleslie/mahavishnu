"""Coverage-push tests for the 5 missed lines in mahavishnu/core/events/canonical.py"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest

from mahavishnu.core.errors import EventEnvelopeConversionError
from mahavishnu.core.events.canonical import (
    _validate_oneiric_envelope,
    create_oneiric_envelope,
    to_mahavishnu_envelope,
)
from oneiric.runtime.events import EventEnvelope as OneiricEventEnvelope


def test_utc_timestamp_replaces_naive_tzinfo() -> None:
    # Line 61: _utc_timestamp branch when timestamp.tzinfo is None
    naive = datetime(2026, 7, 14, 12, 30, 30)
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={},
        source="mahavishnu",
        timestamp=naive,
    )
    assert "+00:00" in envelope.headers["timestamp"]


def test_create_oneiric_envelope_merges_extra_headers() -> None:
    # Line 106: extra_headers update path
    envelope = create_oneiric_envelope(
        topic="workflow.started",
        payload={},
        source="mahavishnu",
        extra_headers={"trace_id": "abc-123", "tenant": "acme"},
    )
    assert envelope.headers["trace_id"] == "abc-123"
    assert envelope.headers["tenant"] == "acme"


def test_to_mahavishnu_envelope_defaults_missing_timestamp_to_now() -> None:
    # Line 160: empty timestamp_str branch
    canonical = OneiricEventEnvelope(
        topic="workflow.started",
        payload={"x": 1},
        headers={
            "event_id": "11111111-2222-3333-4444-555555555555",
            "source": "mahavishnu",
            "version": "1.0.0",
            "timestamp": "",
        },
    )
    restored = to_mahavishnu_envelope(canonical)
    assert isinstance(restored.timestamp, datetime)
    UUID(str(restored.event_id))


def test_validate_oneiric_envelope_rejects_non_dict_headers() -> None:
    # Line 240: headers-not-dict branch
    envelope = OneiricEventEnvelope(
        topic="workflow.started",
        payload={"x": 1},
        headers={"event_id": "abc", "source": "mahavishnu", "version": "1.0.0", "timestamp": "2026-07-14T12:30:00+00:00"},
    )
    object.__setattr__(envelope, "headers", "not-a-dict")
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        _validate_oneiric_envelope(envelope)
    assert exc_info.value.details["field"] == "headers"


def test_validate_oneiric_envelope_rejects_non_dict_payload() -> None:
    # Line 246: payload-not-dict branch
    envelope = OneiricEventEnvelope(
        topic="workflow.started",
        payload={"x": 1},
        headers={"event_id": "abc", "source": "mahavishnu", "version": "1.0.0", "timestamp": "2026-07-14T12:30:00+00:00"},
    )
    object.__setattr__(envelope, "payload", "not-a-dict")
    with pytest.raises(EventEnvelopeConversionError) as exc_info:
        _validate_oneiric_envelope(envelope)
    assert exc_info.value.details["field"] == "payload"