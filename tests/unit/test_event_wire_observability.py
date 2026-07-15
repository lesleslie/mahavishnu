"""Tests for the canonical event-wire observability recorders."""

from __future__ import annotations

from unittest.mock import MagicMock

from mahavishnu.core.events import observability


def test_record_wire_converted_uses_stable_metric_and_log(monkeypatch) -> None:
    counter = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(observability, "_wire_converted", counter)
    monkeypatch.setattr(observability, "_logger", logger)

    observability.record_wire_converted(
        direction="mahavishnu_to_oneiric",
        source="mahavishnu",
    )

    counter.add.assert_called_once_with(
        1,
        attributes={
            "direction": "mahavishnu_to_oneiric",
            "source": "mahavishnu",
        },
    )
    logger.info.assert_called_once_with(
        "event.wire.converted",
        direction="mahavishnu_to_oneiric",
        source="mahavishnu",
    )


def test_record_wire_conversion_failed_emits_warning(monkeypatch) -> None:
    counter = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(observability, "_wire_conversion_failed", counter)
    monkeypatch.setattr(observability, "_logger", logger)

    observability.record_wire_conversion_failed(
        direction="encode_oneiric",
        reason="encode_error",
    )

    counter.add.assert_called_once_with(
        1,
        attributes={
            "direction": "encode_oneiric",
            "reason": "encode_error",
        },
    )
    logger.warning.assert_called_once_with(
        "event.wire.conversion_failed",
        direction="encode_oneiric",
        reason="encode_error",
    )


def test_record_legacy_decoded_emits_info(monkeypatch) -> None:
    counter = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(observability, "_legacy_decoded", counter)
    monkeypatch.setattr(observability, "_logger", logger)

    observability.record_legacy_decoded(consumer="redis_transport")

    counter.add.assert_called_once_with(
        1,
        attributes={"consumer": "redis_transport"},
    )
    logger.info.assert_called_once_with(
        "event.wire.legacy_decoded",
        consumer="redis_transport",
    )


def test_record_wire_decode_failed_emits_warning(monkeypatch) -> None:
    counter = MagicMock()
    logger = MagicMock()
    monkeypatch.setattr(observability, "_wire_decode_failed", counter)
    monkeypatch.setattr(observability, "_logger", logger)

    observability.record_wire_decode_failed(
        consumer="bodai_subscriber",
        reason="malformed_json",
    )

    counter.add.assert_called_once_with(
        1,
        attributes={
            "consumer": "bodai_subscriber",
            "reason": "malformed_json",
        },
    )
    logger.warning.assert_called_once_with(
        "event.wire.decode_failed",
        consumer="bodai_subscriber",
        reason="malformed_json",
    )
