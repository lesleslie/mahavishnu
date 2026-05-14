"""Event publisher contract and in-process test transport.

This module provides the small C1a contract surface used to decouple
event producers from the legacy event bus while preserving a testable,
in-memory path for local validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
import inspect
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
import uuid
from uuid import UUID

from mahavishnu.core.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    EventHandler = Callable[[EventEnvelope], Awaitable[None] | None]
else:
    EventHandler = Any


def _coerce_uuid(value: UUID | str | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def create_event_envelope(
    event_type: str,
    source: str,
    payload: dict[str, object] | None = None,
    *,
    version: str = "1.0.0",
    event_id: UUID | str | None = None,
    correlation_id: UUID | str | None = None,
    causation_id: UUID | str | None = None,
    timestamp: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> EventEnvelope:
    """Create a canonical event envelope with Bodai metadata.

    Args:
        event_type: Canonical event type / topic name.
        source: Producing component identifier.
        payload: Event payload for the domain event.
        version: Envelope schema version.
        event_id: Optional explicit event identifier for tests or replay.
        correlation_id: Optional trace correlation identifier.
        causation_id: Optional causal parent event identifier.
        timestamp: Optional explicit timestamp for tests or replay.
        metadata: Additional metadata fields.
    """
    return EventEnvelope(
        event_id=_coerce_uuid(event_id) or uuid.uuid4(),
        event_type=event_type,
        version=version,
        timestamp=timestamp or datetime.now(UTC),
        source=source,
        correlation_id=_coerce_uuid(correlation_id),
        causation_id=_coerce_uuid(causation_id),
        payload=payload or {},
        metadata=metadata or {},
    )


@runtime_checkable
class EventPublisherProtocol(Protocol):
    """Protocol for event publishers used by Mahavishnu producers."""

    async def publish(self, envelope: EventEnvelope) -> EventEnvelope:
        """Publish an event envelope and return the stored envelope."""

    def subscribe(self, event_type: str, handler: EventHandler) -> str:
        """Subscribe to an exact event type or fnmatch pattern."""

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription by id."""


@dataclass(frozen=True)
class EventSubscription:
    """Subscription metadata for the in-memory transport."""

    subscription_id: str
    pattern: str
    handler: EventHandler


@dataclass
class InMemoryEventTransport:
    """Simple in-process publisher used for tests and local validation."""

    _subscriptions: dict[str, EventSubscription] = field(default_factory=dict)
    _history: list[EventEnvelope] = field(default_factory=list)

    def subscribe(self, event_type: str, handler: EventHandler) -> str:
        """Subscribe to an event type or fnmatch pattern."""
        subscription_id = f"sub-{uuid.uuid4().hex[:12]}"
        self._subscriptions[subscription_id] = EventSubscription(
            subscription_id=subscription_id,
            pattern=event_type,
            handler=handler,
        )
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription if it exists."""
        return self._subscriptions.pop(subscription_id, None) is not None

    async def publish(self, envelope: EventEnvelope) -> EventEnvelope:
        """Publish an envelope to matching subscribers."""
        self._history.append(envelope)

        for subscription in self._subscriptions.values():
            if not fnmatchcase(envelope.event_type, subscription.pattern):
                continue
            result = subscription.handler(envelope)
            if inspect.isawaitable(result):
                await result

        return envelope

    def history(self) -> list[EventEnvelope]:
        """Return a copy of published envelopes."""
        return list(self._history)

    def clear(self) -> None:
        """Reset transport history and subscriptions."""
        self._history.clear()
        self._subscriptions.clear()
