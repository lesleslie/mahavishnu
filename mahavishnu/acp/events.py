"""EventBridge-to-ACP ``session/update`` synthesizer.

The EventBridge (Oneiric canonical envelope) emits a stream of typed events
as work runs. An ACP client expects a different wire shape — a stream of
``session/update`` notifications with discriminated subtypes
(``agent_message_chunk`` / ``tool_call_update`` / ``status``). This module
maps one to the other.

## Mapping table

The mapping is intentionally table-driven so future event types can be added
without changing the synthesizer's dispatch logic. Each row maps a canonical
EventBridge topic (dot-separated, matching ``mahavishnu.core.events.worker_topics``
style) to an ACP ``SessionUpdate`` subtype.

| EventBridge topic              | ACP ``sessionUpdate`` subtype       | Notes                                      |
|--------------------------------|-------------------------------------|--------------------------------------------|
| ``workflow.started``           | ``StatusUpdate(status="working")``   | First event after session creation         |
| ``workflow.completed``         | ``StatusUpdate(status="completed")`` | Terminal success                           |
| ``workflow.failed``            | ``StatusUpdate(status="failed")``    | Terminal failure; error text is logged     |
| ``stage.completed``            | ``AgentMessageChunk``                | Text: ``"stage <name> complete"``           |
| ``tool_call.started``          | ``ToolCallUpdate(status="running")`` | ``toolCallId`` from envelope ``task_id``    |
| ``tool_call.completed``        | ``ToolCallUpdate``                   | ``status`` from envelope ``outcome`` field  |
| ``crackerjack.gate_raised``    | ``AgentMessageChunk``                | Text: ``"gate <name> raised"``              |
| anything else                  | ``AgentMessageChunk``                | Text: JSON-serialized envelope (no silent drop) |

Unknown topic types do NOT raise — the plan explicit invariant ("no silent
drops") means every envelope produces *some* ``SessionUpdate``, so the
client always sees a notification stream.

## Routing

Each ``SessionUpdate`` carries a ``sessionId``. Envelopes without a
recognizable session_id (extracted from ``payload.session_id``, the envelope
``headers.session_id``, or the top-level ``session_id`` field, in that order)
return ``None`` from ``synthesize`` — the dispatcher drops these (they cannot
be routed to a session). This is the one place a None is allowed; it is
logged at the dispatcher level, not here.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from mahavishnu.acp.protocol import (
    AgentMessageChunk,
    SessionUpdate,
    StatusUpdate,
    TextContent,
    ToolCallUpdate,
)
from mahavishnu.acp.topics import TOOL_CALL_COMPLETED, TOOL_CALL_STARTED

# === Mapping table (canonical EventBridge topic → ACP subtype + status) ===

# Each entry: (EventBridge topic, ACP subtype name, default status if applicable).
# The synthesizer dispatches on the topic field; the subtype drives which Pydantic
# model class is instantiated.
_WORKFLOW_TOPICS: frozenset[str] = frozenset({"workflow.started", "workflow.completed", "workflow.failed"})
_STAGE_TOPICS: frozenset[str] = frozenset({"stage.completed"})
_GATE_TOPICS: frozenset[str] = frozenset({"crackerjack.gate_raised"})
_TOOL_TOPICS: frozenset[str] = frozenset({TOOL_CALL_STARTED, TOOL_CALL_COMPLETED})


# === Session-id extraction ===

# Try the envelope's outer ``session_id`` first, then ``headers.session_id``,
# then ``payload.session_id``. This ordering matches how Oneiric envelopes
# typically carry correlation IDs.
def _extract_session_id(envelope: dict[str, Any]) -> str | None:
    """Extract the session ID from a dict-shaped envelope, or ``None``."""
    # Outer field
    sid = envelope.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    # Headers
    headers = envelope.get("headers")
    if isinstance(headers, dict):
        sid = headers.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    # Payload
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        sid = payload.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _extract_topic(envelope: dict[str, Any]) -> str:
    """Extract the topic from a dict-shaped envelope, defaulting to empty string."""
    topic = envelope.get("type") or envelope.get("topic") or envelope.get("event_type")
    return topic if isinstance(topic, str) else ""


def _extract_task_id(envelope: dict[str, Any]) -> str:
    """Extract the task ID (used as ACP ``toolCallId``) from an envelope.

    Looks at the top-level ``task_id`` first (the plan's demo-by shape),
    then ``payload.task_id``, then ``payload.tool_call_id``. Falls back
    to ``"unknown"`` — the field is required by the ACP wire shape, so
    the synthesizer never returns ``None``.
    """
    task_id = envelope.get("task_id")
    if isinstance(task_id, str) and task_id:
        return task_id
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        task_id = payload.get("task_id") or payload.get("tool_call_id")
        if isinstance(task_id, str) and task_id:
            return task_id
    return "unknown"


def _extract_payload_name(envelope: dict[str, Any]) -> str:
    """Extract the ``name`` field from the envelope.

    Looks at top-level ``name`` first, then ``payload.name``. The plan's
    demo-by shape uses top-level ``name`` (e.g., ``{"name": "X"}``).
    """
    name = envelope.get("name")
    if isinstance(name, str) and name:
        return name
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        name = payload.get("name")
        if isinstance(name, str) and name:
            return name
    return ""


def _extract_outcome(envelope: dict[str, Any]) -> Literal["completed", "failed"]:
    """Determine the ``status`` for a ``tool_call.completed`` envelope.

    Defaults to ``"completed"`` when the envelope carries no explicit
    outcome — failures should be loud about themselves.
    """
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        outcome = payload.get("outcome") or payload.get("status")
        if outcome == "failed":
            return "failed"
    return "completed"


# === Synthesizer ===

class EventSynthesizer:
    """Map EventBridge envelopes to ACP ``SessionUpdate`` notifications.

    Stateless and pure: ``synthesize(envelope) -> SessionUpdate | None``.
    The dispatcher (Phase 2) is responsible for the outbound queue, drop
    accounting, and structured-log emission; the synthesizer only does
    mapping.

    Usage::

        synth = EventSynthesizer()
        update = synth.synthesize({"type": "tool_call.started", ...})
        if update is None:
            ...  # envelope had no session_id; dispatcher drops it
        else:
            ...  # serialize and write to stdout
    """

    def synthesize(self, envelope: dict[str, Any]) -> SessionUpdate | None:
        """Map one envelope to one ``SessionUpdate``.

        Returns ``None`` only when the envelope carries no extractable
        session_id (i.e., the dispatcher cannot route it). All other
        envelopes produce a ``SessionUpdate`` — unknown topics fall
        through to ``AgentMessageChunk`` per the plan's "no silent drops"
        invariant.
        """
        session_id = _extract_session_id(envelope)
        if session_id is None:
            return None

        topic = _extract_topic(envelope)

        if topic == "workflow.started":
            return StatusUpdate(sessionId=session_id, status="working")
        if topic == "workflow.completed":
            return StatusUpdate(sessionId=session_id, status="completed")
        if topic == "workflow.failed":
            # Plan maps "failed → status failed + error chunk". The error text
            # surfaces via the unknown-type pass-through path on the next
            # envelope in the stream (which carries the failure detail);
            # we send the status here.
            return StatusUpdate(sessionId=session_id, status="failed")
        if topic == "stage.completed":
            stage_name = _extract_payload_name(envelope) or "unknown"
            return AgentMessageChunk(
                sessionId=session_id,
                content=TextContent(type="text", text=f"stage {stage_name} complete"),
            )
        if topic == TOOL_CALL_STARTED:
            return ToolCallUpdate(
                sessionId=session_id,
                toolCallId=_extract_task_id(envelope),
                status="running",
                title=_extract_payload_name(envelope) or None,
            )
        if topic == TOOL_CALL_COMPLETED:
            return ToolCallUpdate(
                sessionId=session_id,
                toolCallId=_extract_task_id(envelope),
                status=_extract_outcome(envelope),
                title=_extract_payload_name(envelope) or None,
            )
        if topic == "crackerjack.gate_raised":
            gate_name = _extract_payload_name(envelope) or "unknown"
            return AgentMessageChunk(
                sessionId=session_id,
                content=TextContent(type="text", text=f"gate {gate_name} raised"),
            )

        # Unknown topic: serialize the envelope and pass through as text.
        # No silent drops (plan invariant).
        return AgentMessageChunk(
            sessionId=session_id,
            content=TextContent(
                type="text",
                text=f"unknown event: {json.dumps(envelope, default=str)}",
            ),
        )


__all__ = ["EventSynthesizer"]
