from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.core.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from collections.abc import Callable


class CanonicalEnvelopePublisher:
    """Wraps a sink as the contract's EventPublisher.

    Produces canonical Mahavishnu ``EventEnvelope`` instances so the
    existing EventBridge pipeline consumes them unchanged.
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

    def emit(self, topic: str, payload: dict[str, Any]) -> None:
        envelope = EventEnvelope(
            event_id=uuid.uuid4(),
            event_type=topic,
            version="1.0.0",
            timestamp=self._now(),
            source=self._source,
            payload=payload,
        )
        self._sink(envelope)
