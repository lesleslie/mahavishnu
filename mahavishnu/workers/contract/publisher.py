from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.core.events.envelope import EventEnvelope
from mahavishnu.core.events.worker_topics import is_worker_topic

if TYPE_CHECKING:
    from collections.abc import Callable


class CanonicalEnvelopePublisher:
    """Publish canonical ``EventEnvelope`` instances for the worker contract.

    This is the single implementation of
    :class:`mahavishnu.workers.contract.manager.EventPublisher`: the
    contract's ``emit(payload, topic)`` parameter order is the canonical
    form, and this publisher matches it exactly.

    Produces canonical Mahavishnu ``EventEnvelope`` instances so the
    existing EventBridge pipeline consumes them unchanged. Only the
    canonical ``worker.*`` topics are published — any other topic is
    dropped, because the durable-worker event stream carries worker
    topics only.

    Args:
        source: Producer identifier written to ``EventEnvelope.source``.
        sink: Callable that receives each built envelope.
        now: Clock used for ``EventEnvelope.timestamp`` (injectable).
    """

    def __init__(
        self,
        *,
        source: str,
        sink: Callable[[EventEnvelope], None],
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._source = source
        self._sink = sink
        self._now = now

    def emit(self, payload: dict[str, Any], topic: str) -> None:
        """Publish *payload* on *topic* as a canonical envelope."""
        if not is_worker_topic(topic):
            return
        envelope = EventEnvelope(
            event_id=uuid.uuid4(),
            event_type=topic,
            version="1.0.0",
            timestamp=self._now(),
            source=self._source,
            payload=payload,
        )
        self._sink(envelope)
