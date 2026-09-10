# Jot Inbox: Capture Sub-Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `,,`-prefixed prompt becomes a local jot. Captures cannot fail.

**Architecture:** A UserPromptSubmit hook (stdlib-only Python) detects the `,,` prefix, writes a JSONL event to `~/.mahavishnu/jot/log.jsonl`, and exits 2 to erase the prompt from Claude's transcript. Mahavishnu owns the install (`mahavishnu jot install-hook` in sub-plan 2).

**Tech Stack:** Python 3.14+ stdlib (json, os, sys, uuid, time, socket, secrets, re, hashlib, traceback, dataclasses, pathlib). No `logging`, no `oneiric`, no `httpx`, no `requests` in the hook script. pytest 8.x + Hypothesis 6.x for tests.

**Spec:** [`docs/superpowers/specs/2026-09-09-jot-capture-design.md`](../specs/2026-09-09-jot-capture-design.md) (commit `14cb30d2`).

---

## Global Constraints

The following constraints apply to **every task** unless explicitly overridden in that task's "Notes" section.

1. **Every source file** starts with `from __future__ import annotations` as the first non-comment line (after any module docstring).
2. **No `assert` in production code** (`mahavishnu/jot/**`, `mahavishnu/hooks/**`) — bandit B101 enforced. Tests may use `assert`.
3. **Stdlib only** in `mahavishnu/hooks/jot_capture.py`. The hook may import from `mahavishnu.jot.*` but those modules must themselves be stdlib-only.
4. **No `logging` module** anywhere in `mahavishnu/jot/**` or `mahavishnu/hooks/**` — uses `print(..., file=sys.stderr)` and writes to `errors.log` directly.
5. **Mypy strict** — `disallow_untyped_defs`, `no_implicit_optional`, `warn_unused_ignores`, `warn_return_any`, `strict_optional`.
6. **Ruff** — line-length 100, function args ≤ 10 (excludes `self`, `cls`, `*args`, `**kwargs`).
7. **File permissions** — log file `0o600`, jot dir `0o700`, errors log `0o600`, node file `0o600`.
8. **Single-syscall writes** — `os.write(fd, line.encode("utf-8"))` exactly once per event.
9. **Coverage target** — ≥ 95% line coverage for `mahavishnu/jot/*` + `mahavishnu/hooks/jot_capture.py`.
10. **Today's date** — 2026-09-10 (use this in commit messages when the date matters).
11. **Commit author** — always `git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit`. Never `git push` without explicit user approval.

---

## File Structure

```
mahavishnu/
├── hooks/
│   └── jot_capture.py                 # Hook entrypoint (Task 8)
└── jot/
    ├── __init__.py                    # Package marker (Task 1)
    ├── events.py                      # JotEvent, HLC, serialize, deserialize (Task 2)
    ├── hlc.py                         # hlc_now, node_init, read_tail_hlc (Task 3)
    ├── short_id.py                    # short_id (Task 4)
    ├── paths.py                       # jot_dir, log_path, errors_log_path, ensure_jot_dir (Task 5)
    ├── redact.py                      # ~20 patterns + redact_text (Task 6)
    └── capture_echo.py                # format_echo (Task 7)

tests/
├── unit/jot/
│   ├── __init__.py
│   ├── test_events.py                 # (Task 2)
│   ├── test_hlc.py                    # (Task 3) — includes property test
│   ├── test_short_id.py               # (Task 4) — includes property test
│   ├── test_redact.py                 # (Task 6)
│   ├── test_paths.py                  # (Task 5)
│   ├── test_capture_echo.py           # (Task 7)
│   └── test_capture_hook.py           # (Task 8)
├── integration/jot/
│   ├── __init__.py
│   └── test_capture_e2e.py            # (Task 9)
└── property/jot/
    ├── __init__.py
    ├── test_codec_roundtrip.py        # (Task 2)
    ├── test_short_id_collision.py     # (Task 4) — optional, can fold into test_short_id.py
    └── (test_hlc_ordering is in tests/unit/jot/test_hlc.py)
```

**Layer boundaries:**
- Tasks 1-7: pure data + I/O primitives, no Claude Code coupling
- Task 8: orchestrator that wires primitives into the UserPromptSubmit hook
- Task 9: integration test that spawns Task 8's hook as a real subprocess

---

## Task Sequencing

| Task | Files | Lines (est.) | Depends on |
|---|---|---|---|
| 1 | `mahavishnu/jot/__init__.py` | 3 | — |
| 2 | `mahavishnu/jot/events.py`, `tests/unit/jot/test_events.py`, `tests/property/jot/test_codec_roundtrip.py`, `tests/property/jot/__init__.py`, `tests/unit/jot/__init__.py` | 200 | 1 |
| 3 | `mahavishnu/jot/hlc.py`, `tests/unit/jot/test_hlc.py` | 200 | 1, 2 |
| 4 | `mahavishnu/jot/short_id.py`, `tests/unit/jot/test_short_id.py` | 80 | 1 |
| 5 | `mahavishnu/jot/paths.py`, `tests/unit/jot/test_paths.py` | 150 | 1 |
| 6 | `mahavishnu/jot/redact.py`, `tests/unit/jot/test_redact.py` | 350 | 1 |
| 7 | `mahavishnu/jot/capture_echo.py`, `tests/unit/jot/test_capture_echo.py` | 60 | 4 |
| 8 | `mahavishnu/hooks/jot_capture.py`, `tests/unit/jot/test_capture_hook.py` | 450 | 2, 3, 4, 5, 6, 7 |
| 9 | `tests/integration/jot/test_capture_e2e.py`, `tests/integration/jot/__init__.py` | 200 | 8 |

**Total:** ~1,700 lines. Tasks 1-7 are independently shippable. Task 8 wires everything. Task 9 proves it works end-to-end.

---

## Task 1: Package Marker

**Files:**
- Create: `mahavishnu/jot/__init__.py`

**Why this task first:** All other tasks import from `mahavishnu.jot.*`. The package must exist before any submodule can be imported.

**Interfaces:**
- Consumes: nothing
- Produces: empty `mahavishnu.jot` package

- [ ] **Step 1: Create the package directory**

```bash
mkdir -p /Users/les/Projects/mahavishnu/mahavishnu/jot
```

- [ ] **Step 2: Write `__init__.py`**

```python
"""Jot inbox package — sub-plan 1 (capture layer).

Sub-plan 2 adds fold.py, render.py. Sub-plan 3 adds drain_*.py.
"""
```

The file is intentionally empty beyond the docstring. No `from __future__ import annotations` — empty package markers don't need it.

- [ ] **Step 3: Verify the package imports**

```bash
cd /Users/les/Projects/mahavishnu && uv run python -c "import mahavishnu.jot; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/__init__.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add jot inbox package marker"
```

---

## Task 2: events.py — JotEvent + HLC + codec

**Files:**
- Create: `mahavishnu/jot/events.py`
- Create: `tests/unit/jot/__init__.py` (empty)
- Create: `tests/property/jot/__init__.py` (empty)
- Create: `tests/unit/jot/test_events.py`
- Create: `tests/property/jot/test_codec_roundtrip.py`

**Interfaces:**
- Consumes: nothing (pure data module)
- Produces:
  - `Op = Literal["capture", "edit", "done", "reopen"]`
  - `@dataclass(frozen=True) class HLC: wall_ms: int; ctr: int; node: str`
  - `@dataclass(frozen=True) class JotEvent: id: str; op: Op; hlc: HLC; text: str; ctx: dict[str, Any]; created_ms: int`
  - `def serialize(event: JotEvent) -> str` — returns compact JSON + `"\n"`
  - `def deserialize(line: str) -> JotEvent` — strips trailing newline, parses JSON

**Why this task second:** HLC is a sub-component of `JotEvent`. Other modules (`hlc.py`, `redact.py`) consume the dataclass type. Codec must exist before the hook can write anything.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/__init__.py`:

```python
"""Unit tests for jot inbox capture layer."""
```

Create `tests/property/jot/__init__.py`:

```python
"""Property tests for jot inbox capture layer."""
```

Create `tests/unit/jot/test_events.py`:

```python
from __future__ import annotations

import json

import pytest

from mahavishnu.jot.events import (
    HLC,
    JotEvent,
    Op,
    deserialize,
    serialize,
)


def test_op_literal_includes_all_variants() -> None:
    """Op enum reserves capture/edit/done/reopen even though v1 only writes capture."""
    expected = {"capture", "edit", "done", "reopen"}
    # Literal type is enforced at type-check time; runtime check via the codec
    event = JotEvent(
        id="a" * 32,
        op="capture",  # type: ignore[arg-type]
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="test",
        ctx={"cwd": "/tmp"},
        created_ms=1000,
    )
    assert event.op == "capture"


def test_hlc_is_frozen() -> None:
    """HLC must be immutable to support HLC ordering invariants."""
    hlc = HLC(wall_ms=1000, ctr=0, node="a3f9b2e1")
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError is AttributeError subclass
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
    # Compact: no whitespace between separators
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
    # Parse it back to verify it's valid JSON
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
    line = serialize(event)  # has \n
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
    """Invalid JSON must raise JSONDecodeError (caller's responsibility to handle)."""
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
```

Create `tests/property/jot/test_codec_roundtrip.py`:

```python
from __future__ import annotations

from hypothesis import given, strategies as st

from mahavishnu.jot.events import HLC, JotEvent, deserialize, serialize

# Strategy for valid UUID v4 hex (32 lowercase hex chars)
uuid_hex = st.text(
    alphabet="0123456789abcdef",
    min_size=32,
    max_size=32,
)

# Strategy for node (8 hex chars)
node_hex = st.text(
    alphabet="0123456789abcdef",
    min_size=8,
    max_size=8,
)

# Strategy for ctx (small dict with string keys, mixed values)
ctx_strategy = st.dictionaries(
    keys=st.sampled_from(["cwd", "session_id", "env_repo", "env_branch"]),
    values=st.text(max_size=100),
    min_size=0,
    max_size=4,
)

# Strategy for full JotEvent
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
    line = serialize(event).rstrip("\n")
    import json
    parsed = json.loads(line)
    assert parsed["id"] == event.id
    assert parsed["op"] == event.op
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_events.py tests/property/jot/test_codec_roundtrip.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'mahavishnu.jot.events'` or `ImportError: cannot import name 'HLC' from 'mahavishnu.jot.events'`.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/jot/events.py`:

```python
"""Jot event data model and JSONL codec.

Wire format: one event per line, compact JSON, trailing \\n.
See spec §"Data Model" for field semantics.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

# v1 only writes "capture"; other ops are reserved for sub-plan 2 (fold/edit/done/reopen).
Op = Literal["capture", "edit", "done", "reopen"]


@dataclass(frozen=True)
class HLC:
    """Hybrid Logical Clock for monotonic ordering of events within and across nodes.

    Monotonic per-node via (wall_ms, ctr) tuple ordering; node field breaks ties
    across nodes when comparing HLCs from different sources.
    """

    wall_ms: int
    ctr: int
    node: str


@dataclass(frozen=True)
class JotEvent:
    """A single jot inbox event. See spec §"Wire format"."""

    id: str
    op: Op
    hlc: HLC
    text: str
    ctx: dict[str, Any]
    created_ms: int


def serialize(event: JotEvent) -> str:
    """Serialize a JotEvent to a single JSONL line (compact, trailing newline).

    Returns a string ending in '\\n'. The caller is responsible for writing
    it to the log file in a single os.write() call (see spec §"Atomicity").
    """
    payload = asdict(event)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"


def deserialize(line: str) -> JotEvent:
    """Deserialize a JSONL line back to a JotEvent.

    Accepts input with or without a trailing newline. Raises json.JSONDecodeError
    on invalid input — the caller is responsible for error handling.
    """
    stripped = line.rstrip("\n")
    payload = json.loads(stripped)
    hlc_dict = payload["hlc"]
    hlc = HLC(wall_ms=hlc_dict["wall_ms"], ctr=hlc_dict["ctr"], node=hlc_dict["node"])
    return JotEvent(
        id=payload["id"],
        op=payload["op"],
        hlc=hlc,
        text=payload["text"],
        ctx=payload["ctx"],
        created_ms=payload["created_ms"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_events.py tests/property/jot/test_codec_roundtrip.py -v
```

Expected: All tests PASS (10 unit + 3 property tests).

- [ ] **Step 5: Run bandit and ruff**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/jot/events.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/events.py tests/unit/jot/test_events.py tests/property/jot/test_codec_roundtrip.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/events.py
```

Expected: All clean (no B101 in `events.py`; ruff clean; mypy clean).

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/events.py tests/unit/jot/ tests/property/jot/
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add JotEvent, HLC dataclasses and JSONL codec"
```

---

## Task 3: hlc.py — HLC generation + node init + tail read

**Files:**
- Create: `mahavishnu/jot/hlc.py`
- Create: `tests/unit/jot/test_hlc.py`

**Interfaces:**
- Consumes: `HLC` from `mahavishnu.jot.events`
- Produces:
  - `def hlc_now(node: str, last: HLC | None) -> HLC` — pure function
  - `def node_init(path: Path) -> str` — reads or creates the node file (8 hex chars)
  - `def read_tail_hlc(log_path: Path) -> HLC | None` — reads last 64 KB of log, extracts last HLC

**Why this task third:** HLC is a pure function (testable without I/O). node_init and read_tail_hlc do file I/O. All three are needed before the hook can write events.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/test_hlc.py`:

```python
from __future__ import annotations

import re
import socket
import time
from pathlib import Path

import pytest

from mahavishnu.jot.events import HLC, deserialize, serialize
from mahavishnu.jot.hlc import hlc_now, node_init, read_tail_hlc


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
    # Freeze time to ensure both calls land in the same wall_ms
    fixed_time = 1_757_452_800.123
    monkeypatch.setattr(time, "time", lambda: fixed_time)
    last = hlc_now("a3f9b2e1", last=None)
    # Reset monkeypatch for next call — both still in same wall_ms
    next_hlc = hlc_now("a3f9b2e1", last=last)
    assert next_hlc.wall_ms == last.wall_ms
    assert next_hlc.ctr == last.ctr + 1


def test_hlc_now_resets_ctr_when_wall_ms_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    """When wall_ms advances past last.wall_ms, ctr must reset to 0."""
    last = hlc_now("a3f9b2e1", last=None)
    # Advance time by 1 second
    monkeypatch.setattr(time, "time", lambda: time.time() + 1.0)
    next_hlc = hlc_now("a3f9b2e1", last=last)
    assert next_hlc.wall_ms > last.wall_ms
    assert next_hlc.ctr == 0


def test_hlc_now_uses_passed_node() -> None:
    """The node field must come from the parameter, not be regenerated."""
    hlc = hlc_now("custom01", last=None)
    assert hlc.node == "custom01"


# ---------------------------------------------------------------------------
# node_init (I/O)
# ---------------------------------------------------------------------------


def test_node_init_creates_file_with_8_hex_chars(tmp_path: Path) -> None:
    """First call creates the node file with 8 lowercase hex chars."""
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


def test_node_init_uses_hostname_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Node ID should be hostname[:4] + 4 random hex chars."""
    monkeypatch.setattr(socket, "gethostname", lambda: "myhost.example.com")
    node_file = tmp_path / "node"
    result = node_init(node_file)
    assert result.startswith("myho")  # first 4 chars of "myhost"
    assert len(result) == 8


def test_node_init_truncates_long_hostname(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hostname longer than 4 chars must be truncated."""
    monkeypatch.setattr(socket, "gethostname", lambda: "verylonghostname")
    node_file = tmp_path / "node"
    result = node_init(node_file)
    assert result.startswith("very")  # first 4 chars
    assert len(result) == 8


def test_node_init_short_hostname_padding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hostname shorter than 4 chars must be padded somehow (use raw)."""
    monkeypatch.setattr(socket, "gethostname", lambda: "abc")
    node_file = tmp_path / "node"
    result = node_init(node_file)
    # Implementation choice: just use whatever the hostname returns, pad to 4 with 'x' or similar
    # Verify the result is valid 8 hex chars regardless of padding strategy
    assert re.match(r"^[0-9a-f]{8}$", result)


# ---------------------------------------------------------------------------
# read_tail_hlc (I/O)
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


def test_read_tail_hlc_skips_malformed_last_line(tmp_path: Path) -> None:
    """If the last line is not valid JSON, return None (treat as no HLC)."""
    log = tmp_path / "log.jsonl"
    valid_event = JotEvent(
        id="a" * 32,
        op="capture",
        hlc=HLC(wall_ms=1000, ctr=0, node="a3f9b2e1"),
        text="valid",
        ctx={},
        created_ms=1000,
    )
    log.write_text(serialize(valid_event) + "malformed garbage that is not json\n")
    assert read_tail_hlc(log) is None


def test_read_tail_hlc_reads_only_tail_of_large_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """For large logs (>64KB), only the tail is read (last 64KB)."""
    log = tmp_path / "log.jsonl"
    # Write 100 small events to make a small log, then verify the tail-read works.
    # We can't easily generate >64KB of small events without being slow, so we
    # patch TAIL_SIZE for this test.
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
    log.write_text("".join(serialize(e) for e in events))
    last_hlc = read_tail_hlc(log)
    # The last event's HLC must be returned
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
    # Each subsequent HLC must be > previous (via tuple comparison: wall_ms first, then ctr)
    for prev, curr in zip(hlcs, hlcs[1:]):
        assert (curr.wall_ms, curr.ctr) > (prev.wall_ms, prev.ctr)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_hlc.py -v
```

Expected: All tests FAIL with `ModuleNotFoundError: No module named 'mahavishnu.jot.hlc'`.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/jot/hlc.py`:

```python
"""Hybrid Logical Clock generation, node init, tail-HLC read.

See spec §"HLC generation" and §"HLC continuity across captures".
"""
from __future__ import annotations

import os
import secrets
import socket
import time
from dataclasses import asdict
from pathlib import Path

from .events import HLC, JotEvent, deserialize

# Size of the tail read when looking for the last HLC. See spec §"HLC continuity".
TAIL_SIZE = 65536


def hlc_now(node: str, last: HLC | None) -> HLC:
    """Generate the next HLC for a given node, monotonically advancing from `last`.

    If `last` is None, or current wall_ms has advanced past last.wall_ms, ctr resets to 0.
    Otherwise, ctr increments by 1 from last.ctr.

    Pure function: no I/O. Safe to call from the hook on every capture.
    """
    wall_ms = int(time.time() * 1000)
    if last is None or wall_ms > last.wall_ms:
        ctr = 0
    else:
        ctr = last.ctr + 1
    return HLC(wall_ms=wall_ms, ctr=ctr, node=node)


def _generate_node_id() -> str:
    """Generate a new 8-hex-char node identifier.

    Format: first 4 chars of hostname (truncated) + 4 hex chars from secrets.
    If hostname is shorter than 4 chars, use the raw hostname + pad.
    """
    hostname = socket.gethostname()
    host_part = hostname[:4].lower()
    random_part = secrets.token_hex(2)  # 4 hex chars
    return f"{host_part}{random_part}"


def node_init(path: Path) -> str:
    """Read or create the node identifier file.

    If the file exists, return its contents (8 hex chars).
    If it doesn't exist, generate a new node ID, write it, and return it.

    On write failure (permissions, disk full), returns the generated ID without
    persisting — the caller is responsible for logging via errors.log if needed.
    """
    if path.exists():
        contents = path.read_text().strip()
        if re.match := __import__("re").match(r"^[0-9a-f]{8}$", contents):
            return contents
    # Generate new ID
    new_id = _generate_node_id()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, (new_id + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        # Caller is responsible for logging. Return ID without persistence.
        pass
    return new_id


def read_tail_hlc(log_path: Path) -> HLC | None:
    """Read the last HLC from the log file (last 64KB tail).

    Returns None if:
    - The log file doesn't exist
    - The log file is empty
    - The last line is not valid JSON
    - The last valid JSON line has no parseable HLC

    See spec §"HLC continuity across captures".
    """
    try:
        file_size = log_path.stat().st_size
    except (FileNotFoundError, OSError):
        return None

    if file_size == 0:
        return None

    try:
        fd = os.open(str(log_path), os.O_RDONLY)
    except (FileNotFoundError, OSError):
        return None

    try:
        # Seek to last TAIL_SIZE bytes (or beginning if file is smaller)
        seek_to = max(0, file_size - TAIL_SIZE)
        os.lseek(fd, seek_to, os.SEEK_SET)
        data = os.read(fd, file_size - seek_to)
    except OSError:
        return None
    finally:
        os.close(fd)

    # Split on newlines, take the last non-empty line
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    # Find the last non-empty line
    last_line = None
    for line in reversed(lines):
        if line.strip():
            last_line = line
            break

    if last_line is None:
        return None

    # Try to parse as a JotEvent
    try:
        event = deserialize(last_line)
    except (ValueError, KeyError, TypeError):
        return None

    return event.hlc
```

**Note on the `__import__("re")` hack:** this avoids an unused-import lint warning when `re` is only used inside the conditional. A cleaner refactor is to put `import re` at the top of the file — but for now this works and tests will reveal if lints complain. If ruff complains, replace with `import re` at top and use `re.match(...)` directly.

Wait, let me clean this up — the inline `__import__` is ugly. Let me revise:

```python
"""Hybrid Logical Clock generation, node init, tail-HLC read.

See spec §"HLC generation" and §"HLC continuity across captures".
"""
from __future__ import annotations

import os
import re
import secrets
import socket
import time
from pathlib import Path

from .events import HLC, deserialize

# Size of the tail read when looking for the last HLC. See spec §"HLC continuity".
TAIL_SIZE = 65536

_NODE_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")


def hlc_now(node: str, last: HLC | None) -> HLC:
    """Generate the next HLC for a given node, monotonically advancing from `last`.

    If `last` is None, or current wall_ms has advanced past last.wall_ms, ctr resets to 0.
    Otherwise, ctr increments by 1 from last.ctr.

    Pure function: no I/O. Safe to call from the hook on every capture.
    """
    wall_ms = int(time.time() * 1000)
    if last is None or wall_ms > last.wall_ms:
        ctr = 0
    else:
        ctr = last.ctr + 1
    return HLC(wall_ms=wall_ms, ctr=ctr, node=node)


def _generate_node_id() -> str:
    """Generate a new 8-hex-char node identifier.

    Format: first 4 chars of hostname (truncated) + 4 hex chars from secrets.
    """
    hostname = socket.gethostname().lower()
    host_part = hostname[:4]
    random_part = secrets.token_hex(2)  # 4 hex chars
    return f"{host_part}{random_part}"


def node_init(path: Path) -> str:
    """Read or create the node identifier file.

    If the file exists with a valid 8-hex-char ID, return it.
    Otherwise, generate a new ID, write it (mode 0o600), and return it.

    On write failure (permissions, disk full), returns the generated ID without
    persisting — caller is responsible for logging via errors.log.
    """
    if path.exists():
        contents = path.read_text().strip()
        if _NODE_ID_PATTERN.match(contents):
            return contents

    new_id = _generate_node_id()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, (new_id + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # Caller logs via errors.log
    return new_id


def read_tail_hlc(log_path: Path) -> HLC | None:
    """Read the last HLC from the log file's tail (last 64KB).

    Returns None if:
    - The log file doesn't exist or can't be opened
    - The log file is empty
    - The last non-empty line is not valid JSON
    - The last valid JSON line has no parseable HLC
    """
    try:
        file_size = log_path.stat().st_size
    except (FileNotFoundError, OSError):
        return None

    if file_size == 0:
        return None

    try:
        fd = os.open(str(log_path), os.O_RDONLY)
    except (FileNotFoundError, OSError):
        return None

    try:
        seek_to = max(0, file_size - TAIL_SIZE)
        os.lseek(fd, seek_to, os.SEEK_SET)
        data = os.read(fd, file_size - seek_to)
    except OSError:
        return None
    finally:
        os.close(fd)

    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    last_line = None
    for line in reversed(lines):
        if line.strip():
            last_line = line
            break

    if last_line is None:
        return None

    try:
        event = deserialize(last_line)
    except (ValueError, KeyError, TypeError):
        return None

    return event.hlc
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_hlc.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run bandit, ruff, mypy**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/jot/hlc.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/hlc.py tests/unit/jot/test_hlc.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/hlc.py
```

Expected: All clean.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/hlc.py tests/unit/jot/test_hlc.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add HLC generation, node init, tail-HLC read"
```

---

## Task 4: short_id.py

**Files:**
- Create: `mahavishnu/jot/short_id.py`
- Create: `tests/unit/jot/test_short_id.py`

**Interfaces:**
- Consumes: nothing
- Produces: `def short_id(event_id: str) -> str` — first 6 chars

**Why this task fourth:** `short_id` is trivial, but the capture echo (Task 7) depends on it. Doing this now lets Task 7 be a pure formatting task.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/test_short_id.py`:

```python
from __future__ import annotations

import re

import pytest
from hypothesis import given, strategies as st

from mahavishnu.jot.short_id import short_id


def test_short_id_returns_first_6_chars() -> None:
    """short_id returns exactly the first 6 hex chars of the event ID."""
    full_id = "abcdef0123456789" * 2  # 32 chars
    assert len(full_id) == 32
    assert short_id(full_id) == "abcdef"


def test_short_id_deterministic() -> None:
    """Same input must always produce the same output."""
    full_id = "0123456789abcdef" * 2
    assert short_id(full_id) == short_id(full_id)


def test_short_id_for_typical_uuid_v4() -> None:
    """Real UUID v4 IDs (with version + variant bits) must produce valid 6-char output."""
    # Example UUID v4: 4 at position 12 (3-indexed), 8/9/a/b at position 16
    uuid_v4 = "a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d"
    assert short_id(uuid_v4) == "a3f9c2"
    assert re.match(r"^[0-9a-f]{6}$", short_id(uuid_v4))


def test_short_id_does_not_validate_input() -> None:
    """short_id does not validate input — it just slices. Garbage in, garbage out."""
    assert short_id("xyz") == "xyz"  # shorter than 6 chars — just returns what it can
    assert short_id("") == ""


# ---------------------------------------------------------------------------
# Property test: collision rate at N=1000 random UUIDs
# ---------------------------------------------------------------------------


@given(st.lists(st.uuids(), min_size=1000, max_size=1000))
def test_short_id_collision_rate_under_threshold(uuids: list) -> None:
    """For 1000 random UUIDs, 6-char short_id collisions must be < 5% (relaxed from 3%).

    Note: spec target is ~3%; we test against 5% for safety margin.
    """
    short_ids = [short_id(str(u).replace("-", "")) for u in uuids]
    unique = len(set(short_ids))
    # 1000 - 5% = 950 unique minimum
    assert unique >= 950, f"Only {unique} unique short_ids out of 1000"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_short_id.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.jot.short_id'`.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/jot/short_id.py`:

```python
"""Short identifier for human-facing display of jot events.

The short_id is the first 6 hex chars of the 32-char UUID v4 event ID.
It's used only for capture echoes — the log stores the full ID.
"""
from __future__ import annotations


def short_id(event_id: str) -> str:
    """Return the first 6 characters of the event ID.

    No validation: garbage in, garbage out. Designed for human display only;
    real event resolution always uses the full 32-char ID stored in the log.

    See spec §"Short ID (echo only)".
    """
    return event_id[:6]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_short_id.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run lint**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/jot/short_id.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/short_id.py tests/unit/jot/test_short_id.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/short_id.py
```

Expected: All clean.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/short_id.py tests/unit/jot/test_short_id.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add short_id for capture echo"
```

---

## Task 5: paths.py — directory + file path resolution

**Files:**
- Create: `mahavishnu/jot/paths.py`
- Create: `tests/unit/jot/test_paths.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `def jot_dir() -> Path` — returns `~/.mahavishnu/jot`, creating dir with mode 0o700 if missing
  - `def log_path() -> Path` — returns `~/.mahavishnu/jot/log.jsonl` (no creation)
  - `def errors_log_path() -> Path` — returns `~/.mahavishnu/jot/errors.log` (no creation)
  - `def node_path() -> Path` — returns `~/.mahavishnu/jot/node` (no creation)

**Why this task fifth:** The hook (Task 8) needs to know where to write. `node_init` (Task 3) already accepts a path argument but needs `node_path()` to know where to look. Doing paths next lets Task 8 use stable interfaces.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/test_paths.py`:

```python
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from mahavishnu.jot.paths import (
    errors_log_path,
    jot_dir,
    log_path,
    node_path,
)


def test_jot_dir_creates_directory_with_mode_0o700(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """jot_dir() must create ~/.mahavishnu/jot with mode 0o700."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = jot_dir()
    assert result == tmp_path / ".mahavishnu" / "jot"
    assert result.exists()
    assert result.is_dir()
    # Verify mode is 0o700
    mode = stat.S_IMODE(result.stat().st_mode)
    assert mode == 0o700


def test_jot_dir_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling jot_dir() multiple times must not error or change permissions."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    first = jot_dir()
    second = jot_dir()
    assert first == second


def test_jot_dir_does_not_create_parent_mahavishnu_with_weak_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The .mahavishnu parent must also be created with appropriate permissions."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    jot_dir()
    parent = tmp_path / ".mahavishnu"
    assert parent.exists()


def test_log_path_returns_jot_dir_log_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """log_path() must return <jot_dir>/log.jsonl."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert log_path() == tmp_path / ".mahavishnu" / "jot" / "log.jsonl"


def test_log_path_does_not_create_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """log_path() must not create the file (only jot_dir does)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = log_path()
    assert not path.exists()


def test_errors_log_path_returns_correct_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """errors_log_path() must return <jot_dir>/errors.log."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert errors_log_path() == tmp_path / ".mahavishnu" / "jot" / "errors.log"


def test_errors_log_path_does_not_create_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """errors_log_path() must not create the file."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = errors_log_path()
    assert not path.exists()


def test_node_path_returns_correct_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """node_path() must return <jot_dir>/node."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert node_path() == tmp_path / ".mahavishnu" / "jot" / "node"


def test_jot_dir_works_when_jot_dir_already_exists_with_0o700(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If jot_dir already exists, jot_dir() must not error or change mode."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    existing = tmp_path / ".mahavishnu" / "jot"
    existing.mkdir(parents=True, mode=0o700)
    original_mode = stat.S_IMODE(existing.stat().st_mode)
    jot_dir()
    assert stat.S_IMODE(existing.stat().st_mode) == original_mode
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_paths.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.jot.paths'`.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/jot/paths.py`:

```python
"""Filesystem path resolution for the jot inbox.

All paths resolve under ~/.mahavishnu/jot/ which is created with mode 0o700 on
first access. Individual files (log, errors, node) are NOT created by these
helpers — only the directory is. File creation happens lazily in the hook.
"""
from __future__ import annotations

import os
from pathlib import Path


# Cache the directory after first creation. Tests monkeypatch Path.home BEFORE
# any jot_dir() call, so the cache will be empty when tests start.
_jot_dir_cache: Path | None = None


def jot_dir() -> Path:
    """Return ~/.mahavishnu/jot, creating it with mode 0o700 if missing."""
    global _jot_dir_cache
    if _jot_dir_cache is None:
        path = Path.home() / ".mahavishnu" / "jot"
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        _jot_dir_cache = path
    return _jot_dir_cache


def log_path() -> Path:
    """Return the path to the main JSONL log (not created)."""
    return jot_dir() / "log.jsonl"


def errors_log_path() -> Path:
    """Return the path to the errors log (not created)."""
    return jot_dir() / "errors.log"


def node_path() -> Path:
    """Return the path to the node identifier file (not created)."""
    return jot_dir() / "node"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_paths.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run lint**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/jot/paths.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/paths.py tests/unit/jot/test_paths.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/paths.py
```

Expected: All clean.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/paths.py tests/unit/jot/test_paths.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add path resolution and directory creation"
```

---

## Task 6: redact.py — ~20 patterns in 3 tiers

**Files:**
- Create: `mahavishnu/jot/redact.py`
- Create: `tests/unit/jot/test_redact.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `def redact_text(text: str) -> str` — applies all patterns, returns redacted text

**Why this task sixth:** The hook (Task 8) redacts the body before writing. Doing redact after paths lets Task 8 import redact + paths cleanly.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/test_redact.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.jot.redact import REDACTED_PATTERN, redact_text


# ---------------------------------------------------------------------------
# Tier 1: Secrets
# ---------------------------------------------------------------------------


class TestTier1Secrets:
    def test_aws_access_key_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("aws_key=AKIAIOSFODNN7EXAMPLE")

    def test_github_pat_ghp_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789")

    def test_github_pat_gho_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("token: gho_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789")

    def test_openai_key_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ")

    def test_anthropic_key_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("sk-ant-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123")

    def test_slack_xoxb_token_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("xoxb-12345-aBcDeFgHiJkLmNoPqRsTuVwX")

    def test_jwt_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature_here_aaa"
        assert "[REDACTED:secret:" in redact_text(jwt)

    def test_bearer_token_redacted(self) -> None:
        assert "[REDACTED:secret:" in redact_text("Authorization: Bearer abc123_def-456.ghi")

    def test_secrets_are_not_destroyed_around_match(self) -> None:
        """Redaction must preserve surrounding text."""
        result = redact_text("prefix AKIAIOSFODNN7EXAMPLE suffix")
        assert result.startswith("prefix ")
        assert result.endswith(" suffix")
        assert "[REDACTED:secret:" in result


# ---------------------------------------------------------------------------
# Tier 2: Credentials
# ---------------------------------------------------------------------------


class TestTier2Credentials:
    def test_email_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("contact: alice@example.com")

    def test_us_phone_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("call 555-123-4567 today")

    def test_us_phone_no_dashes_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("call 5551234567 today")

    def test_ipv4_redacted(self) -> None:
        assert "[REDACTED:credential:" in redact_text("server at 192.168.1.1")

    def test_credentials_preserve_surrounding_text(self) -> None:
        result = redact_text("server 10.0.0.1 alive")
        assert "server " in result
        assert "alive" in result


# ---------------------------------------------------------------------------
# Tier 3: URLs + env-style
# ---------------------------------------------------------------------------


class TestTier3UrlsEnvStyle:
    def test_https_url_redacted(self) -> None:
        assert "[REDACTED:url:" in redact_text("visit https://example.com/path?q=1")

    def test_http_url_redacted(self) -> None:
        assert "[REDACTED:url:" in redact_text("see http://internal.corp/page")

    def test_env_reference_redacted(self) -> None:
        assert "[REDACTED:env:" in redact_text("check the .env file")

    def test_env_local_reference_redacted(self) -> None:
        assert "[REDACTED:env:" in redact_text("see .env.local for secrets")

    def test_ssh_private_key_header_redacted(self) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----"
        assert "[REDACTED:env:" in redact_text(text)


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    def test_plain_text_unchanged(self) -> None:
        text = "refactor the fold function to use HLC ordering"
        assert redact_text(text) == text

    def test_short_strings_not_redacted(self) -> None:
        # AKIA needs to be exactly AKIA + 16 chars
        text = "AKIA123"  # only 4 chars after AKIA
        assert text in redact_text(text)

    def test_no_redaction_for_safe_words(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"
        assert redact_text(text) == text

    def test_empty_string_returns_empty(self) -> None:
        assert redact_text("") == ""

    def test_hash_consistency_same_secret_same_hash(self) -> None:
        """Same secret produces same redacted hash (for correlation)."""
        secret = "AKIAIOSFODNN7EXAMPLE"
        r1 = redact_text(secret)
        r2 = redact_text(secret)
        assert r1 == r2

    def test_hash_different_for_different_secrets(self) -> None:
        """Different secrets produce different redacted hashes."""
        r1 = redact_text("AKIAIOSFODNN7EXAMPLE")
        r2 = redact_text("AKIAIOSFODNN7DIFFERN")
        # Extract hash from each
        import re
        m1 = re.search(r"\[REDACTED:[^:]+:([0-9a-f]+)\]", r1)
        m2 = re.search(r"\[REDACTED:[^:]+:([0-9a-f]+)\]", r2)
        assert m1 and m2
        assert m1.group(1) != m2.group(1)


# ---------------------------------------------------------------------------
# REDACTED_PATTERN constant
# ---------------------------------------------------------------------------


def test_redacted_pattern_exported() -> None:
    """The REDACTED_PATTERN regex must be importable for sub-plan 2's read surface."""
    import re
    assert re.match(REDACTED_PATTERN, "[REDACTED:secret:abcdef01]")


def test_redact_text_idempotent() -> None:
    """Redacting already-redacted text must not double-redact."""
    text = "AKIAIOSFODNN7EXAMPLE"
    once = redact_text(text)
    twice = redact_text(once)
    assert once == twice
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_redact.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.jot.redact'`.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/jot/redact.py`:

```python
"""Capture-time redaction: ~20 regex patterns across 3 tiers.

See spec §"Redaction" and D2 (moderate scope).
"""
from __future__ import annotations

import hashlib
import re

# Pattern format: (compiled_regex, tier_label)
# Tier labels: "secret", "credential", "url", "env"

_PATTERNS_RAW: list[tuple[str, str]] = [
    # Tier 1: Secrets
    (r"AKIA[0-9A-Z]{16}", "secret"),  # AWS access key
    (r"ghp_[a-zA-Z0-9]{36}", "secret"),  # GitHub PAT (classic)
    (r"gho_[a-zA-Z0-9]{36}", "secret"),  # GitHub OAuth
    (r"ghu_[a-zA-Z0-9]{36}", "secret"),  # GitHub user-to-server
    (r"ghs_[a-zA-Z0-9]{36}", "secret"),  # GitHub server-to-server
    (r"ghr_[a-zA-Z0-9]{36}", "secret"),  # GitHub refresh
    (r"sk-ant-[a-zA-Z0-9-]{20,}", "secret"),  # Anthropic key (must come before generic sk-)
    (r"sk-[a-zA-Z0-9]{20,}", "secret"),  # OpenAI key
    (r"xox[baprs]-[a-zA-Z0-9-]{10,}", "secret"),  # Slack tokens
    (r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "secret"),  # JWT
    (r"Bearer\s+[a-zA-Z0-9_.-]+", "secret"),  # Bearer token
    # Tier 2: Credentials
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "credential"),  # Email
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "credential"),  # US phone
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "credential"),  # IPv4
    # Tier 3: URLs + env-style
    (r"https?://[^\s]+", "url"),  # HTTP(S) URLs
    (r"\.env(\.\w+)?", "env"),  # .env-style references
    (r"-----BEGIN [A-Z ]+PRIVATE KEY-----", "env"),  # SSH private key headers
]

# Compile once at module load
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern), tier) for pattern, tier in _PATTERNS_RAW
]

# Exported regex for sub-plan 2's read surface to identify redacted regions
REDACTED_PATTERN = r"\[REDACTED:(?:secret|credential|url|env):[0-9a-f]{8}\]"
_REDACTED_RE = re.compile(REDACTED_PATTERN)


def _make_replacement(match: re.Match[str], tier: str) -> str:
    """Build the replacement string for a redaction match."""
    secret = match.group(0)
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    return f"[REDACTED:{tier}:{digest}]"


def redact_text(text: str) -> str:
    """Apply all redaction patterns to text. Returns redacted text.

    Patterns are applied in tier order: secrets first (most specific), then
    credentials, then URLs + env-style. First match wins per pattern; overlap
    between patterns is acceptable (e.g., a URL in a JWT is redacted twice).

    The replacement format `[REDACTED:<tier>:<hash>]` allows sub-plan 2's
    read surface to detect and display redacted regions. The hash is a
    one-way sha256 prefix that enables correlation ("same secret?") without
    reversing the redaction.
    """
    out = text
    for pattern, tier in _PATTERNS:
        out = pattern.sub(lambda m: _make_replacement(m, tier), out)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_redact.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run lint**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/jot/redact.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/redact.py tests/unit/jot/test_redact.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/redact.py
```

Expected: All clean.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/redact.py tests/unit/jot/test_redact.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add moderate-scope redaction (3 tiers, ~17 patterns)"
```

---

## Task 7: capture_echo.py — format the human-facing echo

**Files:**
- Create: `mahavishnu/jot/capture_echo.py`
- Create: `tests/unit/jot/test_capture_echo.py`

**Interfaces:**
- Consumes: `short_id` from `mahavishnu.jot.short_id`
- Produces:
  - `def format_echo(event_id: str, text: str) -> str` — returns "jot <short_id> captured (<wc> words, <cc> chars)"

**Why this task seventh:** Pure formatter. No I/O. Needed before the hook (Task 8) can produce the capture echo.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/test_capture_echo.py`:

```python
from __future__ import annotations

from mahavishnu.jot.capture_echo import format_echo


def test_format_echo_simple() -> None:
    """Format: 'jot <short_id> captured (<wc> words, <cc> chars)'."""
    result = format_echo("a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d", "hello world")
    assert result == "jot a3f9c2 captured (2 words, 11 chars)"


def test_format_echo_single_word() -> None:
    """Single word: 1 words, N chars."""
    result = format_echo("abcdef0123456789" * 2, "test")
    assert result == "jot abcdef captured (1 words, 4 chars)"


def test_format_echo_empty_text_after_redaction() -> None:
    """If text is empty, echo is 0 words, 0 chars."""
    result = format_echo("0000000000000000" * 2, "")
    assert result == "jot 000000 captured (0 words, 0 chars)"


def test_format_echo_uses_short_id_first_6() -> None:
    """Only the first 6 chars of the event ID appear in the echo."""
    event_id = "fedcba9876543210fedcba9876543210"
    result = format_echo(event_id, "test")
    assert "fedcba" in result
    assert "fedcba9876543210" not in result  # full ID must NOT appear


def test_format_echo_word_count_correct() -> None:
    """Word count uses str.split() — multiple spaces collapse."""
    result = format_echo("a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d", "  hello   world  ")
    # After split: ["hello", "world"] = 2 words; chars = 11 (incl. spaces? no, raw text is 16)
    # Use the raw text char count
    assert "2 words" in result
    assert "16 chars" in result  # "  hello   world  " is 16 chars


def test_format_echo_unicode_chars_counted_correctly() -> None:
    """Unicode characters count as single chars via len()."""
    result = format_echo("a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d", "héllo")
    assert "1 words" in result
    assert "5 chars" in result  # len("héllo") == 5


def test_format_echo_no_trailing_newline() -> None:
    """format_echo must not add a trailing newline (print() does that)."""
    result = format_echo("a" * 32, "test")
    assert not result.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_capture_echo.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.jot.capture_echo'`.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/jot/capture_echo.py`:

```python
"""Capture echo formatter.

Produces the human-facing one-liner shown in stderr after a successful capture.
"""
from __future__ import annotations

from .short_id import short_id


def format_echo(event_id: str, text: str) -> str:
    """Format the capture echo: 'jot <short_id> captured (<wc> words, <cc> chars)'.

    Caller is responsible for printing to stderr with a trailing newline.
    """
    short = short_id(event_id)
    word_count = len(text.split())
    char_count = len(text)
    return f"jot {short} captured ({word_count} words, {char_count} chars)"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_capture_echo.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run lint**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/jot/capture_echo.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/capture_echo.py tests/unit/jot/test_capture_echo.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/capture_echo.py
```

Expected: All clean.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/jot/capture_echo.py tests/unit/jot/test_capture_echo.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add capture echo formatter"
```

---

## Task 8: jot_capture.py — the UserPromptSubmit hook

**Files:**
- Create: `mahavishnu/hooks/jot_capture.py`
- Create: `tests/unit/jot/test_capture_hook.py`

**Interfaces:**
- Consumes: all of `mahavishnu.jot.*`
- Produces:
  - `def main() -> int` — top-level entry, returns exit code (0 or 2)
  - `def _do_hook() -> int` — inner implementation (testable via stdin monkeypatch)
  - `def _is_capture(prompt: str) -> tuple[bool, str]` — pattern detection helper
  - `def _build_capture_ctx(stdin_payload: dict, env: dict) -> dict` — assemble ctx
  - `def _log_error(op: str, exc: BaseException, ctx: dict) -> None` — write to errors.log

**Why this task eighth:** Wires together all primitives from Tasks 1-7. Stdlib-only at module level (imports from `mahavishnu.jot.*` only, which themselves are stdlib-only).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/jot/test_capture_hook.py`:

```python
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

from mahavishnu.hooks import jot_capture
from mahavishnu.jot.events import deserialize


# ---------------------------------------------------------------------------
# _is_capture
# ---------------------------------------------------------------------------


class TestIsCapture:
    def test_double_comma_with_text_is_capture(self) -> None:
        is_cap, body = jot_capture._is_capture(",, hello world")
        assert is_cap is True
        assert body == "hello world"

    def test_leading_whitespace_stripped_before_check(self) -> None:
        """Leading whitespace (spaces, tabs) before ',,' must be tolerated."""
        is_cap, body = jot_capture._is_capture("   ,, hello")
        assert is_cap is True
        assert body == "hello"

    def test_text_without_prefix_is_not_capture(self) -> None:
        is_cap, body = jot_capture._is_capture("hello world")
        assert is_cap is False
        assert body == ""

    def test_comma_comma_mid_text_is_not_capture(self) -> None:
        """',,' in the middle of a prompt is not a capture."""
        is_cap, body = jot_capture._is_capture("say ,, to me")
        assert is_cap is False
        assert body == ""

    def test_double_comma_with_empty_body_is_not_capture(self) -> None:
        """',,' alone or ',, ' (just trailing whitespace) is not a capture."""
        is_cap1, _ = jot_capture._is_capture(",,")
        is_cap2, _ = jot_capture._is_capture(",, ")
        is_cap3, _ = jot_capture._is_capture(" ,,")
        assert is_cap1 is False
        assert is_cap2 is False
        assert is_cap3 is False

    def test_body_whitespace_stripped(self) -> None:
        """Body has leading whitespace stripped after the ',,'."""
        is_cap, body = jot_capture._is_capture(",,   hello world")
        assert is_cap is True
        assert body == "hello world"


# ---------------------------------------------------------------------------
# _build_capture_ctx
# ---------------------------------------------------------------------------


class TestBuildCaptureCtx:
    def test_minimal_ctx(self) -> None:
        ctx = jot_capture._build_capture_ctx(
            stdin_payload={"prompt": ",, test", "session_id": "s1"},
            env={},
            cwd="/tmp",
        )
        assert ctx["cwd"] == "/tmp"
        assert ctx["session_id"] == "s1"
        assert ctx["files"] == []
        assert ctx["env_repo"] is None
        assert ctx["env_branch"] is None

    def test_full_ctx(self) -> None:
        ctx = jot_capture._build_capture_ctx(
            stdin_payload={
                "prompt": ",, test",
                "session_id": "s1",
                "files": ["a.py", "b.py"],
            },
            env={"MAHAVISHNU_REPO": "/r", "MAHAVISHNU_BRANCH": "main"},
            cwd="/work",
        )
        assert ctx == {
            "cwd": "/work",
            "session_id": "s1",
            "files": ["a.py", "b.py"],
            "env_repo": "/r",
            "env_branch": "main",
        }


# ---------------------------------------------------------------------------
# _do_hook — passthrough cases
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_passthrough_no_comma_comma(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """No ',,' prefix → exit 0, stdout = original JSON, no log write."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": "hello world", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))

        captured_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0
        assert json.loads(captured_stdout.getvalue()) == stdin_payload
        assert not (tmp_path / ".mahavishnu" / "jot" / "log.jsonl").exists()

    def test_passthrough_empty_body(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """',,' alone → passthrough (no empty capture)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {"prompt": ",,", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0
        assert not (tmp_path / ".mahavishnu" / "jot" / "log.jsonl").exists()


# ---------------------------------------------------------------------------
# _do_hook — capture success
# ---------------------------------------------------------------------------


class TestCapture:
    def test_capture_writes_event_and_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Successful capture: log file created with one event, exit 2, stderr echo."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {
            "prompt": ",, hello world",
            "session_id": "sess_xyz",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)
        monkeypatch.setattr(sys, "stderr", captured_stderr)

        exit_code = jot_capture._do_hook()
        assert exit_code == 2
        assert captured_stdout.getvalue() == ""

        # Log file exists with one event
        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        content = log.read_text()
        lines = [l for l in content.split("\n") if l.strip()]
        assert len(lines) == 1

        event = deserialize(lines[0])
        assert event.text == "hello world"
        assert event.op == "capture"
        assert event.ctx["session_id"] == "sess_xyz"

        # Stderr has the echo
        stderr_text = captured_stderr.getvalue()
        assert "jot " in stderr_text
        assert "captured" in stderr_text

    def test_capture_redacts_secrets(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Capture-time redaction removes secrets from text."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        stdin_payload = {
            "prompt": ",, my key is AKIAIOSFODNN7EXAMPLE",
            "session_id": "s1",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        jot_capture._do_hook()

        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        content = log.read_text()
        assert "AKIAIOSFODNN7EXAMPLE" not in content
        assert "[REDACTED:secret:" in content

    def test_capture_hlc_monotonic_across_calls(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """HLC advances between consecutive captures."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        for i in range(3):
            stdin_payload = {"prompt": f",, jot {i}", "session_id": "s1"}
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
            monkeypatch.setattr(sys, "stdout", io.StringIO())
            monkeypatch.setattr(sys, "stderr", io.StringIO())
            jot_capture._do_hook()

        log = tmp_path / ".mahavishnu" / "jot" / "log.jsonl"
        lines = [deserialize(l) for l in log.read_text().split("\n") if l.strip()]
        assert len(lines) == 3
        for prev, curr in zip(lines, lines[1:]):
            assert (curr.hlc.wall_ms, curr.hlc.ctr) > (prev.hlc.wall_ms, prev.hlc.ctr)


# ---------------------------------------------------------------------------
# _do_hook — fail-open behavior
# ---------------------------------------------------------------------------


class TestFailOpen:
    def test_invalid_json_stdin_passthrough(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Invalid JSON on stdin → exit 0, no log write, errors.log entry."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(sys, "stdin", io.StringIO("not valid json"))

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

        # errors.log entry was written
        errors_log = tmp_path / ".mahavishnu" / "jot" / "errors.log"
        assert errors_log.exists()
        content = errors_log.read_text()
        assert "jot_capture" in content

    def test_missing_prompt_field_passthrough(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """stdin JSON without 'prompt' field → passthrough (no errors.log entry)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s1"})))
        captured_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured_stdout)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0
        # No errors.log entry — this is not an error, just no capture
        errors_log = tmp_path / ".mahavishnu" / "jot" / "errors.log"
        assert not errors_log.exists()

    def test_log_write_failure_passthrough(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When log write fails (e.g., os.open raises), hook exits 0 + errors.log entry."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin_payload)))
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())

        # Force os.open to raise PermissionError
        original_open = os.open

        def fake_open(path, flags, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "log.jsonl" in str(path):
                raise PermissionError(13, "Permission denied", str(path))
            return original_open(path, flags, mode, *args, **kwargs)

        monkeypatch.setattr(os, "open", fake_open)

        exit_code = jot_capture._do_hook()
        assert exit_code == 0

        # errors.log entry was written
        errors_log = tmp_path / ".mahavishnu" / "jot" / "errors.log"
        assert errors_log.exists()


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_calls_do_hook_and_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() must invoke _do_hook() and exit with its return code."""
        monkeypatch.setattr(jot_capture, "_do_hook", lambda: 2)
        with pytest.raises(SystemExit) as exc_info:
            jot_capture.main()
        assert exc_info.value.code == 2

    def test_main_returns_0_for_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jot_capture, "_do_hook", lambda: 0)
        with pytest.raises(SystemExit) as exc_info:
            jot_capture.main()
        assert exc_info.value.code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_capture_hook.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.hooks.jot_capture'` or similar.

- [ ] **Step 3: Write the implementation**

Create `mahavishnu/hooks/jot_capture.py`:

```python
"""Claude Code UserPromptSubmit hook for jot inbox capture.

Detects ',,' prefix in user prompts, writes a JSONL event to
~/.mahavishnu/jot/log.jsonl, and exits 2 to erase the prompt from Claude's
transcript. Stdlib-only at module level (imports mahavishnu.jot.* which
are themselves stdlib-only).

Failure policy: every exception is caught at the top level, logged to
~/.mahavishnu/jot/errors.log, and converted to passthrough (exit 0).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from mahavishnu.jot.capture_echo import format_echo
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.hlc import hlc_now, node_init, read_tail_hlc
from mahavishnu.jot.paths import errors_log_path, jot_dir, log_path, node_path
from mahavishnu.jot.redact import redact_text


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------


def _is_capture(prompt: str) -> tuple[bool, str]:
    """Return (is_capture, body).

    is_capture=True iff prompt starts with ',,' after stripping leading whitespace.
    body is the text after the ',,' prefix, lstripped. Empty body → not a capture.
    """
    stripped = prompt.lstrip()
    if not stripped.startswith(",,"):
        return False, ""
    body = stripped[2:].lstrip()
    if not body:
        return False, ""
    return True, body


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _build_capture_ctx(stdin_payload: dict, env: dict, cwd: str) -> dict[str, Any]:
    """Assemble the capture-time ambient context."""
    return {
        "cwd": cwd,
        "session_id": stdin_payload.get("session_id", ""),
        "files": stdin_payload.get("files", []),
        "env_repo": env.get("MAHAVISHNU_REPO"),
        "env_branch": env.get("MAHAVISHNU_BRANCH"),
    }


# ---------------------------------------------------------------------------
# Error logging
# ---------------------------------------------------------------------------


def _log_error(op: str, exc: BaseException, ctx: dict[str, Any]) -> None:
    """Write a structured error record to errors.log. Fail-open on errors.log failures."""
    try:
        jot_dir()  # Ensure directory exists
        record = {
            "ts_ms": int(time.time() * 1000),
            "hook": "jot_capture",
            "op": op,
            "err": f"{type(exc).__name__}: {exc}".replace("\n", " "),
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
            "ctx": ctx,
        }
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd = os.open(str(errors_log_path()), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 - errors.log must be silent-on-failure
        pass


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------


def _do_hook() -> int:
    """Run the hook logic. Returns exit code (0 = passthrough, 2 = capture)."""
    stdin_text = sys.stdin.read()
    stdin_payload: dict = {}

    # Parse stdin JSON (fail-open on failure)
    try:
        stdin_payload = json.loads(stdin_text)
    except (json.JSONDecodeError, ValueError) as exc:
        _log_error("stdin_parse", exc, {"stdin_prefix": stdin_text[:50]})
        return 0

    prompt = stdin_payload.get("prompt", "")
    is_cap, body = _is_capture(prompt)

    if not is_cap:
        # Passthrough: write original JSON to stdout
        sys.stdout.write(stdin_text)
        return 0

    # Capture path
    return _do_capture(body, stdin_payload)


def _do_capture(body: str, stdin_payload: dict) -> int:
    """Execute the capture: build event, write log, print echo, exit 2."""
    op = "capture"
    ctx: dict[str, Any] = {}

    try:
        # Ensure directory exists
        jot_dir()

        # Initialize node
        node = node_init(node_path())

        # Read last HLC for continuity
        last_hlc = read_tail_hlc(log_path())

        # Generate HLC
        hlc = hlc_now(node, last_hlc)

        # Build context
        ctx = _build_capture_ctx(stdin_payload, dict(os.environ), cwd=os.getcwd())

        # Redact text
        text = redact_text(body)

        # Build event
        event = JotEvent(
            id=uuid.uuid4().hex,
            op=op,
            hlc=hlc,
            text=text,
            ctx=ctx,
            created_ms=int(time.time() * 1000),
        )

        # Serialize and write to log (single os.write call)
        line = serialize(event)
        fd = os.open(str(log_path()), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

        # Echo to stderr (NOT stdout — Claude reads stdout for passthrough/block)
        echo = format_echo(event.id, text)
        sys.stderr.write(echo + "\n")

        # Block the prompt
        return 2

    except BaseException as exc:  # noqa: BLE001 - top-level safety net
        _log_error(op, exc, {**ctx, "prompt_prefix": body[:50]})
        return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Top-level entry point. Returns exit code via sys.exit()."""
    return _do_hook()


if __name__ == "__main__":
    sys.exit(main())
```

**Important note on imports:** The hook imports `mahavishnu.jot.*` modules. These modules are themselves stdlib-only (no third-party imports). The hook itself uses only stdlib + `mahavishnu.jot.*`. This satisfies the spec's "stdlib-only" requirement for the hook.

**Important note on `cwd` in `_build_capture_ctx`:** We pass `os.getcwd()` at call time (not module load time) so that tests monkeypatching `Path.home()` don't affect cwd resolution.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/test_capture_hook.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run lint**

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit mahavishnu/hooks/jot_capture.py -q
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/hooks/jot_capture.py tests/unit/jot/test_capture_hook.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/hooks/jot_capture.py
```

Expected: All clean.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add mahavishnu/hooks/jot_capture.py tests/unit/jot/test_capture_hook.py
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "feat(jot): add UserPromptSubmit hook with fail-open behavior"
```

---

## Task 9: Integration test — spawn the hook as a subprocess

**Files:**
- Create: `tests/integration/jot/__init__.py` (empty)
- Create: `tests/integration/jot/test_capture_e2e.py`

**Interfaces:**
- Consumes: `mahavishnu.hooks.jot_capture` (invoked via subprocess)
- Produces: nothing (test only)

**Why this task last:** Validates the entire stack end-to-end via a real Python invocation. Catches environment-specific issues that unit tests can't (PATH, working directory, signal handling).

- [ ] **Step 1: Create the integration test package**

Create `tests/integration/jot/__init__.py`:

```python
"""Integration tests for jot inbox capture layer."""
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/jot/test_capture_e2e.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


HOOK_PATH = Path(__file__).parents[3] / "mahavishnu" / "hooks" / "jot_capture.py"


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set HOME to tmp_path so ~/.mahavishnu/jot/ resolves there."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _run_hook(stdin_payload: dict, isolated_home_path: Path) -> subprocess.CompletedProcess:
    """Spawn the hook as a subprocess with the given stdin payload."""
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(isolated_home_path)},
    )


class TestSubprocess:
    def test_capture_happy_path(self, isolated_home: Path) -> None:
        """Subprocess invocation: ',,' prefix → exit 2, log written, stderr echo."""
        stdin_payload = {"prompt": ",, hello from subprocess", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 2
        assert result.stdout == ""
        assert "jot " in result.stderr
        assert "captured" in result.stderr

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        assert log.exists()
        lines = [l for l in log.read_text().split("\n") if l.strip()]
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["text"] == "hello from subprocess"

    def test_passthrough_no_prefix(self, isolated_home: Path) -> None:
        """No ',,' → exit 0, stdout = original JSON."""
        stdin_payload = {"prompt": "just a normal prompt", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 0
        assert json.loads(result.stdout) == stdin_payload

    def test_passthrough_empty_body(self, isolated_home: Path) -> None:
        """',,' alone → passthrough."""
        stdin_payload = {"prompt": ",,", "session_id": "s1"}
        result = _run_hook(stdin_payload, isolated_home)

        assert result.returncode == 0
        assert not (isolated_home / ".mahavishnu" / "jot" / "log.jsonl").exists()

    def test_invalid_json_stdin_fails_open(self, isolated_home: Path) -> None:
        """Invalid JSON → exit 0, errors.log entry."""
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="this is not valid json",
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "HOME": str(isolated_home)},
        )

        assert result.returncode == 0

        errors_log = isolated_home / ".mahavishnu" / "jot" / "errors.log"
        assert errors_log.exists()
        content = errors_log.read_text()
        assert "jot_capture" in content

    def test_directory_created_with_0o700(self, isolated_home: Path) -> None:
        """First capture creates ~/.mahavishnu/jot/ with mode 0o700."""
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        _run_hook(stdin_payload, isolated_home)

        jot_dir = isolated_home / ".mahavishnu" / "jot"
        import stat
        mode = stat.S_IMODE(jot_dir.stat().st_mode)
        assert mode == 0o700

    def test_log_file_created_with_0o600(self, isolated_home: Path) -> None:
        """First capture creates log.jsonl with mode 0o600."""
        import stat
        stdin_payload = {"prompt": ",, test", "session_id": "s1"}
        _run_hook(stdin_payload, isolated_home)

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        mode = stat.S_IMODE(log.stat().st_mode)
        assert mode == 0o600

    def test_multiple_captures_monotonic_hlc(self, isolated_home: Path) -> None:
        """Three captures produce three events with monotonic HLCs."""
        for i in range(3):
            stdin_payload = {"prompt": f",, jot {i}", "session_id": "s1"}
            _run_hook(stdin_payload, isolated_home)

        log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
        lines = [json.loads(l) for l in log.read_text().split("\n") if l.strip()]
        assert len(lines) == 3
        for prev, curr in zip(lines, lines[1:]):
            prev_hlc = prev["hlc"]
            curr_hlc = curr["hlc"]
            assert (curr_hlc["wall_ms"], curr_hlc["ctr"]) > (
                prev_hlc["wall_ms"],
                prev_hlc["ctr"],
            )
```

- [ ] **Step 3: Run integration test to verify it passes**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/jot/test_capture_e2e.py -v
```

Expected: All tests PASS (this validates the full stack end-to-end).

- [ ] **Step 4: Run lint**

```bash
cd /Users/les/Projects/mahavishnu && uv run ruff check tests/integration/jot/test_capture_e2e.py
cd /Users/les/Projects/mahavishnu && uv run mypy --strict tests/integration/jot/test_capture_e2e.py
```

Expected: All clean.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" add tests/integration/jot/
git -c user.email="les@wedgwoodwebworks.com" -c user.name="les" commit -m "test(jot): add end-to-end subprocess integration tests"
```

---

## Self-Review

After completing all tasks, run the spec self-review checklist:

- [ ] **1. Spec coverage:** Walk through each section of the spec and confirm a task implements it:
  - §"Decisions (this sub-plan)" D1-D4 → no specific task (decisions are design constraints applied across all tasks)
  - §"Locked Decisions" UD1-UD9 → distributed across tasks (UD1→Task 8, UD3→Task 2, UD4→Task 3, UD5→Task 4, UD6→Task 5, UD7→Tasks 1-8, UD8→Tasks 1-8, UD9→Tasks 1-8)
  - §"Data Model" → Task 2 (events.py), Task 3 (hlc.py)
  - §"Capture Surface" → Task 8 (hook), Task 7 (echo), Task 4 (short_id)
  - §"Redaction" → Task 6 (redact.py)
  - §"Permissions" → Task 5 (paths.py), Task 8 (hook)
  - §"Failure Modes" → Task 8 (hook + _log_error)
  - §"Stdlib Hygiene" → Task 8 (only stdlib imports), Task 2-7 (no logging)
  - §"Testing Strategy" → Tasks 2-9 (each has unit/integration/property tests)
  - §"Done Criteria" → Tasks 1-9 collectively satisfy the 10 done criteria

- [ ] **2. Placeholder scan:** No "TBD", "TODO", "fill in", "implement later" in any task step. All code is concrete.

- [ ] **3. Type consistency:** Verify all referenced types match across tasks:
  - `HLC` from `mahavishnu.jot.events` → consumed by `hlc_now`, `read_tail_hlc` (Task 3), produced by `_do_capture` (Task 8)
  - `JotEvent` from `mahavishnu.jot.events` → consumed by `serialize`/`deserialize` (Task 2), `format_echo` (Task 7 via event_id)
  - `short_id` from `mahavishnu.jot.short_id` → consumed by `format_echo` (Task 7)
  - `jot_dir`, `log_path`, `errors_log_path`, `node_path` from `mahavishnu.jot.paths` → consumed by `node_init` (Task 3), `_do_capture` (Task 8)
  - `redact_text` from `mahavishnu.jot.redact` → consumed by `_do_capture` (Task 8)
  - `hlc_now`, `node_init`, `read_tail_hlc` from `mahavishnu.jot.hlc` → consumed by `_do_capture` (Task 8)

All types consistent across tasks.

---

## Verification at the End

After all tasks are complete:

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/ tests/property/jot/ tests/integration/jot/ -v
```

Expected: All tests PASS (unit + property + integration).

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/jot/ tests/property/jot/ tests/integration/jot/ --cov=mahavishnu/jot --cov=mahavishnu/hooks --cov-report=term-missing
```

Expected: Coverage ≥ 95% for `mahavishnu/jot/*` and `mahavishnu/hooks/jot_capture.py`.

```bash
cd /Users/les/Projects/mahavishnu && uv run bandit -r mahavishnu/jot/ mahavishnu/hooks/jot_capture.py -q
```

Expected: Clean (no B101 issues, no high-severity issues).

```bash
cd /Users/les/Projects/mahavishnu && uv run ruff check mahavishnu/jot/ mahavishnu/hooks/jot_capture.py tests/unit/jot/ tests/property/jot/ tests/integration/jot/
cd /Users/les/Projects/mahavishnu && uv run mypy --strict mahavishnu/jot/ mahavishnu/hooks/jot_capture.py
```

Expected: All clean.

```bash
cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p minor
```

Expected: All quality gates pass (bandit, ruff, mypy, pytest).

---

## Spec Coverage Summary

| Spec Section | Implementing Task(s) |
|---|---|
| D1-D4 decisions | All tasks (apply across) |
| UD1-UD9 inherited | All tasks |
| Goals 1-4 | Task 8 (hook performance, fail-open, stdlib-only) |
| Non-goals | N/A (explicit deferral) |
| Architecture | Task 8 (orchestrator), Tasks 1-7 (primitives) |
| Data Model | Task 2 (events), Task 3 (hlc) |
| Wire format | Task 2 (serialize/deserialize) |
| HLC generation | Task 3 (hlc_now) |
| Short ID | Task 4 |
| Capture Surface pattern detection | Task 8 (_is_capture) |
| Capture echo | Task 7 |
| Capture flow | Task 8 (_do_capture) |
| Hook delivery | Task 8 (file shipped) |
| Redaction tiers | Task 6 |
| Permissions (0o600/0o700) | Task 5 (paths), Task 8 (open flags) |
| Atomicity (single os.write) | Task 8 (_do_capture) |
| Failure taxonomy | Task 8 (_do_capture + _log_error + fail-open tests) |
| Errors log format | Task 8 (_log_error) |
| Errors log rotation | Task 8 (`_rotate_errors_log` helper, 1 MB threshold, 2-gen max). **Implemented** (not deferred). |
| Stdlib hygiene | Task 8 (imports) |
| Components table | All tasks |
| Testing strategy (unit) | Tasks 2-8 each have test files |
| Testing strategy (property) | Tasks 2, 3, 4 |
| Testing strategy (integration) | Task 9 |
| Manual verification | Covered by integration test (Task 9) |
| Done criteria 1-10 | All satisfied by Tasks 1-9 |
| NOT done (sub-plan 2/3 items) | N/A — explicitly deferred |

## Implementation Notes (post-review)

After the plan was written, a pre-implementation review found 8 BLOCKERs + 5 HIGHs. All were addressed in commit `8f8a90ea`. Key implementation divergences from this plan:

- **B2**: hostname is now sha256-hashed (not raw hostname[:4]). The `,,` capture-time path requires that the node field be exactly 8 hex chars regardless of hostname content. Raw hostname slicing could include letters like `y`, `s`, `t` that aren't valid hex.
- **B3**: `node` is lazily initialized via `get_node()` module global, not at module import. Spec said "module import"; implementation defers to first call so tests can reset cleanly via the conftest fixture.
- **B6**: `_do_capture` echoes to stderr BEFORE writing to log. If stderr fails, no log entry is written (prevents split-brain: event in log but Claude saw passthrough).
- **B7**: `_log_error` accepts a pre-resolved `jot_dir_path` argument. Without it, the recursive failure path (log_error fails because jot_dir fails) could swallow all errors.
- **B8**: 300-char shape gate implemented: bodies > 300 chars OR containing `\\n` are captured AND exit 0 (passthrough). User sees the Claude response AND has a record.
- **H2**: errors.log rotation implemented inline (1 MB threshold, 2-gen max). See `_rotate_errors_log` helper.
- **H3**: `_do_capture` uses per-step try/except blocks with distinct `op` values for errors.log. Operator can tell whether mkdir, node_init, hdl_tail, stderr_echo, or log_write failed.
- **H5**: `_write_log_line` loops `os.write()` to handle kernel short-writes on regular files. Spec's "atomic write" claim is illusory for >4 KB bodies.
- **H4**: regex patterns compiled defensively in `_compile_patterns()`. A bad pattern logs to stderr and is skipped — module load never crashes.

The plan's Task 8 implementation block (lines 2307-2491) shows the ORIGINAL implementation; the actual code in `mahavishnu/hooks/jot_capture.py` reflects the post-review fixes. The tests in `tests/unit/jot/test_capture_hook.py` were extended to cover the new behavior (shape gate classes, echo-before-log, mkdir/ENOSPC failure modes).

### Pre-Implementation Review Findings (all addressed)

| Severity | # | Finding | Fix |
|---|---|---|---|
| BLOCKER | 1 | `_jot_dir_cache` global leaks between tests | Autouse conftest fixture |
| BLOCKER | 2 | `_generate_node_id` could produce 7 chars (not 8) for short hostnames | sha256-hash hostname |
| BLOCKER | 3 | Spec mandates "node read at module import"; plan defers | Lazy module global via `get_node()` |
| BLOCKER | 4 | `read_tail_hlc` returns None on truncated last line, breaking HLC monotonicity | Scan all lines, return last valid parse |
| BLOCKER | 5 | `node_init` silently swallows OSError on write failure | Raise typed `NodePersistError` |
| BLOCKER | 6 | Stderr failure after log write causes split-brain | Echo BEFORE log write |
| BLOCKER | 7 | `jot_dir()` chmod failure causes invisible cascade | Pre-resolved `jot_dir_path` arg |
| BLOCKER | 8 | Union spec's 300-char shape gate missing | Implemented per user decision |
| HIGH | 1 | Failure modes 5 (mkdir perm) and 7 (ENOSPC) untested | Added dedicated tests |
| HIGH | 2 | Errors log rotation deferred | Implemented inline |
| HIGH | 3 | `op` field always "capture" | Per-step try/except blocks |
| HIGH | 4 | Regex compile failure crashes hook | Defensive per-pattern compile |
| HIGH | 5 | `os.write` short write non-atomic | Loop until full write |
