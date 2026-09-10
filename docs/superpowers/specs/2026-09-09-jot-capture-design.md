# Jot Inbox: Capture Sub-Plan Design

> **Sub-plan 1 of 3.** This spec covers only the **capture** layer (write path).
> The read surface (MCP tools, CLI, fold, render) lives in sub-plan 2.
> The drain (Dhara replication) lives in sub-plan 3.
> See [`2026-09-09-jot-inbox-design.md`](2026-09-09-jot-inbox-design.md) for the union.

**Goal:** A `,,`-prefixed prompt becomes a local jot. Captures cannot fail.

**Architecture:** A UserPromptSubmit hook (stdlib-only Python) detects the `,,` prefix, writes a JSONL event to `~/.mahavishnu/jot/log.jsonl`, and exits 2 to erase the prompt from Claude's transcript. Mahavishnu owns the install (`mahavishnu jot install-hook` in sub-plan 2).

**Tech Stack:** Python 3.12+ stdlib only. No `logging`, no `oneiric`, no Mahavishnu runtime imports inside the hook. Reuses Mahavishnu's `from __future__ import annotations` + bandit B101 conventions.

---

## Decisions (this sub-plan)

### D1. Hook delivery
**Decision:** Mahavishnu plugin install. Hook file `mahavishnu/hooks/jot_capture.py` ships with the package. `mahavishnu jot install-hook` (sub-plan 2's CLI) copies it to `~/.claude/hooks/jot_capture.py` and writes a `UserPromptSubmit` entry in `~/.claude/settings.json`.
**Why:** Simpler than standalone vendoring. Users who use jot already have Mahavishnu installed. Captures do not need to work without Mahavishnu — the "capture cannot fail" goal is met by the hook being fail-open, not by decoupling from Mahavishnu.
**Rejected:** (a) Standalone vendored script — adds dual codec maintenance for an edge case. (b) Both standalone + Mahavishnu-managed — extra work, extra test surface.

### D2. Redaction scope (capture-time)
**Decision:** Moderate. ~20 regex patterns across 3 tiers — secrets (AWS, GitHub PATs, OpenAI/Anthropic, Slack tokens, JWTs, Bearer tokens, high-entropy strings), credentials (emails, US phone numbers, IPv4 addresses), URLs + env-style (HTTP(S) URLs, `.env` references, SSH private key headers).
**Why:** Defensive against accidental secret leakage without excessive false positives. Capture-time redaction is the *first* line; drain-time redaction (sub-plan 3) is the second line using the full Session-Buddy redaction.
**Rejected:** (a) Minimal — too narrow, real leaks slip through. (b) Aggressive opt-in — annoying false positives for the common case.

### D3. Ambient context (capture-time)
**Decision:** Cheap sources only at write-time. Capture: `cwd`, `session_id`, `files` (from Claude stdin), `env_repo` + `env_branch` (from env vars). Defer git context (`repo`, `branch`, `sha`) to read-time (sub-plan 2's fold enriches via `git rev-parse` when needed).
**Why:** Subprocess git calls add 50-200ms per prompt. The hook must cost nothing. Read-time git is paid only when the user actually lists/shows jots, not on every prompt.
**Rejected:** (a) Always git — conflicts with the "capture costs nothing" goal. (b) Cached git — extra file, more complexity, marginal benefit.

### D4. Failure logging
**Decision:** Always-on debug file at `~/.mahavishnu/jot/errors.log`, mode `0o600`. Hook writes structured error records on every captured exception. Sub-plan 2's read surface shows error count + last error message.
**Why:** Failures must be debuggable without explicit opt-in. A user who notices "my jots stopped being captured" needs a way to find out why.
**Rejected:** (a) Opt-in via env var — fails silently when the env isn't set, which is when you most need the log. (b) No logging — debugging is impossible.

---

## Locked Decisions (from the union spec, inherited)

These are *not* sub-plan-1 decisions but are referenced by this sub-plan and remain unchanged:

- **UD1.** `,,` prefix triggers capture (exit 2). Empty body or no `,,` is passthrough.
- **UD2.** Terminal state is `done` (jots are tasks; explicit `done` operation marks completion).
- **UD3.** Append-only JSONL log, one event per line, `\n` line terminator.
- **UD4.** Hybrid Logical Clock `(wall_ms, ctr, node)` replaces wall-clock ordering for capture events.
- **UD5.** 32-hex UUID v4 for event IDs; 6-hex `short_id` is just the first 6 chars (echo only).
- **UD6.** Log file mode `0o600`, dir mode `0o700`.
- **UD7.** No `assert` in `mahavishnu/jot/**` (bandit B101 enforced globally).
- **UD8.** `from __future__ import annotations` first non-comment line of every source file.
- **UD9.** Mypy strict (Python 3.14 target), Ruff line-length 100, function args ≤ 10.

---

## Goals (this sub-plan)

1. **Capture costs nothing** — hook overhead < 10ms per prompt on the success path.
2. **Capture cannot fail** — every failure mode is detected, logged, and converted to passthrough (exit 0).
3. **No organization required at capture time** — the user just types `,, <text>`.
4. **Stdlib-only hook** — the hook script runs without importing Mahavishnu runtime; the only `mahavishnu/*` modules it loads are the `mahavishnu/jot/*` modules, which are themselves stdlib-only.

## Non-goals (deferred)

- ❌ Reading jots (sub-plan 2: fold, render, list, show, done, reopen)
- ❌ MCP tools (sub-plan 2: 8 tools, profile registration)
- ❌ CLI (sub-plan 2: `mahavishnu jot ...` subcommands including `install-hook`)
- ❌ Drain to Dhara (sub-plan 3: replication, offset bookkeeping, integrity guard)
- ❌ `/jot` slash command (sub-plan 2)
- ❌ `,j` (capture via Claude Code slash command) — out of scope entirely
- ❌ `redact` operation — v1 only writes redacted text; no edit-redaction in place
- ❌ Cross-machine sync — local-only; replication is sub-plan 3

---

## Architecture

```
Claude Code (terminal)
   │
   │ stdin: JSON {prompt, session_id, files, ...}
   ↓
~/.claude/hooks/jot_capture.py   ← installed by sub-plan 2's CLI
   │
   │ detects ",," prefix (after leading-whitespace strip)
   │ strips body, redacts, builds event
   ↓
~/.mahavishnu/jot/log.jsonl       ← append-only, 0o600
   │
   │ stderr: "jot a3f9c2 captured (3 words, 24 chars)"
   │ exit 2 → prompt erased
   ↓
(sub-plan 2: fold reads log)
(sub-plan 3: drain reads log → Dhara)
```

**Layer boundaries:**

| Layer | Sub-plan | Owns |
|---|---|---|
| Hook invocation | 1 | Read stdin, detect `,,`, exit codes, echo to stderr |
| Codec + validation | 1 | HLC generation, short_id, redact, ctx assembly |
| Persistent log | 1 | Append-only write, atomicity, dir/file permissions |
| Failure logging | 1 | errors.log writes, rotation, ctx sanitization |
| Fold (read foundation) | 2 | Two-pass HLC-ordered fold, parking, HLC tail read |
| Render | 2 | Vitals, list, show, echo formatting |
| MCP tools + CLI | 2 | 8 tools, `mahavishnu jot ...`, `install-hook` |
| Drain | 3 | Replication to Dhara, offset bookkeeping, integrity |

---

## Data Model

### `JotEvent` dataclass

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class HLC:
    """Hybrid Logical Clock. Monotonic per-node, comparable across nodes via ctr tiebreaker."""
    wall_ms: int      # Unix epoch milliseconds
    ctr: int          # Counter to break ties within same wall_ms
    node: str         # 8-hex-char local node identifier (host shortname + 4-hex random)


@dataclass(frozen=True)
class JotEvent:
    id: str                    # 32-hex-char UUID v4
    op: Literal["capture", "edit", "done", "reopen"]  # v1: only "capture"
    hlc: HLC
    text: str                  # Jot body, post-redaction
    ctx: dict[str, Any]        # Ambient context (see schema below)
    created_ms: int            # Unix ms when hook fired (for human display)
```

**Op enum (v1):** Only `"capture"` is written by the hook in sub-plan 1. Other ops are written by sub-plan 2 (edit/done/reopen). The dataclass reserves them now so the codec doesn't change between sub-plans.

### Capture-time ambient context (`ctx` keys)

| Key | Type | Source | Example |
|---|---|---|---|
| `cwd` | `str` | `os.getcwd()` | `"/Users/les/Projects/mahavishnu"` |
| `session_id` | `str` | Claude Code stdin | `"sess_abc123"` |
| `files` | `list[str]` | Claude Code stdin (modified files) | `["src/x.py", "tests/test_x.py"]` |
| `env_repo` | `str \| None` | `$MAHAVISHNU_REPO` | `"/Users/les/Projects/mahavishnu"` |
| `env_branch` | `str \| None` | `$MAHAVISHNU_BRANCH` | `"main"` |

**Deferred to sub-plan 2 (read-time enrichment):**

| Key | Type | Source | Note |
|---|---|---|---|
| `repo` | `str` | `git rev-parse --show-toplevel` | Subprocess at fold time |
| `branch` | `str` | `git rev-parse --abbrev-ref HEAD` | Subprocess at fold time |
| `sha` | `str` | `git rev-parse HEAD` | Subprocess at fold time |

### Wire format (JSONL)

One event per line. Compact JSON (no indent). Line terminator `\n` (LF, not CRLF).

```json
{"id":"a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d","op":"capture","hlc":{"wall_ms":1757452800123,"ctr":0,"node":"mac01a3f9"},"text":"refactor jot fold to use HLC ordering","ctx":{"cwd":"/Users/les/Projects/mahavishnu","session_id":"sess_xyz","files":["mahavishnu/jot/fold.py"],"env_repo":"/Users/les/Projects/mahavishnu","env_branch":"main"},"created_ms":1757452800123}
```

**Round-trip invariant:** `deserialize(serialize(e)) == e` for all valid events (codec property test).

### HLC generation

```python
def hlc_now(node: str, last: HLC | None) -> HLC:
    """Generate next HLC. Monotonic within a node."""
    wall_ms = int(time.time() * 1000)
    if last is None or wall_ms > last.wall_ms:
        ctr = 0
    else:
        ctr = last.ctr + 1
    return HLC(wall_ms=wall_ms, ctr=ctr, node=node)
```

**`node` initialization:** `~/.mahavishnu/jot/node` is read at module import. If the file doesn't exist, generate `f"{hostname_short[:4]}{secrets.token_hex(2)}"` (8 hex chars total) and write it. Failures during node init are logged to errors.log; the hook proceeds with an in-memory random node (no persistence) — drift in that session only.

**HLC continuity across captures:**
- Open log in read mode, seek to `max(0, file_size - 65536)`, read to EOF
- Parse last complete JSON line → extract `hlc`
- If parse fails or log doesn't exist, treat as `None`
- This guarantees monotonic HLCs within a node even across crashes and restarts

### Short ID (echo only)

```python
def short_id(event_id: str) -> str:
    """First 6 hex chars of UUID v4. ~3% collision at 1000 jots."""
    return event_id[:6]
```

Used only in the capture echo. Real IDs (32 hex) are stored in the log. Collision in the echo is acceptable because the echo is human-facing; real IDs are what matter for the log.

---

## Capture Surface (Hook Contract)

### Claude Code UserPromptSubmit contract

**Input (stdin):** JSON object with at minimum:
- `prompt: str` — the user's prompt text
- `session_id: str` — Claude Code session identifier
- `files: list[str]` (optional) — modified files

**Output (stdout):**
- **Passthrough:** original JSON unchanged
- **Capture:** empty (exit 2 erases the prompt)

**Output (stderr):** capture echo (visible in foreground TUI, lost in non-TTY)

**Exit codes:**
- `0` — passthrough (prompt proceeds normally)
- `2` — capture (prompt erased, event written)

### Pattern detection

```python
def is_capture(prompt: str) -> tuple[bool, str]:
    """Returns (is_capture, body).
    is_capture=True iff prompt starts with ",," after stripping leading whitespace.
    body is the text after the ",," prefix, also lstripped.
    Empty body after stripping → not a capture (passthrough).
    """
    stripped = prompt.lstrip()
    if not stripped.startswith(",,"):
        return False, ""
    body = stripped[2:].lstrip()
    if not body:
        return False, ""
    return True, body
```

Edge cases:
- `" ,,"` (space before comma-comma) → capture (leading whitespace stripped)
- `",, "` (trailing whitespace after prefix) → capture, empty body after lstrip → NO, passthrough (empty body check)
- `"text ,, more text"` → NOT a capture (no leading `,,`)
- `" ,,"` followed by text → capture
- Just `",,"` with nothing → passthrough

### Capture echo (to stderr)

Format: `jot <short_id> captured (<word_count> words, <char_count> chars)`

Example: `jot a3f9c2 captured (3 words, 24 chars)`

Single line. `print(..., file=sys.stderr)` adds the trailing newline.

**Why stderr not stdout:** Claude Code reads stdout to determine passthrough vs block. We want exit 2 + empty stdout to erase the prompt. Stderr is the only user-visible feedback channel that doesn't break the hook contract.

### Capture flow (happy path)

```
1. Read stdin → parse JSON
2. Extract prompt, session_id
3. is_capture, body = is_capture(prompt)
4. If not is_capture:
     → print original JSON to stdout, sys.exit(0)
5. id = uuid.uuid4().hex
6. last_hlc = read_tail_hlc() or None
7. hlc = hlc_now(node, last_hlc)
8. ctx = build_capture_ctx(stdin, env)
9. text = redact_text(body)
10. event = JotEvent(id, "capture", hlc, text, ctx, created_ms=int(time.time()*1000))
11. line = json.dumps(asdict(event), separators=(",", ":")) + "\n"
12. fd = os.open(log_path, O_WRONLY | O_APPEND | O_CREAT, 0o600)
13. os.write(fd, line.encode("utf-8"))
14. os.close(fd)
15. print(f"jot {short_id(id)} captured ({wc} words, {cc} chars)", file=sys.stderr)
16. sys.exit(2)
```

### Hook delivery

**File shipped in Mahavishnu package:** `mahavishnu/hooks/jot_capture.py`

**Installed by sub-plan 2's CLI:** `~/.claude/hooks/jot_capture.py` (copy of the package file)

**`~/.claude/settings.json` entry** (written by sub-plan 2's `mahavishnu jot install-hook`):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/jot_capture.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The hook script is *not* executable; invoked via `python3` explicitly. This avoids shebang issues and works regardless of where Python is installed.

---

## Redaction

### Scope (moderate, ~20 patterns across 3 tiers)

**Tier 1 — Secrets (always redact):**
- AWS access keys: `AKIA[0-9A-Z]{16}`
- GitHub PATs: `ghp_[a-zA-Z0-9]{36}`, `gho_[a-zA-Z0-9]{36}`, `ghu_[a-zA-Z0-9]{36}`, `ghs_[a-zA-Z0-9]{36}`, `ghr_[a-zA-Z0-9]{36}`
- OpenAI/Anthropic keys: `sk-[a-zA-Z0-9]{20,}`, `sk-ant-[a-zA-Z0-9-]{20,}`
- Slack tokens: `xox[baprs]-[a-zA-Z0-9-]{10,}`
- JWTs: `eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+`
- Bearer tokens: `Bearer\s+[a-zA-Z0-9_.-]+`
- Generic high-entropy strings (32+ chars): heuristic with entropy threshold

**Tier 2 — Credentials:**
- Email addresses: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- Phone numbers (US): `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b`
- IP addresses (IPv4): `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`

**Tier 3 — URLs + env-style:**
- HTTP(S) URLs: `https?://[^\s]+`
- `.env`-style references: `\.env(\.\w+)?` in path context
- SSH private key headers: `-----BEGIN [A-Z ]+PRIVATE KEY-----`

**Replacement format:** `[REDACTED:<tier>:<hash>]` where `<hash>` is the first 8 hex chars of `sha256(match.encode()).hexdigest()`. The hash allows:
- Detecting that two redactions were of the same secret (correlation)
- NOT reversing the redaction (one-way)

Example: `aws_key=AKIAIOSFODNN7EXAMPLE` → `aws_key=[REDACTED:secret:a3f9c2b1]`

### Implementation

```python
def redact_text(text: str) -> str:
    """Apply all redaction patterns to text. Returns redacted text."""
    out = text
    for pattern, tier in PATTERNS:
        out = pattern.sub(lambda m: _redact_match(m, tier), out)
    return out
```

Patterns are compiled once at module import (not per-call). Single pass per pattern (no overlap detection — first match wins).

### False positive handling

- IP `10.0.0.1` in version numbers gets redacted — acceptable trade-off (user can re-type with spaces)
- Emails in commit hashes (`abc123@def456`) are unlikely to match (no `.`)
- `.env` reference in `python -c "import os"` matches because of regex context — acceptable

**No false-positive suppression** in v1. If users complain, add an `allowlist` env var in v2.

---

## Permissions

### Directory & files

| Path | Mode | Created by |
|---|---|---|
| `~/.mahavishnu/` | `0o700` | Mahavishnu (pre-existing) |
| `~/.mahavishnu/jot/` | `0o700` | Sub-plan 1: hook on first capture |
| `~/.mahavishnu/jot/log.jsonl` | `0o600` | Sub-plan 1: hook on first capture |
| `~/.mahavishnu/jot/errors.log` | `0o600` | Sub-plan 1: hook on first failure |
| `~/.mahavishnu/jot/node` | `0o600` | Sub-plan 1: hook on first capture |

### Atomicity

**Single-syscall writes:** Every log write is one `os.write()` call. The kernel guarantees that writes ≤ `PIPE_BUF` (4096 bytes on Linux/macOS) are atomic. Event lines are bounded to < 4 KB (a 1000-char jot body is ~1.5 KB serialized).

**No fsync:** We do not call `fsync()` after write. A power loss between write and fsync could lose the last jot — acceptable trade-off (jots are quick-capture; users can re-type).

**No rotation:** The log grows without bound in v1. Sub-plan 2 may add rotation. A single user captures maybe 5-50 jots/day → log grows ~50 KB/day → 18 MB/year. Manageable.

### File descriptor hygiene

```python
fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
try:
    os.write(fd, line.encode("utf-8"))
finally:
    os.close(fd)
```

Always close. `try/finally` is acceptable for resource cleanup (bandit B101 forbids `assert`, not `try/finally`).

---

## Failure Modes

### The cardinal rule

**A failure NEVER blocks the prompt.** The user typed something; if capture breaks, the prompt proceeds. `,,` becomes `,, text` to Claude, which is mildly confusing but not destructive.

### Failure taxonomy

| Failure | Detection | Behavior | Logged to errors.log? |
|---|---|---|---|
| Stdin is not valid JSON | `json.JSONDecodeError` on parse | Passthrough, exit 0 | yes |
| `prompt` field missing | `KeyError` | Passthrough, exit 0 | no |
| Empty prompt | `not prompt` | Passthrough, exit 0 | no |
| `,,` with empty body (after lstrip) | `is_capture` returns False | Passthrough, exit 0 | no |
| Permission denied on `~/.mahavishnu/jot/` mkdir | `PermissionError` | Passthrough, exit 0 | yes |
| Permission denied on log open | `PermissionError` | Passthrough, exit 0 | yes |
| Disk full on write | `OSError` | Passthrough, exit 0 | yes |
| Log doesn't exist (read_tail_hlc) | `FileNotFoundError` | Treat as no last HLC | no |
| Last line of log is malformed JSON | `json.JSONDecodeError` | Treat as no last HLC | no |
| Node file write fails | `OSError` | Generate in-memory; don't write | yes |
| Unexpected exception | `Exception` (bare except at top) | Passthrough, exit 0 | yes |

### Top-level error handler

```python
def main() -> int:
    try:
        return _do_hook()
    except BaseException as exc:  # noqa: BLE001 - top-level safety net
        log_error("capture", exc, ctx={"cwd": safe_cwd(), "prompt_prefix": safe_prefix()})
        return 0  # passthrough


if __name__ == "__main__":
    sys.exit(main())
```

`BaseException` (not `Exception`) to catch `KeyboardInterrupt` and `SystemExit` from runaway subprocesses — also passthrough safely.

### Errors log format

`~/.mahavishnu/jot/errors.log`, mode `0o600`, append-only JSONL.

```json
{"ts_ms":1757452800123,"hook":"jot_capture","op":"capture","err":"PermissionError: [Errno 13] Permission denied: '/Users/les/.mahavishnu/jot/log.jsonl'","traceback":"Traceback (most recent call last):\n  File ...","ctx":{"cwd":"/Users/les/Projects/mahavishnu","prompt_prefix":",, refactor"}}
```

Fields:
- `ts_ms` — when the error occurred (Unix ms)
- `hook` — which hook (`"jot_capture"`)
- `op` — which operation (`"capture"`, `"node_init"`, `"hdl_tail"`, etc.)
- `err` — error class + message (one line, newlines escaped)
- `traceback` — full traceback (multiline allowed in JSONL)
- `ctx` — minimal context (cwd, prompt prefix up to first 50 chars). **Never the full prompt body** (could be sensitive — defeats redaction).

### Errors log rotation

- If `errors.log` exceeds 1 MB on open: rename to `errors.log.1`, start fresh
- Keep only `errors.log` + `errors.log.1` (2 generations max, ~2 MB total)
- Rotation failures → silently swallow

### Errors log writes fail-open

- Open errors.log with `O_APPEND | O_WRONLY | O_CREAT`, mode `0o600`
- If THAT write fails, swallow the exception (no infinite recursion)
- At most one errors.log write attempt per failed capture

### No retry policy

- A failed capture is lost. No write retry, no background queue.
- Rationale: retry/queue adds complexity that defeats the "capture cannot fail" goal. A hung queue is worse than a lost jot. The user can always type the jot again.

---

## Stdlib Hygiene

The hook script (`mahavishnu/hooks/jot_capture.py`) is **stdlib-only**. Specifically forbidden:

```python
# FORBIDDEN — these defeat the hook's portability
import logging           # stdlib but hooks shouldn't use it
import oneiric           # not stdlib
import requests          # not stdlib
import httpx             # not stdlib

# ALLOWED
import json
import os
import sys
import uuid
import time
import socket
import secrets
import re
import hashlib
import traceback
import dataclasses
```

**The hook imports `mahavishnu/jot/*` modules.** Those modules are themselves stdlib-only and live under `mahavishnu/jot/` (e.g., `mahavishnu/jot/events.py`, `mahavishnu/jot/paths.py`). The hook does NOT import the Mahavishnu app/runtime — only these data-only helper modules.

---

## Components

### Files to create (sub-plan 1)

| File | Lines (est.) | Responsibility |
|---|---|---|
| `mahavishnu/hooks/jot_capture.py` | ~150 | Hook entrypoint. Stdlib + `mahavishnu/jot/*`. |
| `mahavishnu/jot/__init__.py` | ~5 | Empty (package marker). |
| `mahavishnu/jot/events.py` | ~80 | `JotEvent`, `HLC`, `serialize`, `deserialize`. |
| `mahavishnu/jot/hlc.py` | ~60 | `hlc_now`, `node_init`, `read_tail_hlc`. |
| `mahavishnu/jot/short_id.py` | ~15 | `short_id`. |
| `mahavishnu/jot/paths.py` | ~60 | `jot_dir`, `log_path`, `errors_log_path`, permission helpers. |
| `mahavishnu/jot/redact.py` | ~150 | Pattern definitions + `redact_text`. |
| `mahavishnu/jot/capture_echo.py` | ~30 | Format capture echo. |
| `tests/unit/jot/__init__.py` | ~5 | Empty. |
| `tests/unit/jot/test_events.py` | ~80 | Codec round-trip. |
| `tests/unit/jot/test_hlc.py` | ~60 | HLC monotonicity, node init. |
| `tests/unit/jot/test_short_id.py` | ~30 | Collision bounds. |
| `tests/unit/jot/test_redact.py` | ~150 | Pattern positive/negative. |
| `tests/unit/jot/test_paths.py` | ~60 | Permission enforcement. |
| `tests/unit/jot/test_capture_echo.py` | ~30 | Echo formatting. |
| `tests/integration/jot/__init__.py` | ~5 | Empty. |
| `tests/integration/jot/test_capture_e2e.py` | ~150 | Subprocess invocation, stdin/stdout/stderr assertions. |
| `tests/property/jot/__init__.py` | ~5 | Empty. |
| `tests/property/jot/test_hlc_ordering.py` | ~50 | Hypothesis: HLC monotonicity. |
| `tests/property/jot/test_codec_roundtrip.py` | ~50 | Hypothesis: serialize/deserialize identity. |

**Total:** ~1,025 lines of new code.

### Files NOT modified

- `mahavishnu/cli/jot_cli.py` — sub-plan 2
- `mahavishnu/mcp/tools/jot_tools.py` — sub-plan 2
- `mahavishnu/mcp/bootstrap.py` — sub-plan 2 (registration)
- `mahavishnu/jot/fold.py` — sub-plan 2
- `mahavishnu/jot/render.py` — sub-plan 2
- `mahavishnu/jot/drain_core.py` — sub-plan 3
- `mahavishnu/jot/offsets.py` — sub-plan 3

---

## Testing Strategy

### Unit tests (`tests/unit/jot/`)

| File | Coverage |
|---|---|
| `test_events.py` | `JotEvent` round-trip (serialize → deserialize), `HLC` ordering, frozen dataclass invariants |
| `test_hlc.py` | `hlc_now()` monotonicity, counter increment on tie, `node` initialization, persisted node read-back, malformed-tail fallback |
| `test_short_id.py` | Determinism (same id → same short_id), bounds (collision rate at 1000 random UUIDs ≤ 3%) |
| `test_redact.py` | Each tier pattern: positive cases match, negative cases don't, redact+restore of unmatched text is identity |
| `test_paths.py` | Directory created with `0o700`, log file `0o600`, errors log `0o600`, XDG-style path resolution, parent dir auto-created |
| `test_capture_echo.py` | Format: `<short_id> captured (<wc> words, <cc> chars)`, word/char counts correct |
| `test_capture_hook.py` | Stdin parsing (valid/invalid JSON), prefix detection (with/without leading whitespace, empty body), exit codes (0 vs 2), echo to stderr, fail-open on every failure mode in the taxonomy |

### Property tests (`tests/property/jot/`)

| File | Property | Examples |
|---|---|---|
| `test_hlc_ordering.py` | For any sequence of N `hlc_now()` calls in a single thread, results are strictly monotonic | ≥ 100 |
| `test_codec_roundtrip.py` | For any valid `JotEvent`, `deserialize(serialize(e)) == e` | ≥ 100 |
| `test_short_id_collision.py` | For 1000 random UUIDs, 6-hex `short_id` collisions ≤ 3% | 50 trials |

### Integration test (`tests/integration/jot/`)

| File | Coverage |
|---|---|
| `test_capture_e2e.py` | Spawn the hook as a subprocess (real Python invocation). Feed various stdin payloads via `subprocess.run(stdin=PIPE)`. Assert log file contents, stderr echo, exit codes. Uses `tmp_path` for isolation. Covers: capture happy path, passthrough no-`,,`, empty body, invalid JSON stdin, missing dir (mkdir-on-first-write). |

### Failure injection tests

In `test_capture_hook.py` and `test_capture_e2e.py`:

- `monkeypatch` `os.open` to raise `PermissionError` → assert exit 0 + errors.log entry
- `monkeypatch` `os.write` to raise `OSError` → assert exit 0 + errors.log entry
- Feed stdin with invalid JSON → assert exit 0 + errors.log entry
- Feed stdin with `prompt=""` → assert exit 0 + no errors.log entry
- Feed stdin with `",,"` only → assert exit 0 + no errors.log entry (passthrough, empty body)
- Feed stdin with `",, "` (trailing whitespace) → assert exit 0 (passthrough, empty body)

### Manual verification (not in test suite)

- `python3 ~/.claude/hooks/jot_capture.py` invoked with synthetic stdin writes the expected event and exits 2
- After sub-plan 2 ships: `mahavishnu jot install-hook` writes `~/.claude/settings.json` correctly
- After sub-plan 2 ships: type `,, test jot from TUI` in Claude Code → see capture echo, jot appears in `mahavishnu jot list`

---

## Done Criteria

A reviewer can mark sub-plan 1 complete when:

1. ✅ All unit tests pass (target coverage ≥ 95% for `mahavishnu/jot/*` + `mahavishnu/hooks/jot_capture.py`)
2. ✅ All property tests pass (≥ 100 examples each)
3. ✅ Integration test passes: subprocess invocation captures a jot, writes log, exits 2
4. ✅ Failure injection tests pass: stdin-not-JSON, permission-denied, disk-full all passthrough cleanly with errors.log entry
5. ✅ Bandit clean (`B101` no-assert enforced on `mahavishnu/jot/`, `mahavishnu/hooks/`)
6. ✅ Ruff clean (per `pyproject.toml` config, line length 100)
7. ✅ Mypy strict clean (with `from __future__ import annotations` on every file)
8. ✅ Manual verification: synthetic stdin invocation writes the expected event and exits 2
9. ✅ Spec is committed to git at `docs/superpowers/specs/2026-09-09-jot-capture-design.md`
10. ✅ Implementation plan exists at `docs/superpowers/plans/YYYY-MM-DD-jot-capture.md` (after writing-plans skill)

**NOT done in sub-plan 1 (must remain NOT-done):**
- ❌ Folding / reading jots (sub-plan 2)
- ❌ MCP tools / CLI (sub-plan 2)
- ❌ Drain to Dhara (sub-plan 3)
- ❌ `mahavishnu jot install-hook` command itself (sub-plan 2 — installs the hook we ship here)

---

## Open Questions

**OQ1.** Should the node identifier include the hostname, or be a pure random hex string? Current: hostname prefix + 4 random hex. Trade-off: human-readable (`mac01a3f9`) vs anonymized (`a3f9b2e1`). Decision: keep human-readable for now; revisit if any user objects.
**OQ2.** (Sub-plan 2's concern) Does the hook need to write a synthetic `error` event to the main log on capture failure, so sub-plan 2's read surface can show "5 jots failed to capture last session" without reading errors.log? Current decision: no, errors.log is separate. Sub-plan 2 reads errors.log directly.
**OQ3.** (Sub-plan 3's concern) What happens to errors.log entries on drain? Are they drained too? Out of scope for sub-plan 1; sub-plan 3 decides.

---

## Future Work / Handoff to Sub-plan 2

**Sub-plan 2 (Read) consumes:**
- `mahavishnu/jot/events.py` — `JotEvent`, `serialize`, `deserialize`
- `mahavishnu/jot/hlc.py` — `HLC` ordering + tail HLC reader
- `mahavishnu/jot/short_id.py` — `short_id` for display
- `mahavishnu/jot/paths.py` — log path resolution
- `mahavishnu/jot/redact.py` — redaction (extended for drain-time in sub-plan 3)
- `mahavishnu/hooks/jot_capture.py` — installed via `mahavishnu jot install-hook`

**Sub-plan 2 (Read) adds:**
- `mahavishnu/jot/fold.py` — two-pass fold with HLC + parking
- `mahavishnu/jot/render.py` — vitals, list, show, echo formatting
- `mahavishnu/jot/cli.py` — `mahavishnu jot ...` CLI
- `mahavishnu/cli/jot_cli.py` — CLI entry point
- `mahavishnu/mcp/tools/jot_tools.py` — 8 MCP tools
- `mahavishnu/mcp/bootstrap.py` — `_register_jot_tools` registration
- `mahavishnu/mcp/tools/profiles.py` — `FULL_REGISTRATIONS` addition
- Plugin manifest updates (CI guard test as 5th edit)

**Sub-plan 3 (Drain) consumes:**
- All sub-plan 1 deliverables + sub-plan 2 deliverables
- Adds `drain_core.py`, `drain_sync.py`, `drain_async.py`, `offsets.py`
- Adds drain-time redaction (full Session-Buddy `redact()`)

---

## Spec Metadata

- **Sub-plan:** 1 of 3 (Capture)
- **Estimated implementation:** ~500-700 lines of code, 1-2 days for an experienced implementer following the plan
- **Spec path:** `docs/superpowers/specs/2026-09-09-jot-capture-design.md`
- **Implementation plan path:** `docs/superpowers/plans/<written by writing-plans skill>.md`
- **Union spec:** `docs/superpowers/specs/2026-09-09-jot-inbox-design.md` (commit ad620124, archive after sub-plan 1 ships)
- **Decisions in this spec:** D1-D4 (4 new), UD1-UD9 (9 inherited)
- **Open questions:** OQ1 (node identifier), OQ2 (synthetic error events), OQ3 (errors.log drain)
