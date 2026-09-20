"""Property-based tests for the ACP wire-format models and synthesizer.

Per plan §Phase 1 Task 7. Two complementary property families:

1. **Pydantic round-trip** — for every ``SessionUpdate`` we generate, dumping
   to JSON and re-parsing must produce an equal model. This guards against
   the family of bugs where a default factory, validator, or discriminator
   resolution fails to round-trip cleanly.
2. **Synthesizer no-crash + no-silent-drop** — for every envelope shape we
   generate (including adversarial ones), ``EventSynthesizer.synthesize``
   must not raise; when the envelope has a session_id, the return value
   must not be ``None``.

We use ``hypothesis`` because the input space is large (random topic strings,
random payload shapes, nested optional fields, discriminated unions) and
per-example tests don't cover the corners.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from mahavishnu.acp.events import EventSynthesizer
from mahavishnu.acp.protocol import (
    AgentMessageChunk,
    SESSION_ID_MAX,
    SessionUpdate,
    StatusUpdate,
    TextContent,
    ToolCallUpdate,
)
from pydantic import TypeAdapter

# === Strategies for SessionUpdate variants ===

# Bound text length to avoid Hypothesis generating gigabytes of text.
_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        max_codepoint=0x7E,
    ),
    max_size=100,
)

_session_id_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-_",
        max_codepoint=0x7E,
    ),
    min_size=1,
    max_size=SESSION_ID_MAX,
)

_task_id_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        max_codepoint=0x7E,
    ),
    min_size=1,
    max_size=32,
)

_status_st = st.sampled_from(["working", "completed", "failed"])
_tool_status_st = st.sampled_from(["running", "completed", "failed"])

agent_message_chunk_st = st.builds(
    AgentMessageChunk,
    sessionId=_session_id_st,
    content=st.builds(TextContent, type=st.just("text"), text=_text_st),
)

tool_call_update_st = st.builds(
    ToolCallUpdate,
    sessionId=_session_id_st,
    toolCallId=_task_id_st,
    status=_tool_status_st,
    title=st.one_of(st.none(), _text_st),
    content=st.one_of(st.none(), st.lists(st.builds(TextContent, type=st.just("text"), text=_text_st), max_size=3)),
)

status_update_st = st.builds(
    StatusUpdate,
    sessionId=_session_id_st,
    status=_status_st,
)

session_update_st = st.one_of(
    agent_message_chunk_st, tool_call_update_st, status_update_st
)

# === Strategies for envelope dicts (synthesizer input) ===

_topic_st = st.sampled_from(
    [
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
        "stage.completed",
        "tool_call.started",
        "tool_call.completed",
        "crackerjack.gate_raised",
        # Adversarial / unknown topics — must not crash the synthesizer.
        "totally.unknown.event",
        "",
        "x" * 50,
    ]
)

_envelope_st = st.fixed_dictionaries(
    {
        "type": _topic_st,
        "session_id": st.one_of(_session_id_st, st.just("")),
        "name": st.one_of(_text_st, st.just("")),
        "task_id": st.one_of(_task_id_st, st.just("")),
        "payload": st.fixed_dictionaries(
            {
                "name": st.one_of(_text_st, st.just("")),
                "task_id": st.one_of(_task_id_st, st.just("")),
                "outcome": st.sampled_from(["completed", "failed", "unknown"]),
            }
        ),
    }
)


# ---------------------------------------------------------------------------
# Pydantic round-trip
# ---------------------------------------------------------------------------

class TestSessionUpdateRoundTrip:
    """Dump a generated SessionUpdate to JSON, re-parse, assert equality."""

    @given(update=session_update_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_session_update_json_round_trip_preserves_equality(
        self, update: SessionUpdate
    ) -> None:
        """``model.model_dump_json()`` → ``model_validate_json(...)`` → equal model."""
        wire = update.model_dump_json()
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        parsed = adapter.validate_json(wire)
        assert parsed == update

    @given(update=session_update_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_session_update_model_dump_round_trip(self, update: SessionUpdate) -> None:
        """``model.model_dump()`` → ``model_validate(...)`` → equal model."""
        wire = update.model_dump()
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        parsed = adapter.validate_python(wire)
        assert parsed == update

    @given(update=session_update_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_session_update_discriminator_resolves_back_to_original_type(
        self, update: SessionUpdate
    ) -> None:
        """After round-trip, the discriminator adapter re-resolves the same variant."""
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        wire = update.model_dump()
        parsed = adapter.validate_python(wire)
        assert type(parsed) is type(update)


# ---------------------------------------------------------------------------
# Synthesizer: no-crash + no-silent-drop
# ---------------------------------------------------------------------------

class TestSynthesizerProperties:
    """The synthesizer must never crash on adversarial envelopes, and must not
    silently drop envelopes that have a recognizable session_id."""

    @given(envelope=_envelope_st)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_synthesizer_does_not_raise_on_any_envelope(
        self, envelope: dict[str, Any]
    ) -> None:
        """The synthesizer must accept any dict-shaped envelope without raising."""
        synth = EventSynthesizer()
        # The function may return None (no session_id) or a SessionUpdate.
        # It must not raise.
        result = synth.synthesize(envelope)
        # If we got a result, it must be a SessionUpdate variant.
        if result is not None:
            adapter: TypeAdapter = TypeAdapter(SessionUpdate)
            # Round-trip through the discriminator to confirm validity.
            adapter.validate_python(result.model_dump())

    @given(envelope=_envelope_st)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_synthesizer_no_silent_drops_when_session_id_present(
        self, envelope: dict[str, Any]
    ) -> None:
        """If the envelope carries a session_id, synthesize must return a SessionUpdate."""
        # Skip envelopes without a session_id (those legitimately return None).
        assume(envelope.get("session_id"))
        synth = EventSynthesizer()
        result = synth.synthesize(envelope)
        assert result is not None, (
            f"silent drop on envelope with session_id={envelope['session_id']!r}: "
            f"topic={envelope.get('type')!r}"
        )
        assert result.sessionId == envelope["session_id"]

    @given(
        topic=st.sampled_from(
            [
                "workflow.started",
                "workflow.completed",
                "workflow.failed",
                "stage.completed",
                "tool_call.started",
                "tool_call.completed",
                "crackerjack.gate_raised",
            ]
        ),
        session_id=_session_id_st,
        task_id=_task_id_st,
        name=_text_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_synthesizer_topic_mapping_canonical_inputs(
        self,
        topic: str,
        session_id: str,
        task_id: str,
        name: str,
    ) -> None:
        """Canonical topic strings map to the right SessionUpdate subtype."""
        synth = EventSynthesizer()
        envelope: dict[str, Any] = {
            "type": topic,
            "session_id": session_id,
            "task_id": task_id,
            "name": name,
            "payload": {"name": name, "task_id": task_id, "outcome": "completed"},
        }
        result = synth.synthesize(envelope)
        assert result is not None
        assert result.sessionId == session_id
        # Verify the discriminator is the correct subtype for the topic.
        if topic == "workflow.started":
            assert isinstance(result, StatusUpdate)
            assert result.status == "working"
        elif topic == "workflow.completed":
            assert isinstance(result, StatusUpdate)
            assert result.status == "completed"
        elif topic == "workflow.failed":
            assert isinstance(result, StatusUpdate)
            assert result.status == "failed"
        elif topic == "stage.completed":
            assert isinstance(result, AgentMessageChunk)
            assert result.content.text.startswith("stage ")
        elif topic in ("tool_call.started", "tool_call.completed"):
            assert isinstance(result, ToolCallUpdate)
            assert result.toolCallId == task_id

    @given(payload_value=st.one_of(st.text(max_size=200), st.integers(), st.floats(allow_nan=False), st.booleans(), st.none()))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_unknown_topic_serializes_arbitrary_payload_to_text(
        self, payload_value: Any
    ) -> None:
        """Adversarial payloads under an unknown topic must produce a valid AgentMessageChunk."""
        synth = EventSynthesizer()
        envelope = {
            "type": "completely.invented.topic",
            "session_id": "s1",
            "payload": {"value": payload_value},
        }
        result = synth.synthesize(envelope)
        assert isinstance(result, AgentMessageChunk)
        # The text must round-trip through JSON.parse without raising.
        parsed_back = json.loads(result.content.text.split("unknown event: ", 1)[1])
        assert parsed_back == envelope


# ---------------------------------------------------------------------------
# Pydantic invariants on adversarial input
# ---------------------------------------------------------------------------

class TestSessionUpdateInvariants:
    """Pydantic-level properties the wire format must satisfy on random input."""

    @given(update=session_update_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_session_id_present_in_every_dump(self, update: SessionUpdate) -> None:
        """``sessionId`` is mandatory on every SessionUpdate variant — the dump
        must contain it (the discriminated-union strategy enforces this)."""
        wire = update.model_dump()
        assert "sessionId" in wire
        assert isinstance(wire["sessionId"], str)
        assert wire["sessionId"], "sessionId must be non-empty"

    @given(update=session_update_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_discriminator_field_is_session_update(self, update: SessionUpdate) -> None:
        """The wire format uses ``sessionUpdate`` as the discriminator, NOT ``type``."""
        wire = update.model_dump()
        assert "sessionUpdate" in wire
        assert wire["sessionUpdate"] in {
            "agent_message_chunk",
            "tool_call_update",
            "status",
        }
