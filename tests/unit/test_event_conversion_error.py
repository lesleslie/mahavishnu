"""Tests for the EventEnvelopeConversionError structured error class."""

from __future__ import annotations

from mahavishnu.core.errors import ErrorCode, EventEnvelopeConversionError


def test_conversion_error_is_structured_validation_error() -> None:
    error = EventEnvelopeConversionError(
        direction="mahavishnu_to_oneiric",
        reason="reserved_header_collision",
        details={"key": "source"},
    )

    assert error.error_code is ErrorCode.VALIDATION_ERROR
    assert error.details == {
        "key": "source",
        "direction": "mahavishnu_to_oneiric",
        "reason": "reserved_header_collision",
    }


def test_conversion_error_protects_direction_and_reason() -> None:
    error = EventEnvelopeConversionError(
        direction="decode_oneiric",
        reason="malformed_json",
        details={"direction": "wrong", "reason": "wrong"},
    )

    assert error.details["direction"] == "decode_oneiric"
    assert error.details["reason"] == "malformed_json"
