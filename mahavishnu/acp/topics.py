"""Canonical EventBridge topic constants for ACP-related worker emissions.

These topic names follow the existing Oneiric dot-separated convention used
in ``mahavishnu.core.events.worker_topics`` (``worker.spawned``, ``worker.reaped``,
etc.). They are emitted by the worker dispatch boundary when a tool call
starts and completes, and consumed by ``mahavishnu.acp.events.EventSynthesizer``
to produce ACP ``session/update`` notifications of type ``tool_call_update``.

Naming is intentionally distinct from the worker topics — ACP is a consumer
of worker events, not a worker itself. The dot-separated form matches the
canonical Oneiric envelope shape (``event_type`` field on ``EventEnvelope``).

Topic constants live in their own module (``mahavishnu.acp.topics``) rather
than being appended to ``mahavishnu.core.events.worker_topics`` to preserve
the semantic boundary: ``worker_topics`` is for worker lifecycle, ACP topics
are for cross-cutting tool-call observation.
"""

from __future__ import annotations

TOOL_CALL_STARTED: str = "tool_call.started"
TOOL_CALL_COMPLETED: str = "tool_call.completed"

ACP_TOPICS: frozenset[str] = frozenset(
    {
        TOOL_CALL_STARTED,
        TOOL_CALL_COMPLETED,
    }
)


def is_acp_topic(topic: str) -> bool:
    """Return True when *topic* is one of the canonical ACP-related topics."""
    return topic in ACP_TOPICS
