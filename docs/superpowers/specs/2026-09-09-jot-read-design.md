# Jot Inbox: Read Sub-Plan Design

> **Sub-plan 2 of 3.** This spec covers the **read** surface (fold + render + MCP tools + CLI + /jot slash command).
> Sub-plan 1 (capture) shipped at `8f8a90ea`.
> Sub-plan 3 (drain) is deferred.
> See [`2026-09-09-jot-inbox-design.md`](2026-09-09-jot-inbox-design.md) for the union.

**Goal:** Users (and AI agents) can list, show, edit, mark done/reopen, search, and inspect vitals for the captured jots via MCP tools, the `mahavishnu jot` CLI, and the `/jot` slash command.

**Architecture:** A two-pass fold with parking turns the append-only JSONL log into a current `JotSummary` / `JotDetail` list. Render layer formats output. MCP tools + CLI expose the read surface. Hook distribution is handled via the Mahavishnu plugin manifest (no `install-hook` CLI).

**Tech Stack:** Python 3.14+ stdlib + `mahavishnu.jot.*` (capture layer) + typer (CLI) + FastMCP (MCP server).

---

## Decisions (this sub-plan)

### R1. MCP tool surface — CRUD-only
**Decision:** 8 tools: `jot_list`, `jot_show`, `jot_add`, `jot_edit`, `jot_done`, `jot_reopen`, `jot_vitals`, `jot_search`.
**Why:** `jot_add` (not `jot_create`) per union spec R1. No dispatch (jot → worker) — keeps the surface minimal and aligned with the "inbox" framing. AI agents can use the existing Mahavishnu `pool_route_execute` if they need to dispatch.
**Rejected:** (a) CRUD + dispatch — adds coupling to pool machinery. (b) CRUD + dispatch + search (drop add) — too kitchen-sink.

### R2. CLI surface — mirror MCP (no install-hook)
**Decision:** 8 subcommands: `list`, `show`, `add`, `edit`, `done`, `reopen`, `vitals`, `search`.
**Why:** CLI parity with MCP means users can do anything from either surface. Hook installation is handled via the **Mahavishnu plugin manifest** (sub-plan 1's `jot_capture.py` ships with the plugin), not via a CLI command — this matches how other Bodai plugins distribute hooks (Crackerjack, Akosha).
**Rejected:** (a) Mirror MCP + tail (live log) — `tail` is dev/ops, out of user scope. (b) Mirror MCP + install-hook — install-hook belongs in the plugin manifest; CLI duplication risks divergence.

### R3. Fold algorithm — two-pass with parking
**Decision:** Two-pass: pass 1 groups events by id, parks orphan ops (done/reopen targeting missing ids). Pass 2 applies in HLC order, replays parked ops as parents appear. Genuinely orphan ops (parked through full log scan) get logged to errors.log and surfaced in `FoldResult.errors`.
**Tiebreaker:** when two events share `(wall_ms, ctr)`, sort lexicographic on `(wall_ms, ctr, node)`; same node breaks ties by `ctr` (UD4). Spec §HLC tiebreaker below makes this explicit.
**Why:** Required for sub-plan 3 (drain from Dhara may deliver events out of order). Single-pass would silently misapply out-of-order ops.
**Rejected:** (a) Single-pass — fails under drain. (b) Timestamp-only sort — violates UD4 HLC contract.

### R4. Git enrichment — lazy subprocess per call (serverless-safe)
**Decision:** On every fold, spawn `git rev-parse --show-toplevel`, `--abbrev-ref HEAD`, `HEAD` sequentially. ~150ms total per call. Fail-open: git failures → ctx fields None.
**Why:** File-based git metadata (reading `.git/HEAD` directly) **breaks serverless deployments** where no `.git/` directory exists (Lambda, Cloudflare Workers, Vercel functions, Docker scratch images). Subprocess with `FileNotFoundError` + `subprocess.CalledProcessError` fallback handles both local (with `.git/`) and serverless (without) deployment targets uniformly. The user explicitly rejected the file-based alternative during pre-implementation review for this reason.
**Rejected:** (a) Concurrent via threads — parallelism gain doesn't justify thread overhead for 3 calls. (b) Cached with TTL — extra file, more complexity, marginal benefit. (c) File-based `.git/HEAD` reads — incompatible with serverless targets.

### R5. Parking TTL — indefinite
**Decision:** Orphan ops parked indefinitely. If never replayed (genuine orphan), logged to errors.log at end of fold and surfaced in `FoldResult.errors`.
**Why:** Drain (sub-plan 3) may deliver events from minutes/hours later. TTL would silently lose data.
**Rejected:** TTL-based parking — would drop valid late-arriving ops from drain.

### R6. /jot slash command — vitals only (mandated by union)
**Decision:** `/jot` invokes `mahavishnu jot vitals` and shows output. Single-purpose, no arguments.
**Why:** Mandated by union spec R6 — slash commands are for quick status checks, not full CRUD. Users wanting CRUD use the CLI.
**Rejected:** Multi-purpose slash command — adds parsing complexity; would also violate union spec.

### R7. Fold split — pure parse + transform
**Decision:** `parse_events(log_path)` is pure file-I/O (returns `list[JotEvent]`). `build_states(events, *, enrich=True, current_dir=None)` is pure transformation (returns `FoldResult`). No monolithic `fold()`.
**Why:** Separates I/O from transformation, enables unit-testing build_states without tmpdirs, surfaces both layers for property tests. Matches "no Any, explicit signatures" discipline (TD-H1).
**Rejected:** Monolithic `fold(log_path, enrich=True)` — mixes concerns; harder to test the transform path; matches the type-design review's H1 finding.

### R8. Handle ambiguity — explicit error
**Decision:** When a handle (substring or full ID) matches ≥2 jots, raise `JotAmbiguousHandleError` listing the matched short_ids. Caller decides whether to use a longer substring or the full ID.
**Why:** Silent first-match is wrong — can mutate the wrong jot. Ambiguity is exceptional, not normal; explicit error surfaces it.
**Rejected:** (a) First-match wins — incorrect; can mutate wrong record. (b) Require full 32-hex ID always — bad UX, defeats the short_id purpose.

### R9. State shape — `JotSummary` (5 fields) + `JotDetail` (composition)
**Decision:** `JotSummary` carries only what list/short views need. `JotDetail` composes a summary with extra (HLC, created_ms, ctx). No 9-field mega-`JotState`; no dead-weight `op` field on state (kept on `JotEvent`).
**Why:** List views don't need ctx/hlc/created_ms/op — carrying them wastes memory and makes the type's invariant unclear (TD-H2). `op` is metadata about the *event*, not the *state* (TD-H3).
**Rejected:** Single 9-field `JotState` — too many fields for list views; op is dead weight at the state level.

### R10. Dataclass discipline — `frozen` + `slots` + `Mapping` for ctx
**Decision:** All state dataclasses are `@dataclass(frozen=True, slots=True)`. `ctx` is typed as `Mapping[str, str | list[str] | None]` (read-only contract), not `dict[str, Any]` — preserves the frozen invariant.
**Why:** `frozen=True` + mutable `dict[str, Any]` is a latent bug — any code holding a `JotState` reference can mutate the "immutable" ctx. `Mapping` types enforce read-only at the type level. `slots=True` cuts memory per instance (TD-H4).
**Rejected:** `frozen=True` + `dict[str, Any]` ctx — invites mutation bugs. Untyped ctx — violates "No Any" rule.

### R11. MCP return types — TypedDicts (no Any)
**Decision:** MCP tools return TypedDicts (`JotSummaryDict`, `JotDetailDict`, `JotVitalsDict`) instead of `dict[str, Any]`.
**Why:** "No Any" is a CLAUDE.md hard limit. TypedDicts make the JSON shape part of the type signature, so static analysis catches missing/extra keys (TD-H5, TD-B1).
**Rejected:** `dict[str, Any]` return type — violates CLAUDE.md; loses static checking.

---

## Locked Decisions (from union spec, inherited)

These are not sub-plan-2 decisions but are referenced and unchanged:

- **UD1.** `,,` prefix triggers capture (sub-plan 1).
- **UD2.** Terminal state is `done` (jot ops: capture/edit/done/reopen).
- **UD3.** Append-only JSONL log, one event per line, `\n` line terminator.
- **UD4.** Hybrid Logical Clock `(wall_ms, ctr, node)` — fold sorts by this. **Tiebreaker:** lex on `(wall_ms, ctr, node)`; same `(wall_ms, node)` breaks by `ctr` ascending.
- **UD5.** 32-hex UUID v4 for event IDs; 6-hex `short_id` is the **last 6 chars** of the ID (random node field — stable, low collision). **Implementation note:** `mahavishnu/jot/short_id.py` currently uses `id[:6]` (first 6); sub-plan 2 must update it to `id[-6:]` to match UD5.
- **UD6.** Log file mode `0o600`, dir mode `0o700`.
- **UD7.** No `assert` in production code (bandit B101).
- **UD8.** `from __future__ import annotations` first non-comment line of every source file.
- **UD9.** Mypy strict, Ruff line-length 100, function args ≤ 10.

---

## Goals (this sub-plan)

1. **Read parity** — list, show, edit, done, reopen work identically via MCP and CLI.
2. **Log-idempotent fold** — same log content + same `current_dir` produces same state. Git enrichment is best-effort and not part of the idempotency contract (CA-H1).
3. **Out-of-order safe** — ops arriving before their target get parked and applied when target arrives.
4. **Git-aware** — jots know which repo/branch/sha they were captured from (best-effort, fail-open, serverless-compatible).
5. **Search via Session-Buddy** — semantic search delegates to `:8678` when available, falls back to lexical.
6. **Type-safe MCP surface** — all return types are TypedDicts, no `Any` (TD-B1, TD-H5).

## Non-goals (deferred)

- ❌ Drain to Dhara (sub-plan 3)
- ❌ Drain-time redaction (sub-plan 3)
- ❌ Multi-machine sync (sub-plan 3)
- ❌ Jot → worker dispatch (deferred to follow-on sub-plan after sub-plan 3)
- ❌ Edit history visualization (just current state for v1)
- ❌ Tags / labels / categories (future)
- ❌ Cross-jot linking (future)

---

## Architecture

```
~/.mahavishnu/jot/log.jsonl
  ↓ parse_events (file I/O; pure function over Path)
mahavishnu/jot/fold.py → list[JotEvent]
  ↓ build_states (pure transform; git subprocess only when enrich=True)
mahavishnu/jot/fold.py → FoldResult(states, parked, errors)
  ↓
mahavishnu/jot/render.py → str (terminal) / TypedDict (MCP)
  ↓
mahavishnu/jot/cli.py + cli/jot_cli.py → stdout (terminal)
mahavishnu/mcp/tools/jot_tools.py → JSON (MCP)
```

**Layer boundaries:**
- `fold.py` — `parse_events()` (I/O) + `build_states()` (transform); no mixed concerns
- `render.py` — pure formatting (state → str/TypedDict); no I/O
- `handle.py` — handle resolution; pure over `list[JotSummary]`
- `cli.py` — Typer handlers; orchestrates fold + render + writes events back to log
- `mcp/tools/jot_tools.py` — FastMCP tools; orchestrates fold + render + writes events back to log
- `errors.py` — JotError hierarchy (TD-B2)

---

## Data Model

### `JotSummary` dataclass (list view, 5 fields)

```python
@dataclass(frozen=True, slots=True)
class JotSummary:
    id: str                       # 32-hex UUID v4
    short_id: str                 # last 6 hex chars (UD5)
    text: str                     # current text (latest edit wins)
    status: Literal["open", "done"]
    last_modified_ms: int         # latest event time for this jot
```

### `JotDetail` dataclass (show view, 8 fields via composition)

```python
@dataclass(frozen=True, slots=True)
class JotDetail:
    summary: JotSummary           # composition
    hlc: HLC                      # *latest* HLC for this jot (post-edit/done/reopen)
    created_ms: int               # original capture time (anchor)
    ctx: Mapping[str, str | list[str] | None]  # read-only contract
```

`op` (the last applied op) lives on `JotEvent`, NOT on state — TD-H3. State doesn't need to remember which op produced it; replay produces the same state regardless of the last op's identity.

### `FoldResult` dataclass (TD-B3 — was missing before)

```python
@dataclass(frozen=True, slots=True)
class FoldResult:
    states: list[JotSummary]      # current state, sorted by last_modified_ms desc
    parked: list[JotEvent]        # ops parked because target not yet seen
    errors: list[JotEvent]        # genuine orphans (parked after full scan)
```

`states` is what callers use. `parked` and `errors` are exposed for observability and tests — never silently dropped.

### `ctx` fields (after enrichment)

| Key | Type | Source | Notes |
|---|---|---|---|
| `cwd` | str | capture-time | Always present |
| `session_id` | str | capture-time | Always present |
| `files` | list[str] | capture-time | Optional list |
| `env_repo` | str \| None | capture-time | Optional |
| `env_branch` | str \| None | capture-time | Optional |
| `repo` | str \| None | git subprocess at fold time | Lazy; None if git fails |
| `branch` | str \| None | git subprocess at fold time | Lazy; None if git fails |
| `sha` | str \| None | git subprocess at fold time | Lazy; None if git fails |

### TypedDicts (MCP return values — TD-B1, TD-H5)

```python
class JotSummaryDict(TypedDict):
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int

class JotDetailDict(TypedDict):
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int
    hlc: str  # serialized "{wall_ms}-{ctr}-{node}"
    created_ms: int
    ctx: dict[str, str | list[str] | None]

class JotVitalsDict(TypedDict):
    total: int
    open: int
    done: int
    last_capture_ms: int | None
    oldest_ms: int | None
```

### Error hierarchy — `mahavishnu/jot/errors.py` (TD-B2 — was ValueError before)

```python
class JotError(Exception):
    """Base class for all jot errors."""

class JotNotFoundError(JotError):
    """Handle didn't match any jot."""

class JotAmbiguousHandleError(JotError):
    """Handle matched multiple jots; lists candidates."""

class JotLogCorruptError(JotError):
    """Log file has unparseable lines that prevent fold."""

class JotParseError(JotError):
    """Generic log parse failure (line-level)."""
```

Subclasses carry structured context (`candidates: list[str]` on `JotAmbiguousHandleError`) so callers can render rich error messages without parsing strings.

---

## Fold Algorithm

```python
def parse_events(log_path: Path) -> list[JotEvent]:
    """Read log, deserialize each line.
    
    - Skips malformed lines (logged to errors.log with line number).
    - Raises JotLogCorruptError only when the log can't be opened or is unreadable.
    - Truncated last line is silently skipped (handled by sub-plan 1's read_tail_hlc).
    """

def build_states(
    events: list[JotEvent],
    *,
    enrich: bool = True,
    current_dir: Path | None = None,
) -> FoldResult:
    """Two-pass fold with parking. Pure except for git subprocess when enrich=True.
    
    Pass 1: Scan events in HLC order. For each event:
      - op="capture": create JotSummary, add to states_by_id
      - op="edit": if id in states, update text/last_modified_ms; else park
      - op="done"/"reopen": if id in states, update status; else park
    
    Pass 2: Replay parked events in HLC order against current states.
      If still orphan after full scan, move from parked to errors.
    
    Returns FoldResult with states sorted by last_modified_ms desc.
    
    HLC ordering tiebreaker (UD4): lex on (wall_ms, ctr, node); same (wall_ms, node)
    breaks by ctr ascending.
    """
```

### Edge cases

- **Truncated last line** — `read_tail_hlc` (sub-plan 1) already handles this; fold iterates the full log, skipping malformed lines.
- **Multiple edits** — latest edit wins (HLC order).
- **Edit on done jot** — allowed; status remains "done".
- **Done on already-done jot** — no-op (idempotent).
- **Reopen on open jot** — no-op.
- **Status transitions** — `open` → `done` → `open` are all valid; only the latest status matters.
- **Same-HLC events** — tiebreaker is lex on `(wall_ms, ctr, node)`; same node ties broken by `ctr` order (UD4).
- **Genuine orphans** — after full log scan, still-parked events move to `FoldResult.errors` and are logged to errors.log.

### Idempotency (CA-H1 — clarified)

`build_states` is referentially transparent **for log content**: same `events` list → same `FoldResult` (states, parked, errors), regardless of the `enrich` flag setting. **However**, git enrichment is best-effort and not part of the idempotency contract — calling `build_states` twice in a row may produce different `ctx` field values if HEAD moves between calls.

Documented caveat: **"log-idempotent, not git-idempotent."** Tests asserting idempotency must set `enrich=False` to avoid flakiness.

---

## Handle Resolution (`mahavishnu/jot/handle.py`)

```python
def resolve_handle(states: list[JotSummary], handle: str) -> JotSummary:
    """Resolve handle to a single JotSummary.
    
    Match priority:
    1. Exact 32-hex ID
    2. Exact 6-hex short_id (last 6 of ID, UD5)
    3. Substring match: any unambiguous prefix/suffix of any state's id or short_id
    
    Raises:
        JotNotFoundError: handle matches no jot (message includes suggestions)
        JotAmbiguousHandleError: handle matches 2+ jots; lists candidate short_ids
    """
```

`short_id` is the **last 6 hex chars** of the ID per UD5 (CA-H2 — corrected from "first 6" in earlier draft).

---

## Render Format

### `render_list(states: list[JotSummary], *, status_filter: str | None = None, limit: int = 50) -> str`

```
OPEN  a3f9c2  refactor jot fold to use HLC ordering         2026-09-09 14:23
DONE  b7e1d4  investigate why errors.log isn't rotating     2026-09-08 11:05
OPEN  f2c8a1  plan the v1 cuts for the inbox                 2026-09-08 09:14
```

Columns: `STATUS (4 chars)`, `SHORT_ID (6 chars)`, `TEXT (truncated to 50)`, `MODIFIED (YYYY-MM-DD HH:MM)`.

### `render_show(detail: JotDetail) -> str`

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

### `render_vitals(result: FoldResult) -> str`

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

All tools return TypedDicts (JSON-serializable, no `Any`). Errors raise specific `JotError` subclasses.

```python
@mcp.tool()
def jot_list(status: str | None = None, limit: int = 50) -> list[JotSummaryDict]:
    """List jots, newest first. status filter: 'open' | 'done' | None for all."""

@mcp.tool()
def jot_show(handle: str) -> JotDetailDict:
    """Show one jot by id (32 hex) or short_id (6 hex).
    
    Raises JotNotFoundError or JotAmbiguousHandleError.
    """

@mcp.tool()
def jot_add(text: str) -> JotDetailDict:
    """Manually create a jot (alternative to ',,' capture). Writes capture event."""

@mcp.tool()
def jot_edit(handle: str, new_text: str) -> JotDetailDict:
    """Edit a jot's text. Writes edit event.
    
    Raises JotNotFoundError or JotAmbiguousHandleError.
    """

@mcp.tool()
def jot_done(handle: str) -> JotDetailDict:
    """Mark a jot as done. No-op if already done.
    
    Raises JotNotFoundError or JotAmbiguousHandleError.
    """

@mcp.tool()
def jot_reopen(handle: str) -> JotDetailDict:
    """Reopen a done jot. No-op if already open.
    
    Raises JotNotFoundError or JotAmbiguousHandleError.
    """

@mcp.tool()
def jot_vitals() -> JotVitalsDict:
    """Return counts: total, open, done, last_capture_ms, oldest_ms."""

@mcp.tool()
def jot_search(query: str, limit: int = 20) -> list[JotSummaryDict]:
    """Semantic search via Session-Buddy. Falls back to lexical substring match."""
```

---

## CLI Commands (8)

```bash
mahavishnu jot list [--status open|done] [--limit N]
mahavishnu jot show <handle>
mahavishnu jot add <text>            # quotes support multi-word
mahavishnu jot edit <handle> <new_text>
mahavishnu jot done <handle>
mahavishnu jot reopen <handle>
mahavishnu jot vitals
mahavishnu jot search <query> [--limit N]
```

Typer app at `mahavishnu/cli/jot_cli.py`. Each subcommand handler in `mahavishnu/jot/cli.py`. Output via stdout (terminal-friendly render). Errors via stderr + exit code 1.

**Hook installation:** distributed via the Mahavishnu plugin manifest (R2). The `mahavishnu/hooks/jot_capture.py` file ships with the plugin and is registered in `mahavishnu/mcp/tools/profiles.py`. No CLI install-hook command.

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

Behavior: invokes `mahavishnu jot vitals` and shows output. No arguments (R6 — mandated by union spec).

---

## Git Enrichment

On every `build_states(events, enrich=True, current_dir=...)` call:

```python
def _enrich_ctx(ctx: dict, current_dir: Path) -> Mapping[str, str | None]:
    """Add git repo/branch/sha to ctx. Fail-open: git failures → None.
    
    Serverless-safe: uses subprocess (file-based .git/ reads would break).
    """
    enriched: dict[str, str | None] = dict(ctx)
    try:
        enriched["repo"] = _git(current_dir, "rev-parse", "--show-toplevel")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["repo"] = None
    try:
        enriched["branch"] = _git(current_dir, "rev-parse", "--abbrev-ref", "HEAD")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["branch"] = None
    try:
        enriched["sha"] = _git(current_dir, "rev-parse", "HEAD")
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
| `test_fold.py` | parse_events + build_states; HLC tiebreaker; parking; orphan→errors; log-idempotency; git enrichment fail-open |
| `test_handle.py` | Exact ID, exact short_id, substring, ambiguity, not-found |
| `test_render.py` | list, show, vitals formats; column alignment; truncation |
| `test_cli.py` | Each of 8 subcommands; arg parsing; error handling |
| `test_jot_tools.py` | All 8 MCP tools; error cases; status filters; search fallback |
| `test_errors.py` | Error hierarchy; subclass relations; message preservation |
| `test_short_id.py` | Verify `id[-6:]` after UD5 fix (was `id[:6]`) |

### Property tests

| Property | Examples |
|---|---|
| Fold log-idempotency (same events → same states; set enrich=False) | 50 |
| Capture-edit-done-reopen commutativity under same HLC | 30 |
| Parked-op replay correctness | 50 |
| Handle ambiguity always raises (never silent first-match) | 30 |

### Integration tests (`test_read_e2e.py`)

| Scenario | Coverage |
|---|---|
| capture → fold → CLI list | End-to-end pipeline |
| MCP tool call via subprocess | MCP registration works |
| Slash command resolution | `/jot` invokes vitals |

---

## Done Criteria

1. All unit + property + integration tests pass
2. Coverage ≥ 90% for `mahavishnu/jot/fold.py`, `handle.py`, `render.py`, `cli.py`, `errors.py`, `mahavishnu/mcp/tools/jot_tools.py`
3. Mypy strict clean (no `Any` in tool inputs or return types — verified by `tests/unit/test_jot/test_no_any.py` static check)
4. Ruff clean (BLE001 narrowed where possible; `# noqa: BLE001` for catch-all fail-open cases)
5. Bandit clean (no B101, no high-severity)
6. `mahavishnu jot list` works on real log
7. 8 MCP tools registered in `profiles.py` (FULL_REGISTRATIONS + REGISTRATION_MAP)
8. CI guard test asserts registration count
9. `/jot` slash command visible in Claude Code TUI
10. `mahavishnu/jot/short_id.py` updated to use `id[-6:]` (UD5 spec change from first-6 to last-6)
11. `mahavishnu/jot/errors.py` exists with full hierarchy
12. `FoldResult` returned by `build_states`, not `list[JotSummary]` directly

---

## Open Questions

- **OQ1.** Should `jot_search` return scored results (semantic similarity) or just matched substrings (lexical)? Currently: both — semantic via Session-Buddy with lexical fallback. Confirm with user after Session-Buddy integration spike.
- **OQ2.** When the log file doesn't exist (no jots captured yet), should `jot_list` return `[]` or raise? Current: `[]` (no error). Reasonable.

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

## Review Triage (this round)

This version applies all BLOCKERs (6) and HIGHs (10) from the multi-subagent review:

| # | Severity | Finding | Resolved as |
|---|---|---|---|
| CA-B1 | BLOCKER | Git enrichment via subprocess vs file | **Kept subprocess** — file-based breaks serverless (user override) |
| CA-B2 | BLOCKER | `jot_create` vs `jot_add` per union spec | **Renamed to `jot_add`** everywhere |
| CA-B3 | BLOCKER | install-hook vs plugin manifest | **Dropped install-hook**, plugin manifest distribution |
| TD-B1 | BLOCKER | `dict[str, Any]` violates "No Any" | **TypedDicts** (`JotSummaryDict`, `JotDetailDict`, `JotVitalsDict`) |
| TD-B2 | BLOCKER | `ValueError` for all MCP errors | **`mahavishnu/jot/errors.py`** hierarchy |
| TD-B3 | BLOCKER | `FoldResult` missing → orphan data dropped | **`FoldResult` dataclass** with states/parked/errors |
| CA-H1 | HIGH | Idempotency broken by git enrichment | **Documented caveat** — log-idempotent, not git-idempotent |
| CA-H2 | HIGH | First-6-hex vs last-6-hex | **Last 6** per UD5 (with `short_id.py` fix item) |
| CA-H3 | HIGH | /jot scope contradicts union | **Vitals-only confirmed** in R6 |
| CA-H4 | HIGH | HLC tiebreaker not specified | **Explicit tiebreaker** in R3 and UD4 |
| CA-H5 | HIGH | Handle ambiguity not handled | **R8 + `JotAmbiguousHandleError`** |
| TD-H1 | HIGH | Fold mixes pure + I/O + boolean flag | **R7** — `parse_events` + `build_states` |
| TD-H2 | HIGH | 9-field JotState | **R9** — `JotSummary` (5) + `JotDetail` (composition) |
| TD-H3 | HIGH | `op` field dead weight on state | **R9** — `op` lives on `JotEvent`, not state |
| TD-H4 | HIGH | frozen + mutable dict violation | **R10** — `slots=True` + `Mapping[str, str \| None]` |
| TD-H5 | HIGH | MCP return types lack TypedDicts | **R11** — all MCP tools return TypedDicts |

MEDIUMs (16) and LOWs (12) deferred to post-BLOCKER/HIGH sweep; will be picked up during implementation.

---

## Spec Metadata

- **Sub-plan:** 2 of 3 (Read)
- **Depends on:** sub-plan 1 (capture) at `8f8a90ea`
- **Estimated implementation:** ~1,400 lines code, ~1,700 lines tests, 2-3 days
- **Spec path:** `docs/superpowers/specs/2026-09-09-jot-read-design.md`
- **Implementation plan path:** `docs/superpowers/plans/<written by writing-plans skill>.md`
