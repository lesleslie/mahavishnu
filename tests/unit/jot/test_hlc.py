from __future__ import annotations

from pathlib import Path
import re
import socket
import time

import pytest

from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.hlc import (
    NodePersistError,
    _generate_node_id,
    get_node,
    hlc_now,
    node_init,
    read_tail_hlc,
)

# ---------------------------------------------------------------------------
# hlc_now (pure)
# ---------------------------------------------------------------------------


def test_hlc_now_first_call_returns_ctr_zero() -> None:
    """First call with no last HLC must have ctr=0."""
    hlc = hlc_now("a3f9b2e1", last=None)
    assert hlc.ctr == 0
    assert hlc.node == "a3f9b2e1"
    assert hlc.wall_ms > 0


def test_hlc_now_increments_ctr_on_same_wall_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    """When wall_ms is unchanged from last, ctr must increment."""
    fixed_time = 1_757_452_800.123
    monkeypatch.setattr(time, "time", lambda: fixed_time)
    last = hlc_now("a3f9b2e1", last=None)
    next_hlc = hlc_now("a3f9b2e1", last=last)
    assert next_hlc.wall_ms == last.wall_ms
    assert next_hlc.ctr == last.ctr + 1


def test_hlc_now_resets_ctr_when_wall_ms_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    """When wall_ms advances past last.wall_ms, ctr must reset to 0."""
    # Capture real time BEFORE patching to avoid recursion in the lambda.
    original_time = time.time
    baseline = original_time()
    last = hlc_now("a3f9b2e1", last=None)
    # Patch to return a time 1 second in the future
    monkeypatch.setattr(time, "time", lambda: baseline + 1.0)
    next_hlc = hlc_now("a3f9b2e1", last=last)
    assert next_hlc.wall_ms > last.wall_ms
    assert next_hlc.ctr == 0


def test_hlc_now_uses_passed_node() -> None:
    """The node field must come from the parameter, not be regenerated."""
    hlc = hlc_now("custom01", last=None)
    assert hlc.node == "custom01"


# ---------------------------------------------------------------------------
# _generate_node_id (B2 fix: hostname padded to 4 chars)
# ---------------------------------------------------------------------------


def test_generate_node_id_always_8_lowercase_hex() -> None:
    """B2 fix: regardless of hostname, output is always exactly 8 hex chars."""
    for hostname in ["ci", "abc", "myhost.example.com", "verylonghostname", "HOST", "MyHost"]:
        with pytest.MonkeyPatch.context() as m:
            m.setattr(socket, "gethostname", lambda h=hostname: h)
            result = _generate_node_id()
        assert re.match(r"^[0-9a-f]{8}$", result), f"hostname {hostname!r} produced {result!r}"


def test_generate_node_id_is_deterministic_per_hostname() -> None:
    """Same hostname produces same ID prefix (sha256 determinism)."""
    with pytest.MonkeyPatch.context() as m:
        m.setattr(socket, "gethostname", lambda: "stable-host")
        first = _generate_node_id()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(socket, "gethostname", lambda: "stable-host")
        second = _generate_node_id()
    # First 4 chars (sha256 prefix) must be identical
    assert first[:4] == second[:4]


def test_generate_node_id_uppercase_lowercased() -> None:
    """Uppercase hostname is lowercased before hashing."""
    with pytest.MonkeyPatch.context() as m:
        m.setattr(socket, "gethostname", lambda: "HOST")
        upper = _generate_node_id()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(socket, "gethostname", lambda: "host")
        lower = _generate_node_id()
    # Same hash → same prefix
    assert upper[:4] == lower[:4]


# ---------------------------------------------------------------------------
# node_init (file I/O)
# ---------------------------------------------------------------------------


def test_node_init_creates_file_with_8_hex_chars(tmp_path: Path) -> None:
    """First call creates the node file with exactly 8 lowercase hex chars."""
    node_file = tmp_path / "node"
    result = node_init(node_file)
    assert node_file.exists()
    assert re.match(r"^[0-9a-f]{8}$", result)


def test_node_init_returns_existing_node_on_second_call(tmp_path: Path) -> None:
    """Subsequent calls must return the same node (no regeneration)."""
    node_file = tmp_path / "node"
    first = node_init(node_file)
    second = node_init(node_file)
    assert first == second


def test_node_init_uses_hostname_hash_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Node ID prefix is sha256(hostname)[:4], not raw hostname chars."""
    monkeypatch.setattr(socket, "gethostname", lambda: "stable-host")
    node_file = tmp_path / "node"
    first = node_init(node_file)
    # Recreate with same hostname — must produce same prefix
    node_file.unlink()
    second = node_init(node_file)
    assert first[:4] == second[:4]
    assert re.match(r"^[0-9a-f]{8}$", first)


def test_node_init_write_failure_raises_node_persist_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When file write fails, raise NodePersistError (B5 fix)."""
    import os
    node_file = tmp_path / "node"

    original_open = os.open

    def fake_open(path, flags, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(node_file) in str(path):
            raise PermissionError(13, "Permission denied", str(path))
        return original_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", fake_open)

    with pytest.raises(NodePersistError):
        node_init(node_file)


# ---------------------------------------------------------------------------
# get_node (B3 fix: lazy module-level cache)
# ---------------------------------------------------------------------------


def test_get_node_returns_cached_value(tmp_path: Path) -> None:
    """get_node must return the same value on repeated calls within one process."""
    node_file = tmp_path / "node"
    first = get_node(node_file)
    second = get_node(node_file)
    assert first == second


def test_get_node_initializes_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_node must call node_init exactly once even when called many times."""
    node_file = tmp_path / "node"
    call_count = 0
    original_init = node_init

    def counting_init(path: Path) -> str:
        nonlocal call_count
        call_count += 1
        return original_init(path)

    # Patch the module-level reference that get_node uses
    from mahavishnu.jot import hlc as hlc_module
    monkeypatch.setattr(hlc_module, "node_init", counting_init)

    for _ in range(5):
        get_node(node_file)
    assert call_count == 1


# ---------------------------------------------------------------------------
# read_tail_hlc (B4 fix: scan all lines, return last valid)
# ---------------------------------------------------------------------------


def test_read_tail_hlc_returns_none_when_log_missing(tmp_path: Path) -> None:
    """No log file → no last HLC (caller treats as fresh start)."""
    assert read_tail_hlc(tmp_path / "nonexistent.jsonl") is None


def test_read_tail_hlc_returns_none_for_empty_log(tmp_path: Path) -> None:
    """Empty log file → no last HLC."""
    log = tmp_path / "log.jsonl"
    log.write_text("")
    assert read_tail_hlc(log) is None


def test_read_tail_hlc_returns_hlc_of_last_event(tmp_path: Path) -> None:
    """Last complete JSON line's HLC must be returned."""
    log = tmp_path / "log.jsonl"
    events = [
        JotEvent(
            id="a" * 32,
            op="capture",
            hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
            text="first",
            ctx={},
            created_ms=1000,
        ),
        JotEvent(
            id="b" * 32,
            op="capture",
            hlc=HLC(wall_ms=2000, ctr=0, node="a3f9b2e1"),
            text="second",
            ctx={},
            created_ms=2000,
        ),
    ]
    log.write_text("".join(serialize(e) for e in events))
    last_hlc = read_tail_hlc(log)
    assert last_hlc == HLC(wall_ms=2000, ctr=0, node="a3f9b2e1")


def test_read_tail_hlc_returns_last_valid_when_final_line_truncated(tmp_path: Path) -> None:
    """B4 fix: when final line is truncated, return the prior valid HLC (not None)."""
    log = tmp_path / "log.jsonl"
    valid_event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=5, node="a3f9b2e1"),
        text="valid",
        ctx={},
        created_ms=1000,
    )
    # Append a truncated (unparseable) line after a valid line
    log.write_text(serialize(valid_event) + '{"id":"b","op":"capture","hlc":{"wall_ms":2000,"ctr":0,"nod')
    # Should return the valid event's HLC, NOT None
    last_hlc = read_tail_hlc(log)
    assert last_hlc == HLC(wall_ms=1000, ctr=5, node="a3f9b2e1")


def test_read_tail_hlc_returns_none_when_only_truncated_line(tmp_path: Path) -> None:
    """If all lines are malformed, return None."""
    log = tmp_path / "log.jsonl"
    log.write_text("malformed garbage that is not json\nmore garbage\n")
    assert read_tail_hlc(log) is None


def test_read_tail_hlc_skips_malformed_lines_in_middle(tmp_path: Path) -> None:
    """Malformed lines between valid events don't break recovery of the last valid HLC."""
    log = tmp_path / "log.jsonl"
    valid1 = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="first",
        ctx={},
        created_ms=1000,
    )
    valid2 = JotEvent(
        id="b" * 32,
        op="capture",
        hlc=HLC(wall_ms=2000, ctr=0, node="a3f9b2e1"),
        text="second",
        ctx={},
        created_ms=2000,
    )
    log.write_text(serialize(valid1) + "garbage\n" + serialize(valid2))
    last_hlc = read_tail_hlc(log)
    assert last_hlc == HLC(wall_ms=2000, ctr=0, node="a3f9b2e1")


def test_read_tail_hlc_reads_only_tail_of_large_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """For large logs (>64KB), only the tail is read."""
    from mahavishnu.jot import hlc as hlc_module

    monkeypatch.setattr(hlc_module, "TAIL_SIZE", 256)
    events = [
        JotEvent(
            id=f"{i:032x}"[-32:],
            op="capture",
            hlc=HLC(wall_ms=1000 + i, ctr=0, node="a3f9b2e1"),
            text=f"event {i}",
            ctx={},
            created_ms=1000 + i,
        )
        for i in range(20)
    ]
    log = tmp_path / "log.jsonl"
    log.write_text("".join(serialize(e) for e in events))
    last_hlc = read_tail_hlc(log)
    assert last_hlc == events[-1].hlc


# ---------------------------------------------------------------------------
# Property test: HLC monotonicity in a single thread
# ---------------------------------------------------------------------------


def test_hlc_now_is_monotonic_in_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sequence of N hlc_now() calls must produce strictly monotonic HLCs."""
    fixed_time = 1_757_452_800.0
    monkeypatch.setattr(time, "time", lambda: fixed_time)
    last = None
    hlcs = []
    for _ in range(100):
        hlc = hlc_now("a3f9b2e1", last=last)
        hlcs.append(hlc)
        last = hlc
    for prev, curr in zip(hlcs, hlcs[1:]):
        assert (curr.wall_ms, curr.ctr) > (prev.wall_ms, prev.ctr)
