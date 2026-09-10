from __future__ import annotations

import json

import pytest

from mahavishnu.jot.events import (
    HLC,
    CaptureCtx,
    JotEvent,
    deserialize,
    serialize,
)


def test_hlc_is_frozen() -> None:
    """HLC must be immutable to support HLC ordering invariants."""
    hlc = HLC(wall_ms=1000, ctr=0, node="a3f9b2e1")
    with pytest.raises((AttributeError, Exception)):
        hlc.wall_ms = 2000  # type: ignore[misc]


def test_jot_event_is_frozen() -> None:
    """JotEvent must be immutable to support deterministic round-trip."""
    event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="test",
        ctx={"cwd": "/tmp"},
        created_ms=1000,
    )
    with pytest.raises((AttributeError, Exception)):
        event.text = "modified"  # type: ignore[misc]


def test_serialize_returns_compact_json_with_newline() -> None:
    """Wire format: one event per line, no indent, trailing \\n."""
    event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="hello world",
        ctx={"cwd": "/tmp", "session_id": "s1"},
        created_ms=1000,
    )
    line = serialize(event)
    assert line.endswith("\n")
    assert ": " not in line
    assert ", " not in line


def test_serialize_uses_separators_no_whitespace() -> None:
    """JSON separators must be (',', ':') — no spaces."""
    event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="hello",
        ctx={},
        created_ms=1000,
    )
    line = serialize(event)
    parsed = json.loads(line.rstrip("\n"))
    assert parsed["text"] == "hello"


def test_deserialize_strips_trailing_newline() -> None:
    """deserialize must handle both '\\n' and no-newline inputs."""
    event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="hello",
        ctx={"cwd": "/tmp"},
        created_ms=1000,
    )
    line = serialize(event)
    result = deserialize(line)
    assert result == event


def test_deserialize_handles_line_without_newline() -> None:
    """deserialize must also work if the caller has already stripped the newline."""
    event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="hello",
        ctx={},
        created_ms=1000,
    )
    line_without_newline = serialize(event).rstrip("\n")
    result = deserialize(line_without_newline)
    assert result == event


def test_deserialize_raises_on_invalid_json() -> None:
    """Invalid JSON must raise JSONDecodeError (caller's responsibility)."""
    with pytest.raises(json.JSONDecodeError):
        deserialize("not json\n")


def test_serialize_preserves_unicode() -> None:
    """UTF-8 text (emoji, accented chars) must survive round-trip."""
    event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="héllo wörld 🚀",
        ctx={"cwd": "/tmp"},
        created_ms=1000,
    )
    line = serialize(event)
    assert "héllo wörld 🚀" in line
    assert deserialize(line) == event


def test_round_trip_preserves_all_fields() -> None:
    """Every field of JotEvent must survive serialize → deserialize."""
    event = JotEvent(
        id="0123456789abcdef0123456789abcdef",
        op="capture",
        hlc=HLC(wall_ms=1757452800123, ctr=42, node="mac01a3f9"),
        text="complex text with [REDACTED:secret:abc12345]",
        ctx={
            "cwd": "/Users/les/Projects/mahavishnu",
            "session_id": "sess_xyz",
            "files": ["src/x.py", "tests/test_x.py"],
            "env_repo": "/Users/les/Projects/mahavishnu",
            "env_branch": "main",
        },
        created_ms=1757452800123,
    )
    line = serialize(event)
    result = deserialize(line)
    assert result == event


def test_capture_ctx_typed_dict_exists() -> None:
    """CaptureCtx TypedDict is exported for callers who want typed ctx."""
    ctx: CaptureCtx = {"cwd": "/tmp", "session_id": "s1"}
    assert ctx["cwd"] == "/tmp"
