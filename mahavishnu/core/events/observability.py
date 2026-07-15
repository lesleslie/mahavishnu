"""Observability instruments for the canonical event-wire boundary."""

from __future__ import annotations

from oneiric.core.logging import get_logger
from opentelemetry import metrics

_logger = get_logger("mahavishnu.event_wire")
_meter = metrics.get_meter(__name__)
_wire_converted = _meter.create_counter("mahavishnu.event.wire.converted_total")
_wire_conversion_failed = _meter.create_counter("mahavishnu.event.wire.conversion_failed_total")
_legacy_decoded = _meter.create_counter("mahavishnu.event.wire.legacy_decoded_total")
_wire_decode_failed = _meter.create_counter("mahavishnu.event.wire.decode_failed_total")


def record_wire_converted(*, direction: str, source: str) -> None:
    attributes = {"direction": direction, "source": source}
    _wire_converted.add(1, attributes=attributes)
    _logger.info("event.wire.converted", **attributes)


def record_wire_conversion_failed(*, direction: str, reason: str) -> None:
    attributes = {"direction": direction, "reason": reason}
    _wire_conversion_failed.add(1, attributes=attributes)
    _logger.warning("event.wire.conversion_failed", **attributes)


def record_legacy_decoded(*, consumer: str) -> None:
    attributes = {"consumer": consumer}
    _legacy_decoded.add(1, attributes=attributes)
    _logger.info("event.wire.legacy_decoded", **attributes)


def record_wire_decode_failed(*, consumer: str, reason: str) -> None:
    attributes = {"consumer": consumer, "reason": reason}
    _wire_decode_failed.add(1, attributes=attributes)
    _logger.warning("event.wire.decode_failed", **attributes)
