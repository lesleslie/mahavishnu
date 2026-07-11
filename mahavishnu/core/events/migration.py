"""Migration helpers for upgrading legacy events to EventEnvelope format.
Provides utilities to convert events from the old dataclass-based format
to the new typed EventEnvelope format.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID

from mahavishnu.core.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


def migrate_legacy_event_bus_event(
    legacy: dict[str, Any],
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
) -> EventEnvelope:
    """Migrate a legacy system-wide event dataclass dict to EventEnvelope.
    The legacy event structure has this shape:
        {
            "id": "uuid-string",
            "type": "worker.started",
            "data": {...},
            "timestamp": "2026-04-05T12:00:00+00:00",
            "source": "code_index_service",
            "version": 1  (integer)
        }

    Args:
        legacy: Dictionary from legacy Event.to_dict() format.
        correlation_id: Optional correlation ID to attach.
        causation_id: Optional causation ID to attach.

    Returns:
        EventEnvelope with migrated data.
    """
    event_id = legacy.get("id")
    if event_id:
        event_id = str(event_id)
    else:
        from uuid import uuid4

        event_id = str(uuid4())

    return EventEnvelope(
        event_id=UUID(event_id),
        event_type=legacy.get("type", "unknown"),
        version=_migrate_version(legacy.get("version", 1)),
        timestamp=_parse_timestamp(legacy.get("timestamp")),
        source=legacy.get("source", "unknown"),
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=legacy.get("data", {}),
        metadata={"migrated_from": "event_bus_v1"},
    )


def migrate_legacy_task_event(
    legacy: dict[str, Any],
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
) -> EventEnvelope:
    """Migrate a legacy TaskEvent dataclass dict to EventEnvelope.
    The legacy TaskEvent (from task_notifications.py) has:
        {
            "event_type": "created",
            "task_id": "abc-123",
            "data": {...},
            "timestamp": "2026-04-05T12:00:00+00:00",
            "metadata": {...}
        }

    Args:
        legacy: Dictionary from legacy TaskEvent.to_dict() format.
        correlation_id: Optional correlation ID to attach.
        causation_id: Optional causation ID to attach.

    Returns:
        EventEnvelope with migrated data.
    """
    return EventEnvelope(
        event_type=f"task.{legacy.get('event_type', 'unknown')}",
        source="task_notifications",
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload={
            "task_id": legacy.get("task_id"),
            **legacy.get("data", {}),
        },
        metadata={
            "migrated_from": "task_event_v1",
            **legacy.get("metadata", {}),
        },
    )


def migrate_legacy_webhook_event(
    legacy: dict[str, Any],
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
) -> EventEnvelope:
    """Migrate a legacy WebhookEvent dataclass dict to EventEnvelope.
    The legacy WebhookEvent (from webhook_handler.py) has:
        {
            "event_id": "uuid-string",
            "source": "github",
            "event_type": "push",
            "repository": "org/repo",
            "received_at": "2026-04-05T12:00:00+00:00",
            "sender": "username"
        }

    Args:
        legacy: Dictionary from legacy WebhookEvent.to_dict() format.
        correlation_id: Optional correlation ID to attach.
        causation_id: Optional causation ID to attach.

    Returns:
        EventEnvelope with migrated data.
    """
    received_at = legacy.get("received_at")
    if isinstance(received_at, str):
        received_at = datetime.fromisoformat(received_at)

    event_id = legacy.get("event_id")
    if event_id:
        event_id = UUID(str(event_id))

    return EventEnvelope(
        event_id=event_id,  # ty: ignore[invalid-argument-type]
        event_type=f"webhook.{legacy.get('event_type', 'unknown')}",
        version="1.0.0",
        timestamp=received_at or datetime.now(UTC),
        source=f"webhook.{legacy.get('source', 'unknown')}",
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload={"repository": legacy.get("repository"), "sender": legacy.get("sender")},
        metadata={"migrated_from": "webhook_event_v1"},
    )


def _migrate_version(legacy_version: int | str) -> str:
    """Convert legacy integer version to semver string.

    Args:
        legacy_version: Integer version (e.g., 1) or semver string.

    Returns:
        Semver string (e.g., "1.0.0").
    """
    if isinstance(legacy_version, int):
        return f"{legacy_version}.0.0"
    return str(legacy_version)


def _parse_timestamp(ts: str | None) -> datetime:
    """Parse a timestamp string into datetime.

    Args:
        ts: ISO format timestamp string or None.

    Returns:
        datetime instance (UTC now if ts is None).
    """
    if ts is None:
        return datetime.now(UTC)
    return datetime.fromisoformat(ts)
