# Unified iTerm2 AppleScript Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify AppleScript/iTerm2 integration across mdinject (Swift) and Mahavishnu (Python) using Approach C: Specification-First with Native Implementations.

**Architecture:** Define canonical ITerm2 session schema, escaping rules, and AppleScript patterns in a shared spec document. Both languages implement to spec, conformance-tested independently. No runtime dependency between Swift and Python.

**Tech Stack:** Python (asyncio, mcp-common), Swift (NSAppleScript), macOS iTerm2

---

## Phase 1: Shared Specification (Single Task)

### Task 1: Write Canonical ITerm2 AppleScript Protocol Spec

**Files:**
- Create: `mcp-common/docs/iterm2-applescript-protocol.md`
- Reference: `docs/superpowers/specs/2026-05-23-unified-iterm2-applescript-design.md`

This task is complete — the design doc at `docs/superpowers/specs/2026-05-23-unified-iterm2-applescript-design.md` serves as the source of truth. Copy the canonical portions to `mcp-common/docs/iterm2-applescript-protocol.md` for discoverability.

**Steps:**

- [ ] **Step 1: Create mcp-common/docs directory structure**

```bash
mkdir -p /Users/les/Projects/mcp-common/docs
```

- [ ] **Step 2: Write the protocol spec**

Create `mcp-common/docs/iterm2-applescript-protocol.md` containing:
- Canonical `ITerm2Session` schema (all fields, types)
- Escaping rules algorithm (step-by-step)
- AppleScript pattern templates (enumerate, send, create, close, bounds)
- Session ID format: `"session_{iTerm2IntId}"` — string format
- Conformance test requirements

- [ ] **Step 3: Copy spec to mcp-common and commit**

```bash
cd /Users/les/Projects/mcp-common
git add docs/iterm2-applescript-protocol.md
git commit -m "docs: add iTerm2 AppleScript protocol spec"
```

---

## Phase 2: Python Side (Mahavishnu + mcp-common)

### Task 2: Update mcp-common AppleScript Bridge — Multi-Line Escaping

**Files:**
- Modify: `mcp-common/mcp_common/apple_script/bridge.py`
- Create: `mcp-common/tests/unit/test_apple_script_bridge.py`
- Reference: `mcp-common/docs/iterm2-applescript-protocol.md` (escaping rules)

**Current state:** `bridge.py` has no escaping utilities — caller handles it. Need to add canonical escaping functions.

- [ ] **Step 1: Write failing test for multi-line escaping**

```python
# mcp-common/tests/unit/test_apple_script_bridge.py
import pytest
from mcp_common.apple_script.bridge import escape_for_applescript, build_applescript_string

def test_escape_backslash():
    assert escape_for_applescript("a\\b") == 'a\\\\b'

def test_escape_double_quote():
    assert escape_for_applescript('a"b') == 'a\\"b'

def test_escape_single_quote():
    assert escape_for_applescript("a'b") == "a\\'b"

def test_escape_tab():
    assert escape_for_applescript("a\tb") == "a\\tb"

def test_escape_carriage_return_removed():
    assert escape_for_applescript("a\rb") == "ab"

def test_build_single_line_string():
    result = build_applescript_string("hello world")
    assert result == '"hello world"'

def test_build_multi_line_string():
    result = build_applescript_string("line1\nline2")
    expected = '"line1" & return & "line2"'
    assert result == expected

def test_build_empty_string():
    result = build_applescript_string("")
    assert result == '""'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && pytest tests/unit/test_apple_script_bridge.py -v`
Expected: FAIL with "module 'mcp_common.apple_script.bridge' has no attribute 'escape_for_applescript'"

- [ ] **Step 3: Add escaping functions to bridge.py**

Add to `mcp-common/mcp_common/apple_script/bridge.py`:

```python
def escape_for_applescript(value: str) -> str:
    """Escape a string for AppleScript following the canonical spec."""
    escaped = value.replace("\\", "\\\\")  # backslash first
    escaped = escaped.replace('"', '\\"')  # double-quote
    escaped = escaped.replace("'", "\\'")  # single-quote
    escaped = escaped.replace("\t", "\\t")  # tab
    escaped = escaped.replace("\r", "")     # carriage return removed
    return escaped

def build_applescript_string(value: str) -> str:
    """Build an AppleScript string literal, handling multi-line via & return &."""
    lines = value.split("\n")
    if len(lines) == 1:
        return f'"{escape_for_applescript(value)}"'
    escaped_lines = [f'"{escape_for_applescript(line)}"' for line in lines]
    return " & return & ".join(escaped_lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && pytest tests/unit/test_apple_script_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/apple_script/bridge.py tests/unit/test_apple_script_bridge.py
git commit -m "feat(apple_script): add canonical multi-line escaping functions

Adopt Swift's & return & approach for multi-line strings as canonical.
This matches the iTerm2 AppleScript protocol spec."
```

---

### Task 3: Update Mahavishnu ITerm2Adapter — Use Canonical Escaping

**Files:**
- Modify: `mahavishnu/terminal/adapters/iterm2.py`
- Create: `tests/unit/test_terminal_adapters_iterm2_escaping.py`
- Reference: `mcp-common/docs/iterm2-applescript-protocol.md`

**Current state:** `iterm2.py` has inline escaping: `command.replace("\\", "\\\\").replace('"', '\\"')`. Single-line only.

- [ ] **Step 1: Write failing test for multi-line command escaping**

```python
# tests/unit/test_terminal_adapters_iterm2_escaping.py
import pytest
from mahavishnu.terminal.adapters.iterm2 import ITerm2Adapter

@pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available")
class TestITerm2AdapterEscaping:
    """Test that ITerm2Adapter uses canonical bridge escaping."""

    def test_send_command_with_newline_uses_multiline_syntax(self):
        """Multi-line commands should use & return & AppleScript syntax."""
        adapter = ITerm2Adapter()
        adapter._sessions["test"] = {
            "command": "echo test",
            "created_at": datetime.now(),
            "window": "win_123",
            "tab": "tab_456",
            "new_window": False,
        }

        captured_script = None
        async def capture_script(script):
            nonlocal captured_script
            captured_script = script
            return ""

        adapter._run_applescript = capture_script

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            adapter.send_command("test", "echo line1\necho line2")
        )

        # Should use & return & for multi-line, not embedded \n
        assert "& return &" in captured_script
        assert "\\n" not in captured_script

    def test_send_command_with_single_quote_escaped(self):
        """Single quotes should be escaped per canonical spec."""
        adapter = ITerm2Adapter()
        adapter._sessions["test"] = {
            "command": "echo test",
            "created_at": datetime.now(),
            "window": "win_123",
            "tab": "tab_456",
            "new_window": False,
        }

        captured_script = None
        async def capture_script(script):
            nonlocal captured_script
            captured_script = script
            return ""

        adapter._run_applescript = capture_script

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            adapter.send_command("test", "echo 'single quote")
        )

        assert "\\'" in captured_script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_terminal_adapters_iterm2_escaping.py -v`
Expected: FAIL — current implementation doesn't use `& return &` for multi-line

- [ ] **Step 3: Update iterm2.py to use bridge escaping**

In `iterm2.py`, add import:

```python
from mcp_common.apple_script import escape_for_applescript, build_applescript_string
```

Update `_run_applescript` caller in `send_command` to use `build_applescript_string`:

```python
escaped_command = build_applescript_string(command)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_terminal_adapters_iterm2_escaping.py -v`
Expected: PASS

- [ ] **Step 5: Run full iterm2 test suite to check for regressions**

Run: `pytest tests/unit/test_terminal_adapters_iterm2.py -v`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/terminal/adapters/iterm2.py tests/unit/test_terminal_adapters_iterm2_escaping.py
git commit -m "fix(iterm2): use canonical multi-line AppleScript escaping

Now uses build_applescript_string() from mcp_common.apple_script
following the iTerm2 AppleScript protocol spec."
```

---

### Task 4: Add Mahavishnu AppleScript Bridge Conformance Tests

**Files:**
- Create: `tests/unit/test_apple_script_bridge_conformance.py`
- Reference: `mcp-common/docs/iterm2-applescript-protocol.md`

**Purpose:** Validate that `mcp_common.apple_script.bridge` correctly implements the canonical spec patterns.

- [ ] **Step 1: Write conformance tests for all spec patterns**

```python
# tests/unit/test_apple_script_bridge_conformance.py
"""
Conformance tests for mcp-common AppleScript bridge against canonical spec.
Tests:
- Escaping algorithm (backslash, quote, tab, CR removal, multiline)
- build_applescript_string for single and multi-line
- run() function with timeout and error handling
"""
import pytest

from mcp_common.apple_script import (
    AppleScriptError,
    ScriptTimeoutError,
    run,
    escape_for_applescript,
    build_applescript_string,
    OSASCRIPT_AVAILABLE,
)

@pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="macOS only")
class TestEscapingConformance:
    """Conformance tests for canonical escaping algorithm."""

    def test_backslash_escaped_first(self):
        """Backslash must be escaped before other characters."""
        result = escape_for_applescript("a\\b")
        assert result == "a\\\\b"
        # Verify quote escaping also works after backslash
        assert escape_for_applescript('a\\"b') == 'a\\\\\\"b'

    def test_double_quote_escaped(self):
        result = escape_for_applescript('hello"world')
        assert result == 'hello\\"world'

    def test_single_quote_escaped(self):
        result = escape_for_applescript("hello'world")
        assert result == "hello\\'world"

    def test_tab_escaped(self):
        result = escape_for_applescript("a\tb")
        assert result == "a\\tb"

    def test_carriage_return_removed(self):
        result = escape_for_applescript("a\r b")
        assert result == "a b"  # CR removed, space remains

    def test_newline_splits_for_multiline(self):
        """Newline triggers & return & multi-line syntax."""
        result = build_applescript_string("line1\nline2\nline3")
        assert result == '"line1" & return & "line2" & return & "line3"'

    def test_single_line_no_multiline_syntax(self):
        result = build_applescript_string("simple")
        assert result == '"simple"'
        assert "return" not in result

    def test_empty_string(self):
        assert build_applescript_string("") == '""'

    def test_tab_in_multiline(self):
        result = build_applescript_string("a\tb\nc")
        assert "\\t" in result

@pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="macOS only")
class TestRunFunctionConformance:
    """Conformance tests for run() function behavior."""

    @pytest.mark.asyncio
    async def test_run_simple_script_returns_output(self):
        result = await run('return "hello"')
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_run_raises_apple_script_error_on_failure(self):
        with pytest.raises(AppleScriptError):
            await run('this is not valid applescript')

    @pytest.mark.asyncio
    async def test_run_raises_timeout_on_hung_script(self):
        # Using a script that would hang indefinitely
        with pytest.raises(ScriptTimeoutError):
            await run('repeat while true\nend repeat', timeout=1.0)

    @pytest.mark.asyncio
    async def test_run_with_special_chars(self):
        result = await run('return "hello \\" world"')
        assert result == 'hello " world'
```

- [ ] **Step 2: Run conformance tests**

Run: `pytest tests/unit/test_apple_script_bridge_conformance.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_apple_script_bridge_conformance.py
git commit -m "test(apple_script): add conformance tests against canonical spec"
```

---

## Phase 3: Swift Side (mdinject) — Separate Implementation

> **Note:** These tasks are for the mdinject repository. Implementation should happen in that repo with reference to this plan.

### Task 5: Migrate Swift ITerm2Session — Int → String ID

**Files:**
- Modify: `mdinject/app/MdInjectApp/AppState.swift:126-132`
- Modify: `mdinject/app/MdInjectApp/State/TerminalState.swift:15-36`

**Current:** `ITerm2Session.id` is `Int` (iTerm2 native session id)
**Target:** `ITerm2Session.id` is `String` in format `"session_{int}"`

Steps:
1. Add computed property `idString: String = "session_\(id)"`
2. Update `sendPromptToITerm2` to use `session id Int(idString.replacingOccurrences(...))`
3. Update `fetchITermSessions` to construct `id: "session_\(sessionId)"`
4. Update all usages of `.id` in SwiftUI views to use new string format
5. Run mdinject test suite to verify

### Task 6: Verify Swift Escaping Matches Spec

**Files:**
- Reference: `mdinject/app/MdInjectApp/AppState.swift:1601-1619`

Swift's existing `appleScriptStringLiteral(_:)` already implements:
- [x] Backslash → `\\`
- [x] Double-quote → `\"`
- [x] Single-quote → `\'`
- [x] Tab → `\t`
- [x] Parentheses → `\(` `\)`
- [x] Multi-line via `& return &`

Verify no changes needed — this already matches the canonical spec.

### Task 7: Add Swift AppleScript Bridge Conformance Tests

**Files:**
- Create: `mdinject/Tests/AppTests/AppleScriptBridgeConformanceTests.swift`

Add Swift XCTest suite that validates:
- Escaping algorithm matches spec
- Multi-line string building matches spec
- `runAppleScript` error handling matches spec

---

## Phase 4: Integration Verification

### Task 8: Cross-Repo Session ID Compatibility Test

**Files:**
- Create: `tests/integration/test_iterm2_session_compatibility.py` (Mahavishnu)

Purpose: Validate that when a session ID is formatted in Mahavishnu's `session_{windowId}_{tabIdOrWin}` format, mdinject can parse and use it, and vice versa.

---

## File Structure Summary

```
mcp-common/
├── docs/
│   └── iterm2-applescript-protocol.md    ← canonical spec
├── mcp_common/apple_script/
│   ├── __init__.py                        ← exports escape/build/run
│   ├── bridge.py                          ← add canonical escaping
│   └── exceptions.py
└── tests/unit/
    ├── test_apple_script_bridge.py        ← escaping unit tests
    └── test_apple_script_bridge_conformance.py  ← spec conformance

mahavishnu/
├── terminal/adapters/
│   └── iterm2.py                          ← use build_applescript_string
└── tests/unit/
    ├── test_terminal_adapters_iterm2_escaping.py  ← multi-line tests
    └── test_apple_script_bridge_conformance.py

mdinject/ (separate implementation)
├── app/MdInjectApp/AppState.swift         ← String session IDs
├── app/MdInjectApp/State/TerminalState.swift ← String session IDs
└── Tests/AppTests/AppleScriptBridgeConformanceTests.swift
```

---

## Execution Options

**1. Subagent-Driven (recommended)** — I dispatch fresh subagent per task, two-stage review between tasks

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
