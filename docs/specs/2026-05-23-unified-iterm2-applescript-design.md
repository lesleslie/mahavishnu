---
status: draft
role: implementation
topic: terminal
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Unified iTerm2 AppleScript Integration — Design Spec

## **Date:** 2026-05-23 **Status:** Draft for review <!-- legacy status: Draft for review — see YAML frontmatter --> **Goal:** Unify AppleScript/iTerm2 integration across mdinject (Swift) and Mahavishnu (Python) for shared session identity schema, compatible string escaping, and common AppleScript patterns.

## 1. Problem Statement

Two Bodai ecosystem repos independently implement iTerm2 control via AppleScript:

| Repo | Language | Execution | Session ID | String Escaper |
|------|----------|-----------|------------|----------------|
| **mdinject** | Swift | `NSAppleScript` (native) | `Int` (iTerm2 session id) | `\"` `\\` `\'` `\t` `\(` `\)` + multiline `& return &` |
| **Mahavishnu** | Python | `asyncio subprocess exec("osascript")` | `str` (UUID[:8]) + window_id/tab_id | `\"` `\\` only, single-line |

**Problems:**

- Duplicated AppleScript logic across languages
- Incompatible session identity schemas (can't cross-reference sessions)
- Inconsistent string escaping (Swift handles more metacharacters)
- No shared specification of canonical AppleScript patterns
- Long-term maintenance burden: changes to iTerm2 API must be made in two places

______________________________________________________________________

## 2. What to Unify

Not everything needs to be shared. Clarify scope:

### 2.1 Session Identity Schema (UNIFY)

A canonical session identifier both Swift and Python can use:

```swift
// Swift proposed (compatible with string-based approach)
struct ITerm2Session: Identifiable, Hashable {
    let id: String          // canonical: string "session_{int}"
    let windowId: String    // iTerm2 unique id (string)
    let tabId: String?      // nil if window-level (no tab)
    let name: String?
    let currentDirectory: String?
    let windowIndex: Int   // for display/human reference only
    let tabIndex: Int
}
```

```python
# Python already close — just need to formalize
@dataclass
class ITerm2Session:
    session_id: str         # "grid_abc123" — UUID[:8] or "session_{int}"
    window_id: str          # iTerm2 unique id (string)
    tab_id: str | None
    name: str | None
    current_directory: str | None
```

**Key decision:** Session IDs become `String` in both implementations. Swift currently uses `Int`. Need to decide: does Swift migrate to string session IDs, or does Python wrap Swift's int-based IDs in a string adapter?

### 2.2 String Escaping (UNIFY)

A canonical escaping algorithm both languages implement:

**Rules:**

1. Backslash `\` → `\\` (escape first, always)
1. Double-quote `"` → `\"`
1. Single-quote `'` → `\'` (AppleScript standard)
1. Tab `\t` → `\t`
1. Carriage return `\r` → removed (not valid in AppleScript strings)
1. Newline `\n` → expressed as `" & return & "` for multi-line strings

**Multi-line handling:** When a string contains multiple lines, Swift joins them as:

```
"line1" & return & "line2" & return & "line3"
```

Python's current implementation doesn't handle multi-line. We need to decide: does Python adopt Swift's multi-line approach, or does Swift switch to Python's single-line-with-embedded-newlines approach?

**Recommendation:** Adopt Swift's multi-line `& return &` approach as canonical — it's the AppleScript-idiomatic way and Swift has been production-tested with it.

### 2.3 AppleScript Patterns (UNIFY as SPEC only)

Canonical AppleScript scripts for:

- Enumerate sessions (window/tab/session info)
- Send text to session
- Create window with profile
- Close session/window
- Get/Set window bounds

Both languages implement these patterns from a shared spec document, but execute differently (native vs subprocess).

### 2.4 What Stays Language-Specific

- **Execution model**: Swift uses `NSAppleScript`, Python uses `osascript` subprocess. These are fundamentally different and can't be shared without complex IPC.
- **Session lifecycle**: mdinject manages iTerm2 sessions for interactive use; Mahavishnu's TerminalGridManager orchestrates grid deployments. Different use cases, different lifecycle management.
- **Grid orchestration**: Mahavishnu's `TerminalGridManager` with quadrant layout and multi-desktop is unique to Mahavishnu.

______________________________________________________________________

## 3. Approaches

### Approach A: MCP Protocol Bridge

Swift calls Python's AppleScript bridge over a local Unix domain socket MCP connection. Python owns the bridge; Swift is a client.

```
┌─────────────┐          Unix Socket MCP          ┌─────────────────┐
│  mdinject   │ ──────── (JSON-RPC over UDS) ─────▶ │ mcp-common      │
│  (Swift)    │ ◀──────── (response) ────────────── │ apple_script     │
│             │                                    │ (Python)        │
└─────────────┘                                    └─────────────────┘
```

**Session identity:** Python owns the session ID format. Swift translates between iTerm2's native `Int` IDs and Python's string format.

**String escaping:** Python handles all escaping. Swift sends raw text to Python bridge.

**Unified spec file:** `mcp-common/apple_script/spec/iterm2-applescript-spec.md`

**Pros:**

- Single implementation of AppleScript execution (Python)
- Swift gets AppleScript for free, no native implementation
- Schema enforcement from one place
- Can add more clients (if other languages need iTerm2)

**Cons:**

- **Dependency**: Swift now depends on Python running. If Python process dies, iTerm2 control breaks.
- **Latency**: Every AppleScript call is a socket round-trip. Fine for interactive use; potentially problematic for high-frequency operations.
- **Deployment complexity**: Two processes must be running. More complex startup.
- **你不是真正的统一**: Swift is still doing its own session tracking internally, just translating to Python's format. Not true schema alignment.

______________________________________________________________________

### Approach B: Shared Swift Package + Native Implementations

Create a Swift `AppleScriptBridge` package with the same interface contract as Python's `mcp_common.apple_script`. Both implement to a shared spec, but each in their native execution model.

```
┌──────────────────────┐         ┌──────────────────────┐
│      mdinject        │         │      Mahavishnu       │
│       (Swift)        │         │       (Python)        │
│                      │         │                      │
│ ┌──────────────────┐ │         │ ┌──────────────────┐  │
│ │ AppleScriptBridge│ │         │ │ mcp_common.apple │  │
│ │ (Swift package)  │ │         │ │ _script.bridge   │  │
│ └────────┬─────────┘ │         │ └────────┬─────────┘  │
│          │           │         │          │            │
└──────────┼───────────┘         └──────────┼───────────┘
          │                             │
          ▼                             ▼
   ┌─────────────────────────────────────────┐
   │  iterm2-applescript-protocol.md (shared) │
   │  - Session schema (canonical)            │
   │  - Escaping rules                        │
   │  - AppleScript pattern templates         │
   └─────────────────────────────────────────┘
```

**Session identity:** Both use `String`-based IDs. Swift migrates from `Int` to `String`.

**String escaping:** Both implement from spec — Swift's existing implementation already handles all cases correctly.

**AppleScript patterns:** Both execute from canonical templates in the spec doc.

**Pros:**

- True dual-maintenance: both languages implement the same spec
- No runtime dependency between Swift and Python
- Native execution in both (no IPC overhead)
- Schema alignment through spec document

**Cons:**

- **Duplicated implementation**: AppleScript logic exists in two languages. Changes to patterns require updates in both.
- **Migration required**: Swift must migrate from `Int` session IDs to `String`. mdinject has production iTerm2 sessions — migration path needed.
- **No single source of truth**: The spec doc could drift from implementations.

______________________________________________________________________

### Approach C: Specification-First with Native Implementations (Recommended)

Define a canonical `ITerm2Protocol` specification that both languages implement independently. The spec is the source of truth; implementations must pass conformance tests.

```
┌─────────────────────────────────────────────────────────────────┐
│           iterm2-applescript-protocol.md                        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   mdinject   │  │  Mahavishnu  │  │  (future)    │          │
│  │    Swift     │  │    Python    │  │  other repo  │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                   │
│         ▼                 ▼                 ▼                   │
│   Conformance      Conformance        Conformance              │
│   Tests (Swift)   Tests (Python)    Tests (lang)             │
└─────────────────────────────────────────────────────────────────┘
```

**Key additions over Approach B:**

- **Conformance test suite**: Each language has a test suite that validates its implementation against the spec. Tests are in each repo, runnable against the local implementation.
- **Shared spec in mcp-common**: The spec lives in `mcp-common/docs/iterm2-applescript-protocol.md`. Both Swift and Python reference it.
- **Canonical session schema in spec**: All languages implement the same `ITerm2Session` schema with `String` IDs.

**Session identity:** Migrate Swift to `String` IDs using format `"session_{iTerm2IntId}"`. Python uses existing `UUID[:8]` format for internal sessions, exposes `session_{iTerm2Id}` for cross-repo communication.

**String escaping:** Swift's existing implementation is canonical — it's more complete than Python's. Update Python to match Swift's multi-line handling.

**AppleScript patterns:** Single canonical template per operation in the spec. Both implement the same pattern.

**Pros:**

- True schema alignment with conformance testing
- No runtime dependency between languages
- Native execution (no IPC overhead)
- Spec document serves as single source of truth
- Extensible: future languages can implement to spec

**Cons:**

- **Migration work**: Swift must migrate `Int` → `String` session IDs
- **Duplicated implementation**: AppleScript logic in two languages, but this is acceptable — they're different execution models
- **Migration of Python escaping**: Python's single-line-only escaping needs to be updated to handle multi-line via `& return &`

______________________________________________________________________

## 4. Session Identity Migration Plan

### Swift: `Int` → `String`

Current: `ITerm2Session(id: Int, ...)` where `id` is iTerm2's native session integer.

Target: `ITerm2Session(id: String, ...)` where `id` is `"session_{int}"`.

Migration path:

1. Add `idString: String` computed property: `return "session_\(id)"`
1. Update all internal usages to prefer `idString`
1. Once all Swift code uses `idString`, rename `idString` → `id` and deprecate old `Int`-based approach
1. In bridging layer (if needed), translate between `"session_123"` and `123` for iTerm2 calls

### Python: UUID[:8] → String

Current: Python generates `UUID[:8]` as internal session ID. iTerm2 window/tab IDs are already strings.

Target: For cross-repo compatibility, Python exposes `session_{windowId}_{tabId or "win"}` format when communicating with Swift.

This doesn't require Python to change its internal format — just the translation layer when talking to Swift.

______________________________________________________________________

## 5. Escaping Rules (Canonical)

```python
# Canonical escaping algorithm (Python version)
def escape_for_applescript(value: str) -> str:
    """Escape a string for AppleScript, handling multi-line correctly."""
    # 1. Backslash first (before everything else)
    escaped = value.replace("\\", "\\\\")
    # 2. Double-quote
    escaped = escaped.replace('"', '\\"')
    # 3. Single-quote (AppleScript standard)
    escaped = escaped.replace("'", "\\'")
    # 4. Tab
    escaped = escaped.replace("\t", "\\t")
    # 5. Carriage return (remove, not valid in AppleScript strings)
    escaped = escaped.replace("\r", "")
    # 6. Newline: handled at call site (multi-line with & return &)
    return escaped

def build_applescript_string(value: str) -> str:
    """Build an AppleScript string literal, handling multi-line."""
    lines = value.split("\n")
    if len(lines) == 1:
        return f'"{escape_for_applescript(value)}"'
    # Multi-line: "line1" & return & "line2" & return & "line3"
    escaped_lines = [f'"{escape_for_applescript(line)}"' for line in lines]
    return " & return & ".join(escaped_lines)
```

Swift already implements this correctly. Python needs to adopt the multi-line handling.

______________________________________________________________________

## 6. AppleScript Pattern Templates

### 6.1 Enumerate Sessions

```applescript
-- Canonical template
tell application "iTerm2"
    if it is running then
        set output to {}
        repeat with w in windows
            set wIndex to index of w
            repeat with t in tabs of w
                set tIndex to index of t
                repeat with s in sessions of t
                    set sId to id of s
                    set sName to name of s
                    set sCwd to ""
                    try
                        set sCwd to current directory of s
                    end try
                    set end of output to {wIndex, tIndex, sId, sName, sCwd}
                end repeat
            end repeat
        end repeat
        return output
    else
        return {}
    end if
end tell
```

### 6.2 Send Text to Session

```applescript
tell application "iTerm2"
    tell session id {session_id}
        write text {escaped_text}
    end tell
end tell
```

### 6.3 Create Window with Profile

```applescript
tell application "iTerm2"
    activate
    set newWindow to (create window with profile {profile_name})
    set windowID to unique id of newWindow
    tell newWindow
        tell current session
            write text {escaped_command}
        end tell
    end tell
    return windowID
end tell
```

______________________________________________________________________

## 7. Canonical Session Schema

```yaml
ITerm2Session:
  id: string           # "session_{iTerm2IntId}" — canonical across repos
  window_id: string     # iTerm2 unique window id
  tab_id: string | null # null if window-level session
  name: string | null
  current_directory: string | null
  window_index: int    # display/human reference only
  tab_index: int       # display/human reference only
```

______________________________________________________________________

## 8. Approach Comparison

| Criterion | A: MCP Bridge | B: Shared Package | C: Spec-First (Recommended) |
|-----------|---------------|-------------------|------------------------------|
| **Session ID schema unified** | ✅ (via Python) | ✅ | ✅ |
| **String escaping unified** | ✅ (via Python) | ✅ | ✅ |
| **No runtime dependency** | ❌ | ✅ | ✅ |
| **Native execution** | ❌ (IPC overhead) | ✅ | ✅ |
| **True dual-maintenance** | ❌ | ✅ | ✅ |
| **Conformance testing** | N/A | ❌ | ✅ |
| **Extensible to other languages** | ✅ | ❌ (no pkg) | ✅ |
| **Migration complexity** | Medium | Medium | Medium |
| **Long-term maintenance** | Single point of failure | Duplicated | ✅ Both |

______________________________________________________________________

## 9. Recommendation

**Approach C (Spec-First with Native Implementations)** is recommended because:

1. **No runtime dependency**: Swift and Python each run independently
1. **True schema alignment**: Both implement the same session schema
1. **Conformance testing**: Each implementation validates against the spec
1. **Extensible**: Future Bodai ecosystem repos can implement to spec
1. **Native performance**: No IPC overhead for AppleScript calls

**Migration steps:**

1. Write canonical spec doc to `mcp-common/docs/iterm2-applescript-protocol.md`
1. Update Python's escaping to handle multi-line (adopt Swift's `& return &` approach)
1. Swift migrates `Int` session IDs → `String` format `session_{int}`
1. Create conformance tests in both repos
1. Update bridging layer if Swift/Python need to communicate directly

______________________________________________________________________

## 10. Open Questions

1. **Should Python adopt Swift's multi-line `& return &` approach, or should Swift adopt Python's single-line approach?** Recommendation: Swift's approach is more AppleScript-idiomatic and has been production-tested.

1. **How do Swift and Python session IDs translate when they need to communicate?**

   - Option A: Swift converts `Int` → `"session_{int}"` when sending to Python
   - Option B: Each keeps its own format; translation happens at the boundary
   - Recommendation: Use canonical `"session_{int}"` format for cross-repo communication.

1. **Should mdinject's Python layer (terminal_pane_service.py) also use the shared bridge?**

   - Currently mdinject's Python has no iTerm2 support. If it needed to add some, it should use `mcp_common.apple_script`.

1. **Where does the spec live?**

   - `mcp-common/docs/iterm2-applescript-protocol.md` — since mcp-common is already the shared infrastructure package.

______________________________________________________________________

## 11. Out of Scope

- Grid orchestration (Mahavishnu-specific)
- PTY terminal management (mdinject Python layer — different paradigm)
- Terminal.app support (iTerm2 only)
- Non-AppleScript iTerm2 control (Python API, etc.)
