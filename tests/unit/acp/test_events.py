"""Tests for ``mahavishnu.acp.events.EventSynthesizer``.

Two complementary layers of coverage:

1. **Mapping-table row-by-row** (``TestSynthesizerMapping``) — every row
   of the mapping table is exercised in isolation. If a future change
   breaks a single row, the failing test name pinpoints the regression.
2. **Invariants** (``TestSynthesizerInvariants``) — the "no silent drops"
   invariant (every envelope with a session_id produces a SessionUpdate),
   the "missing session_id → None" routing invariant, and the disc
   discriminator key correctness.

The plan also specifies a "drop-on-full-queue path" test. That belongs to
the dispatcher (Phase 2), which manages the outbound queue; the synthesizer
is a pure mapper with no queue awareness. We cover it in Phase 2.
"""

from __future__ import annotations

import pytest

from mahavishnu.acp.events import EventSynthesizer
from mahavishnu.acp.protocol import (
    AgentMessageChunk,
    SessionUpdate,
    StatusUpdate,
    ToolCallUpdate,
)

pytestmark = [pytest.mark.unit, pytest.mark.acp]


# ---------------------------------------------------------------------------
# Mapping table row-by-row
# ---------------------------------------------------------------------------

class TestSynthesizerMapping:
    """Each row of the mapping table is exercised in isolation."""

    def setup_method(self) -> None:
        self.synth = EventSynthesizer()

    def test_workflow_started_maps_to_working(self) -> None:
        update = self.synth.synthesize(
            {"type": "workflow.started", "session_id": "s1"}
        )
        assert isinstance(update, StatusUpdate)
        assert update.status == "working"
        assert update.sessionId == "s1"

    def test_workflow_completed_maps_to_completed(self) -> None:
        update = self.synth.synthesize(
            {"type": "workflow.completed", "session_id": "s1"}
        )
        assert isinstance(update, StatusUpdate)
        assert update.status == "completed"
        assert update.sessionId == "s1"

    def test_workflow_failed_maps_to_failed(self) -> None:
        update = self.synth.synthesize(
            {"type": "workflow.failed", "session_id": "s1"}
        )
        assert isinstance(update, StatusUpdate)
        assert update.status == "failed"
        assert update.sessionId == "s1"

    def test_stage_completed_emits_agent_message_chunk(self) -> None:
        update = self.synth.synthesize(
            {
                "type": "stage.completed",
                "session_id": "s1",
                "payload": {"name": "preprocess"},
            }
        )
        assert isinstance(update, AgentMessageChunk)
        assert update.content.text == "stage preprocess complete"

    def test_stage_completed_with_missing_name_uses_unknown(self) -> None:
        update = self.synth.synthesize(
            {"type": "stage.completed", "session_id": "s1", "payload": {}}
        )
        assert isinstance(update, AgentMessageChunk)
        assert update.content.text == "stage unknown complete"

    def test_tool_call_started_maps_to_running(self) -> None:
        """The plan's §Phase 1 Task 4 demo-by assertion: tool_call.started → running."""
        update = self.synth.synthesize(
            {
                "type": "tool_call.started",
                "name": "X",
                "task_id": "t1",
                "session_id": "s1",
            }
        )
        assert isinstance(update, ToolCallUpdate)
        assert update.status == "running"
        assert update.toolCallId == "t1"
        assert update.sessionId == "s1"
        assert update.title == "X"

    def test_tool_call_completed_maps_to_completed(self) -> None:
        update = self.synth.synthesize(
            {
                "type": "tool_call.completed",
                "name": "X",
                "task_id": "t1",
                "session_id": "s1",
                "payload": {"outcome": "completed"},
            }
        )
        assert isinstance(update, ToolCallUpdate)
        assert update.status == "completed"

    def test_tool_call_completed_maps_to_failed(self) -> None:
        update = self.synth.synthesize(
            {
                "type": "tool_call.completed",
                "name": "X",
                "task_id": "t1",
                "session_id": "s1",
                "payload": {"outcome": "failed"},
            }
        )
        assert isinstance(update, ToolCallUpdate)
        assert update.status == "failed"

    def test_tool_call_completed_defaults_to_completed(self) -> None:
        """Plan: failures should be loud about themselves. A missing outcome defaults to completed."""
        update = self.synth.synthesize(
            {
                "type": "tool_call.completed",
                "task_id": "t1",
                "session_id": "s1",
                "payload": {},
            }
        )
        assert isinstance(update, ToolCallUpdate)
        assert update.status == "completed"

    def test_crackerjack_gate_raised_emits_agent_message_chunk(self) -> None:
        update = self.synth.synthesize(
            {
                "type": "crackerjack.gate_raised",
                "session_id": "s1",
                "payload": {"name": "coverage"},
            }
        )
        assert isinstance(update, AgentMessageChunk)
        assert update.content.text == "gate coverage raised"

    def test_unknown_topic_passes_through_as_text(self) -> None:
        """Plan invariant: no silent drops. Unknown topics serialize the envelope as text."""
        envelope = {
            "type": "future.event_type_we_dont_know_about",
            "session_id": "s1",
            "payload": {"value": 42},
        }
        update = self.synth.synthesize(envelope)
        assert isinstance(update, AgentMessageChunk)
        # The serialized envelope should be present in the text payload.
        assert "future.event_type_we_dont_know_about" in update.content.text
        assert '"value": 42' in update.content.text

    def test_session_id_extracted_from_headers(self) -> None:
        update = self.synth.synthesize(
            {
                "type": "workflow.started",
                "headers": {"session_id": "from-headers"},
            }
        )
        assert update is not None
        assert update.sessionId == "from-headers"

    def test_session_id_extracted_from_payload(self) -> None:
        update = self.synth.synthesize(
            {
                "type": "workflow.started",
                "payload": {"session_id": "from-payload"},
            }
        )
        assert update is not None
        assert update.sessionId == "from-payload"

    def test_task_id_falls_back_to_unknown(self) -> None:
        """No task_id in envelope → toolCallId='unknown' (required field)."""
        update = self.synth.synthesize(
            {
                "type": "tool_call.started",
                "session_id": "s1",
            }
        )
        assert isinstance(update, ToolCallUpdate)
        assert update.toolCallId == "unknown"

    def test_task_id_extracted_from_tool_call_id_alias(self) -> None:
        """Accept ``tool_call_id`` as an alias for ``task_id`` (worker contract convention)."""
        update = self.synth.synthesize(
            {
                "type": "tool_call.started",
                "session_id": "s1",
                "payload": {"tool_call_id": "alt-id"},
            }
        )
        assert isinstance(update, ToolCallUpdate)
        assert update.toolCallId == "alt-id"


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

class TestSynthesizerInvariants:
    """Cross-cutting invariants the synthesizer must always satisfy."""

    def setup_method(self) -> None:
        self.synth = EventSynthesizer()

    def test_no_silent_drops_when_session_id_present(self) -> None:
        """Every envelope with a session_id must produce a SessionUpdate, regardless of topic."""
        envelope = {
            "type": "totally.uninvented.event",
            "session_id": "s1",
        }
        update = self.synth.synthesize(envelope)
        assert update is not None, "no silent drops: unknown topic still produces a SessionUpdate"

    def test_returns_none_when_session_id_missing(self) -> None:
        """The one place None is returned: dispatcher drops unroutable envelopes."""
        envelope = {"type": "workflow.started"}
        assert self.synth.synthesize(envelope) is None

    def test_session_id_missing_from_all_three_locations(self) -> None:
        """None when session_id is absent from outer, headers, and payload."""
        envelope = {
            "type": "workflow.started",
            "headers": {"other": "value"},
            "payload": {"name": "x"},
        }
        assert self.synth.synthesize(envelope) is None

    def test_session_id_routing_priority_outer_beats_headers(self) -> None:
        """Outer ``session_id`` wins over ``headers.session_id`` if both present."""
        update = self.synth.synthesize(
            {
                "type": "workflow.started",
                "session_id": "outer",
                "headers": {"session_id": "from-headers"},
            }
        )
        assert update.sessionId == "outer"

    def test_session_id_routing_priority_headers_beats_payload(self) -> None:
        """``headers.session_id`` wins over ``payload.session_id``."""
        update = self.synth.synthesize(
            {
                "type": "workflow.started",
                "headers": {"session_id": "from-headers"},
                "payload": {"session_id": "from-payload"},
            }
        )
        assert update.sessionId == "from-headers"

    def test_session_id_empty_string_treated_as_missing(self) -> None:
        """An empty string session_id is not a valid routing key."""
        assert self.synth.synthesize(
            {"type": "workflow.started", "session_id": ""}
        ) is None

    def test_non_string_session_id_ignored(self) -> None:
        """A non-string session_id (e.g., int) is ignored; falls through to headers/payload."""
        update = self.synth.synthesize(
            {
                "type": "workflow.started",
                "session_id": 12345,  # not a string
                "payload": {"session_id": "real-id"},
            }
        )
        assert update.sessionId == "real-id"

    def test_returned_update_serializes_to_camel_case(self) -> None:
        """Wire format: SessionUpdate model_dump uses sessionId (camelCase), not session_id."""
        update = self.synth.synthesize(
            {"type": "workflow.started", "session_id": "s1"}
        )
        wire = update.model_dump()
        assert "sessionId" in wire
        assert "session_id" not in wire

    def test_session_update_type_adapter_accepts_synthesizer_output(self) -> None:
        """The synthesizer output must be parseable by the SessionUpdate discriminator."""
        from pydantic import TypeAdapter

        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        for envelope_type in (
            "workflow.started",
            "workflow.completed",
            "workflow.failed",
            "stage.completed",
            "tool_call.started",
            "tool_call.completed",
            "crackerjack.gate_raised",
        ):
            envelope = {
                "type": envelope_type,
                "session_id": "s1",
                "task_id": "t1",
                "payload": {"name": "n", "outcome": "completed"},
            }
            update = self.synth.synthesize(envelope)
            assert update is not None, f"no update for {envelope_type}"
            # Round-trip through the discriminator adapter.
            parsed = adapter.validate_python(update.model_dump())
            assert isinstance(parsed, type(update))
