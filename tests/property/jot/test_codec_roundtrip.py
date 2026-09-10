from __future__ import annotations

from hypothesis import given, strategies as st

from mahavishnu.jot.events import HLC, JotEvent, deserialize, serialize

uuid_hex = st.text(alphabet="0123456789abcdef", min_size=32, max_size=32)
node_hex = st.text(alphabet="0123456789abcdef", min_size=8, max_size=8)
ctx_strategy = st.dictionaries(
    keys=st.sampled_from(["cwd", "session_id", "env_repo", "env_branch"]),
    values=st.text(max_size=100),
    min_size=0,
    max_size=4,
)
event_strategy = st.builds(
    JotEvent,
    id=uuid_hex,
    op=st.sampled_from(["capture", "edit", "done", "reopen"]),
    hlc=st.builds(
        HLC,
        wall_ms=st.integers(min_value=0, max_value=2**48),
        ctr=st.integers(min_value=0, max_value=2**32),
        node=node_hex,
    ),
    text=st.text(max_size=1000),
    ctx=ctx_strategy,
    created_ms=st.integers(min_value=0, max_value=2**48),
)


@given(event_strategy)
def test_serialize_deserialize_roundtrip(event: JotEvent) -> None:
    """For any valid JotEvent, deserialize(serialize(e)) == e."""
    line = serialize(event)
    result = deserialize(line)
    assert result == event


@given(event_strategy)
def test_serialize_ends_with_newline(event: JotEvent) -> None:
    """Every serialized line must end with \\n for atomic append."""
    line = serialize(event)
    assert line.endswith("\n")


@given(event_strategy)
def test_serialize_produces_valid_json(event: JotEvent) -> None:
    """The serialized output (without newline) must be valid JSON."""
    import json
    line = serialize(event).rstrip("\n")
    parsed = json.loads(line)
    assert parsed["id"] == event.id
    assert parsed["op"] == event.op
