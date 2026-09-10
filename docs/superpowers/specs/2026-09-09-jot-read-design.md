# Jot Inbox: Read Sub-Plan Design

> **Sub-plan 2 of 3.** This spec covers the **read** surface (fold + render + MCP tools + CLI + install-hook + /jot slash command).
> Sub-plan 1 (capture) shipped at `8f8a90ea`.
> Sub-plan 3 (drain) is deferred.
> See [`2026-09-09-jot-inbox-design.md`](2026-09-09-jot-inbox-design.md) for the union.

**Goal:** Users (and AI agents) can list, show, edit, mark done/reopen, search, and inspect vitals for the captured jots via MCP tools, the `mahavishnu jot` CLI, and the `/jot` slash command.

**Architecture:** A two-pass fold with parking turns the append-only JSONL log into a current `JotState` list. Render layer formats output. MCP tools + CLI expose the read surface. `install-hook` wires the capture hook (sub-plan 1) into Claude Code.

**Tech Stack:** Python 3.14+ stdlib + mahavishnu.jot.* (capture layer) + typer (CLI) + FastMCP (MCP server).

---

## Decisions (this sub-plan)

### R1. MCP tool surface — CRUD-only
**Decision:** 8 tools: `jot_list`, `jot_show`, `jot_create`, `jot_edit`, `jot_done`, `jot_reopen`, `jot_vitals`, `jot_search`.
**Why:** No dispatch (jot → worker) — keeps the surface minimal and aligned with the "inbox" framing. AI agents can use the existing Mahavishnu `pool_route_execute` if they need to dispatch.
**Rejected:** (a) CRUD + dispatch — adds coupling to pool machinery. (b) CRUD + dispatch + search (drop create) — too kitchen-sink.

### R2. CLI surface — mirror MCP + install-hook
**Decision:** 9 subcommands: `list`, `show`, `create`, `edit`, `done`, `reopen`, `vitals`, `search`, `install-hook`.
**Why:** CLI parity with MCP means users can do anything from either surface. install-hook belongs here because the hook ships in sub-plan 1 but the install step is the user-facing CLI entry point.
**Rejected:** (a) Mirror MCP + tail (live log) — `tail` is dev/ops, out of user scope. (b) Mirror MCP only — install-hook would have nowhere to live.

### R3. Fold algorithm — two-pass with parking
**Decision:** Two-pass: pass 1 groups events by id, parks orphan ops (done/reopen targeting missing ids). Pass 2 applies in HLC order, replays parked ops as parents appear. Genuinely orphan ops (parked through full log scan) get logged to errors.log and skipped.
**Why:** Required for sub-plan 3 (drain from Dhara may deliver events out of order). Single-pass would silently misapply out-of-order ops.
**Rejected:** (a) Single-pass — fails under drain.

### R4. Git enrichment — lazy subprocess per call
**Decision:** On every fold, spawn `git rev-parse --show-toplevel`, `--abbrev-ref HEAD`, `HEAD` sequentially. ~150ms total per call. Fail-open: git failures → ctx fields None.
**Why:** Simplest implementation. No cache to invalidate. Captures the user's current state when they ask.
**Rejected:** (a) Concurrent via threads — parallelism gain doesn't justify thread overhead for 3 calls. (b) Cached with TTL — extra file, more complexity, marginal benefit.

### R5. Parking TTL — indefinite
**Decision:** Orphan ops parked indefinitely. If never replayed (genuine orphan), logged to errors.log at end of fold and skipped.
**Why:** Drain (sub-plan 3) may deliver events from minutes/hours later. TTL would silently lose data.
**Rejected:** TTL-based parking — would drop valid late-arriving ops from drain.

### R6. /jot slash command — vitals only
**Decision:** `/jot` invokes `mahavishnu jot vitals` and shows output. Single-purpose, no arguments.
**Why:** Slash commands are for quick status checks, not full CRUD. Users wanting CRUD use the CLI.
**Rejected:** Multi-purpose slash command — adds parsing complexity for marginal benefit.

---

## Locked Decisions (from union spec, inherited)

These are not sub-plan-2 decisions but are referenced and unchanged:

- **UD1.** `,,` prefix triggers capture (sub-plan 1).
- **UD2.** Terminal state is `done` (jot ops: capture/edit/done/reopen).
- **UD3.** Append-only JSONL log, one event per line, `\n` line terminator.
- **UD4.** Hybrid Logical Clock `(wall_ms, ctr, node)` — fold sorts by this.
- **UD5.** 32-hex UUID v4 for event IDs; 6-hex `short_id` is the first 6 chars.
- **UD6.** Log file mode `0o600`, dir mode `0o700`.
- **UD7.** No `assert` in production code (bandit B101).
- **UD8.** `from __future__ import annotations` first non-comment line.
- **UD9.** Mypy strict, Ruff line-length 100, function args ≤ 10.

---

## Goals (this sub-plan)

1. **Read parity** — list, show, edit, done, reopen work identically via MCP and CLI.
2. **Idempotent fold** — calling fold multiple times on the same log produces the same state.
3. **Out-of-order safe** — ops arriving before their target get parked and applied when target arrives.
4. **Git-aware** — jots know which repo/branch/sha they were captured from.
5. **Search via Session-Buddy** — semantic search delegates to `:8678` when available, falls back to lexical.

## Non-goals (deferred)

- ❌ Drain to Dhara (sub-plan 3)
- ❌ Drain-time redaction (sub-plan 3)
- ❌ Multi-machine sync (sub-plan 3)
- ❌ Jot → worker dispatch (deferred to follow-on sub-plan after sub-plan 3)
- ❌ Edit history visualization (just current state for v1)
- ❌ Tags / labels / categories (future)
- ❌ Cross-jot linking (e.g., `parent: a3f9c2`) (future)

---

## Architecture

```
~/.mahavishnu/jot/log.jsonl
  ↓ (two-pass fold with parking)
mahavishnu/jot/fold.py → list[JotState]
  ↓
mahavishnu/jot/render.py → str (terminal) / dict (MCP)
  ↓
mahavishnu/jot/cli.py + cli/jot_cli.py → stdout (terminal)
mahavishnu/mcp/tools/jot_tools.py → JSON (MCP)
```

**Layer boundaries:**
- `fold.py` — pure transformation (log → state list); no I/O except log read + git subprocess
- `render.py` — pure formatting (state → str/dict); no I/O
- `cli.py` — Typer handlers; orchestrates fold + render + writes events back to log
- `mcp/tools/jot_tools.py` — FastMCP tools; orchestrates fold + render + writes events back to log
- `install.py` — one-time hook installation; copies file + merges settings.json

---

## Data Model

### `JotState` dataclass

```python
@dataclass(frozen=True)
class JotState:
    id: str                       # 32-hex UUID v4
    short_id: str                 # first 6 hex chars
    text: str                     # current text (latest edit wins)
    op: Op                        # last applied op
    hlc: HLC                      # latest HLC for this jot
    created_ms: int               # original capture time
    last_modified_ms: int         # latest event time for this jot
    status: Literal["open", "done"]
    ctx: dict[str, Any]           # ambient context, enriched with git
```

### `ctx` fields (after enrichment)

| Key | Source | Notes |
|---|---|---|
| `cwd` | capture-time | Always present (from sub-plan 1) |
| `session_id` | capture-time | Always present (from sub-plan 1) |
| `files` | capture-time | Optional list (from sub-plan 1) |
| `env_repo` | capture-time | Optional (from sub-plan 1) |
| `env_branch` | capture-time | Optional (from sub-plan 1) |
| `repo` | git subprocess at fold time | Lazy; None if git fails |
| `branch` | git subprocess at fold time | Lazy; None if git fails |
| `sha` | git subprocess at fold time | Lazy; None if git fails |

---

## Fold Algorithm

```python
def fold(log_path: Path, enrich: bool = True) -> list[JotState]:
    """Two-pass fold with parking.

    Pass 1: Scan log in HLC order. For each event:
      - op="capture": create JotState, add to states_by_id
      - op="edit": if id in states, update text/hlc/last_modified_ms; else park
      - op="done"/"reopen": if id in states, update status; else park

    Pass 2: Replay parked events in HLC order against current states.
      If still orphan after full log scan, log to errors.log and skip.

    Returns list of JotState, sorted by hlc desc (newest first).
    """
```

### Edge cases

- **Truncated last line** — `read_tail_hlc` (sub-plan 1) already handles this; fold iterates the full log, skipping malformed lines.
- **Multiple edits** — latest edit wins (HLC order).
- **Edit on done jot** — allowed; status remains "done".
- **Done on already-done jot** — no-op (idempotent).
- **Reopen on open jot** — no-op.
- **Status transitions** — `open` → `done` → `open` are all valid; only the latest status matters.

### Idempotency

`fold` is referentially transparent: same log → same output, always. No caching, no mutation. Multiple calls in the same process return the same result.

---

## Render Format

### `render_list(states: list[JotState], *, status_filter: str | None = None, limit: int = 50) -> str`

```
OPEN  a3f9c2  refactor jot fold to use HLC ordering         2026-09-09 14:23
DONE  b7e1d4  investigate why errors.log isn't rotating     2026-09-08 11:05
OPEN  f2c8a1  plan the v1 cuts for the inbox                 2026-09-08 09:14
```

Columns: `STATUS (4 chars)`, `SHORT_ID (6 chars)`, `TEXT (truncated to 50)`, `MODIFIED (YYYY-MM-DD HH:MM)`.

### `render_show(state: JotState) -> str`

```
ID:        a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d
Status:    OPEN
Created:   2026-09-09 14:23:01
Modified:  2026-09-09 14:23:01
Repo:      /Users/les/Projects/mahavishnu (main @ a3f9c2b)
Session:   sess_xyz

Text:
  refactor jot fold to use HLC ordering
```

### `render_vitals(states: list[JotState]) -> str`

```
Jot inbox vitals
  Total:   247
  Open:    198
  Done:     49
  Last:    2026-09-09 14:23 (3 hours ago)
  Oldest:  2026-08-22 09:01 (18 days ago)
```

---

## MCP Tools (8)

All tools return dict (JSON-serializable). Errors raise `ValueError` with descriptive message.

```python
@mcp.tool()
def jot_list(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List jots, newest first. status filter: 'open' | 'done' | None for all."""

@mcp.tool()
def jot_show(handle: str) -> dict[str, Any]:
    """Show one jot by id (32 hex) or short_id (6 hex). Raises ValueError if not found."""

@mcp.tool()
def jot_create(text: str) -> dict[str, Any]:
    """Manually create a jot (alternative to ',,' capture). Writes capture event."""

@mcp.tool()
def jot_edit(handle: str, new_text: str) -> dict[str, Any]:
    """Edit a jot's text. Writes edit event. Raises ValueError if handle not found."""

@mcp.tool()
def jot_done(handle: str) -> dict[str, Any]:
    """Mark a jot as done. No-op if already done."""

@mcp.tool()
def jot_reopen(handle: str) -> dict[str, Any]:
    """Reopen a done jot. No-op if already open."""

@mcp.tool()
def jot_vitals() -> dict[str, Any]:
    """Return counts: total, open, done, last_capture_ms, oldest_ms."""

@mcp.tool()
def jot_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Semantic search via Session-Buddy. Falls back to lexical substring match."""
```

---

## CLI Commands (9)

```bash
mahavishnu jot list [--status open|done] [--limit N]
mahavishnu jot show <handle>
mahavishnu jot create <text>     # quotes support multi-word
mahavishnu jot edit <handle> <new_text>
mahavishnu jot done <handle>
mahavishnu jot reopen <handle>
mahavishnu jot vitals
mahavishnu jot search <query> [--limit N]
mahavishnu jot install-hook
```

Typer app at `mahavishnu/cli/jot_cli.py`. Each subcommand handler in `mahavishnu/jot/cli.py`. Output via stdout (terminal-friendly render). Errors via stderr + exit code 1.

---

## install-hook

`mahavishnu jot install-hook` performs:

1. **Copy** `mahavishnu/hooks/jot_capture.py` to `~/.claude/hooks/jot_capture.py` (idempotent: skip if content matches via sha256)
2. **Merge** `UserPromptSubmit` entry into `~/.claude/settings.json`:
   ```json
   {"hooks": {"UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/jot_capture.py", "timeout": 5}]}]}}
   ```
3. **Print** confirmation: `Hook installed. Captures via ',,' are now active. Test with: ,, hello from CLI`

Idempotency: re-running does not duplicate the hook entry; safe to call from shell init scripts.

---

## /jot slash command

File at `mahavishnu/commands/jot.md` (registered in Mahavishnu plugin manifest).

```yaml
---
description: Show jot inbox vitals
allowed-tools: []
---

Run `mahavishnu jot vitals` and display the output verbatim.
```

Behavior: invokes `mahavishnu jot vitals` and shows output. No arguments.

---

## Git Enrichment

On every fold call:

```python
def _enrich_ctx(ctx: dict) -> dict:
    """Add git repo/branch/sha to ctx. Fail-open: git failures → None."""
    enriched = dict(ctx)
    try:
        enriched["repo"] = _git("rev-parse", "--show-toplevel")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["repo"] = None
    try:
        enriched["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["branch"] = None
    try:
        enriched["sha"] = _git("rev-parse", "HEAD")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["sha"] = None
    return enriched
```

Performance: ~150ms total per fold. Acceptable since fold is on-demand, not hot-path.

---

## Testing Strategy

### Unit tests

| File | Coverage |
|---|---|
| `test_fold.py` | Two-pass correctness, HLC ordering, parking, orphan skip + errors.log, idempotency, git enrichment fail-open |
| `test_render.py` | list, show, vitals formats; column alignment; truncation |
| `test_cli.py` | Each of 9 subcommands; arg parsing; error handling |
| `test_jot_tools.py` | All 8 MCP tools; error cases; status filters; search fallback |
| `test_install.py` | Idempotency; settings.json merge preserves other settings; sha256 compare |

### Property tests

| Property | Examples |
|---|---|
| Fold idempotency (same log → same state) | 50 |
| Capture-edit-done-reopen commutativity under same HLC | 30 |
| Parked-op replay correctness | 50 |

### Integration tests (`test_read_e2e.py`)

| Scenario | Coverage |
|---|---|
| capture → fold → CLI list | End-to-end pipeline |
| install-hook → fresh settings.json → hook installed | Idempotency + merge |
| MCP tool call via subprocess | MCP registration works |

---

## Done Criteria

1. All unit + property + integration tests pass
2. Coverage ≥ 90% for `mahavishnu/jot/fold.py`, `render.py`, `cli.py`, `mahavishnu/mcp/tools/jot_tools.py`
3. Mypy strict clean
4. Ruff clean (BLE001 narrowed where possible; `# noqa: BLE001` for catch-all fail-open cases)
5. Bandit clean (no B101, no high-severity)
6. `mahavishnu jot list` works on real log
7. `mahavishnu jot install-hook` writes working entry, idempotent
8. 8 MCP tools registered in `profiles.py` (FULL_REGISTRATIONS + REGISTRATION_MAP)
9. CI guard test asserts registration count (5th edit per union spec)
10. `/jot` slash command visible in Claude Code TUI

---

## Open Questions

- **OQ1.** Should `jot_search` return scored results (semantic similarity) or just matched substrings (lexical)? Currently: both — semantic via Session-Buddy with lexical fallback. Confirm with user after Session-Buddy integration spike.
- **OQ2.** When the log file doesn't exist (no jots captured yet), should `jot_list` return `[]` or raise? Current: `[]` (no error). Reasonable.
- **OQ3.** Should `mahavishnu jot install-hook` also create the `~/.mahavishnu/jot/` directory? Current: yes (idempotent).

---

## Future Work / Handoff to Sub-plan 3 (Drain)

**Sub-plan 3 (Drain) consumes:**
- All sub-plan 1 + sub-plan 2 deliverables
- `mahavishnu/jot/fold.py` — drain reads from log, then writes to Dhara
- `mahavishnu/jot/events.py` — drain emits copy events
- `mahavishnu/jot/redact.py` — drain-time redaction with full Session-Buddy `redact()`

**Sub-plan 3 (Drain) adds:**
- `mahavishnu/jot/drain_core.py` — pure planner
- `mahavishnu/jot/drain_sync.py` — urllib, 2s hard limit
- `mahavishnu/jot/drain_async.py` — httpx2 wrapper
- `mahavishnu/jot/offsets.py` — Dhara offset bookkeeping
- Drain triggers (SessionStart, SessionEnd, drain-before-read)
- `MockSessionBuddy` test fixture

---

## Spec Metadata

- **Sub-plan:** 2 of 3 (Read)
- **Depends on:** sub-plan 1 (capture) at `8f8a90ea`
- **Estimated implementation:** ~1,200 lines code, ~1,500 lines tests, 2-3 days
- **Spec path:** `docs/superpowers/specs/2026-09-09-jot-read-design.md`
- **Implementation plan path:** `docs/superpowers/plans/<written by writing-plans skill>.md`
