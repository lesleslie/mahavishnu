---
status: draft
role: implementation
topic: tooling
date: 2026-09-29
last_reviewed: 2026-09-29
superseded_by: null
blocks_on: []
title: "Bodai Task System Design"

---

# Bodai Task System Design

## **Goal:** A unified cross-component replacement for Claude Code's default `TaskCreate` / `TodoWrite` tool family, currently disabled by Anthropic's `tengu_vellum_ash` server-side gate on `MiniMax-M3`, `Opus 4.8`, `Sonnet 5`, and `Fable 5`. Tasks persist across sessions, link to git branches via `auto-coordinate`, hand off to mahavishnu workflows via an explicit tool (no implicit side channels), and surface analytics through akosha — all under server-side caller-identity authz. **Architecture:** Three-Bodai-component split: session-buddy is the system of record (CRUD over reflections), mahavishnu owns workflow handoff (`tasks_handoff_to_workflow` is the only dispatch edge), akosha owns read/analytics. Plus a Claude Code skill for UX. No new MCP server. **Tech Stack:** Python 3.14 (target per `CLAUDE.md`), FastMCP, Pydantic v2, `uuid.uuid7()`, existing Bodai WebSocket event bus (`bodai:events` Redis Stream), existing Akosha reindex, existing `auto-coordinate` skill.

## Context

The default Claude Code `TaskCreate` / `TodoWrite` / `TaskUpdate` / `TaskList` / `TaskGet` tools are unavailable in this session because:

1. The model proxy at `https://api.minimax.io/anthropic` does not advertise `TodoWrite` in the tool schema.
2. Claude Code's "Background Tasks" feature is gated by Anthropic's remote-config flag `tengu_vellum_ash` against a model allowlist (`claude-opus-4-8`, `claude-sonnet-5`, `claude-fable-5`). Per issue [anthropics/claude-code#80487](https://github.com/anthropics/claude-code/issues/80487) the gate has no client-side override. Per issue [#80305](https://github.com/anthropics/claude-code/issues/80305) the only known workaround (`DISABLE_TELEMETRY=1`) costs 1M context, `/remote-control`, `--bg`, Agent View, 1h prompt-cache TTL, and remote killswitches.

This is not a temporary outage — the design ships a permanent Bodai-native replacement that is strictly more capable than the default tools (cross-session persistence, git-branch linking via `auto-coordinate`, semantic search via akosha, explicit workflow handoff via mahavishnu, server-side authz).

## Goals & Non-Goals

### Goals

1. **Cross-session persistence** — tasks survive Claude Code session restarts
2. **Git-branch linking** — tasks get auto-linked to the working branch via `auto-coordinate` skill
3. **Explicit workflow dispatch** — `mahavishnu.tasks_handoff_to_workflow` is the *only* way to trigger `dispatch_to_pool` from a task (no magic-string or implicit paths)
4. **Semantic read surface** — akosha powers "what's blocking me?", "tasks like this", "tasks overdue for me"
5. **Subagent compatibility** — works from subagents dispatched via `Agent` tool, even when those subagents lack `TodoWrite` themselves
6. **Server-side caller-identity authz** — `owner`/`created_by`/`completed_by`/`actor` derived from authenticated MCP caller identity; read paths enforce `caller_identity == owner OR visibility == "public"` server-side, regardless of caller-supplied filters
7. **Backwards-compat with existing pattern** — `mcp__session-buddy__store_reflection(content, tags=["todo", ...])` continues to work via explicit `include_legacy` opt-in; new `tasks_*` tools are the typed layer above

### Non-Goals (v1)

- **Not a Claude Code marketplace plugin.** Skills yes, but no `claude-plugins-official` submission in v1.
- **Not a stand-alone MCP server.** Reuses existing session-buddy, mahavishnu, akosha servers. (`bodai-tasks` MCP considered and rejected.)
- **Not atomic handoff.** Orphan window acknowledged; sweeper deferred to v1.1.
- **No multi-tenant UI/sharing** — `visibility` field exists for v1.1 team mode, but v1 only enforces `private`/`public`. No shared lists, no UI for team-mode.
- **No implicit dispatch path** — every dispatch goes through the explicit `tasks_handoff_to_workflow` call. Anti-flap is enforced by *removing* the conditional path entirely, not by gating it on a magic string.
- **Not a `TaskCreate` replacement in spirit.** This is a *better* system; `TaskCreate` won't be re-recommended even if it comes back.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code (this session, subagents, future sessions) │
│  + task-system skill (UX)                               │
└──────────────────────────┬──────────────────────────────┘
                           │ routes to:
        ┌──────────────────┼───────────────────┬───────────────────┐
        ▼                  ▼                   ▼                   ▼
  ┌──────────────┐   ┌──────────────┐     ┌────────────┐     ┌────────────┐
  │ session-     │   │ mahavishnu   │     │ akosha     │     │ auto-coord │
  │ buddy        │   │              │     │            │     │ (existing) │
  │ CRUD         │   │ ORCHESTRATE  │     │ ANALYZE    │     │ GIT-LINK   │
  │ system of    │   │ handoff to   │     │ read/      │     │ existing   │
  │ record       │   │ workflows    │     │ analytics  │     │ skill      │
  └──────────────┘   └──────────────┘     └────────────┘     └────────────┘
        │                  │                   │
        │ emits:           │ dispatches:        │ reads via:
        │ bodai:events     │ bodai:events       │ semantic index
        │ Redis Stream     │ Redis Stream       │ (already indexed)
        ▼                  ▼                   ▼
   [task.created]      [task.handoff_started]  [search_all_systems]
   [task.updated]      [task.handoff_completed] [analyze_trends]
   [task.completed]    [task.handoff_orphan]    [correlate_systems]
```

Each component does what it's best at. session-buddy is the system of record; mahavishnu owns the dispatch edge; akosha powers read/analytics. The skill is the UX layer; `auto-coordinate` is a separate existing skill extended to react to `tasks_*` calls.

## Components & Responsibilities

### session-buddy (CRUD — system of record — new tools)

```python
# All under existing mcp__session-buddy__ namespace. ALL async def.
# Per project convention: no `Any` in tool inputs; typed envelopes for paginated results.

@mcp.tool()
async def tasks_create(
    content: str,                                        # ≤ 4 KiB; control chars stripped
    tags: list[str],                                     # ≤ 32 items; must include "task"
    owner: str | None = None,                            # server overwrites from caller identity
    due: datetime | None = None,                         # must be timezone-aware (ISO 8601)
    priority: Literal["critical","high","normal","low"] = "normal",
    effort: Literal["xs","s","m","l","xl"] | None = None,
    parent_task_id: str | None = None,                   # must match id pattern if set
    metadata: dict[str, JsonValue] | None = None,        # ≤ 1 KiB serialized
) -> Task: ...

@mcp.tool()
async def tasks_list(
    status: Literal["open","in_progress","blocked","done","cancelled"] | None = None,
    owner: str | None = None,
    tag: str | None = None,
    parent_task_id: str | None = None,
    include_legacy: bool = False,                        # default OFF; surfaces ghost tasks otherwise
    k: int = 20,
    cursor: str | None = None,
) -> TaskListResult: ...                                # {items, next_cursor, total}

@mcp.tool()
async def tasks_get(task_id: str) -> Task: ...           # validates ^t-[0-9a-f]{32}$

@mcp.tool()
async def tasks_update(
    task_id: str,
    request: UpdateTaskRequest,                          # bounded Pydantic, NOT **fields
) -> Task: ...

@mcp.tool()
async def tasks_complete(
    task_id: str,
    result_notes: str | None = None,                     # free text; no implicit dispatch
) -> Task: ...                                          # status=done; completed_at now

@mcp.tool()
async def tasks_search(
    query: str,
    project: str | None = None,                          # parity with quick_search
    min_score: float | None = None,
    k: int = 10,
) -> list[Task]: ...

@mcp.tool()
async def tasks_history(
    task_id: str,
    k: int = 50,
    cursor: str | None = None,
) -> TaskHistoryResult: ...                             # {items, next_cursor}
```

**Identity model**: `owner`, `created_by`, and `completed_by` are server-derived from the authenticated MCP caller identity. Caller-supplied values for these fields are **rejected** (unless the caller holds an explicit admin role, which is not in v1). See "Authz Model" section.

**Bounded enums everywhere** so FastMCP can publish typed schemas and clients can introspect valid values.

**Why async**: every existing session-buddy memory tool (`store_reflection`, `quick_search`, `search_by_concept`) is `async def` because it hits the reflection DB asynchronously. New `tasks_*` tools follow the same convention.

### mahavishnu (orchestration handoff — new tool, the *only* dispatch edge)

```python
# Under existing mcp__mahavishnu__ namespace.

@mcp.tool()
async def tasks_handoff_to_workflow(
    task_id: str,                                         # must match ^t-[0-9a-f]{32}$
    adapter: Literal["prefect", "llamaindex", "agno"] = "prefect",
    params: HandoffParams | None = None,                 # typed, NOT dict
    timeout: int | None = None,
) -> HandoffResult:
    """Dispatch task.content as a workflow; store workflow_id on task.

    Three sequential steps inside a try/finally that emits
    `task.handoff_orphan` on asyncio.CancelledError:

      1. session-buddy.tasks_get(task_id)              # fail-fast if down
      2. dispatch_to_pool(prompt=validated_content)    # fail → task not updated
      3. session-buddy.tasks_update(task_id,
              UpdateTaskRequest(metadata__workflow_id=...))
                                                    # fail → orphan event

    Caller-disconnect mid-flight (asyncio.CancelledError between
    step 2 and step 3) emits task.handoff_orphan so the v1.1 sweeper
    can re-link. See "Error Handling Matrix".
    """
```

Calls `dispatch_to_pool` internally. No new transport — reuses `bodai:events` and `workflow:*` WebSocket channels. **No implicit dispatch from `tasks_complete`** — that path was removed in the v1.1 spec revision; handoff is a deliberate two-call flow.

### akosha (read/analysis path — 6 thin wrappers over the indexed reflections)

```python
@mcp.tool()
def tasks_similar_to(task_id: str, k: int = 10) -> list[Task]: ...
@mcp.tool()
def tasks_blocking(owner: str) -> list[Task]: ...
@mcp.tool()
def tasks_overdue_for(owner: str) -> list[Task]: ...
@mcp.tool()
def tasks_velocity(owner: str, window: Literal["1d","7d","30d"] = "7d") -> VelocityStats: ...
@mcp.tool()
def tasks_anomalies(
    scope: Literal["all", "owner"] = "all",
    owner: str | None = None,                            # split discriminator+payload
) -> list[Anomaly]: ...
@mcp.tool()
def tasks_correlate(
    metric: Literal["completion_rate","creation_rate","block_rate","handoff_rate"] = "completion_rate",
    window: Literal["7d","30d","90d"] = "30d",
) -> CorrelationReport: ...
```

All 6 ship in v1 per design decision. No new storage engine — these are thin query shapes over the existing akosha semantic index of session-buddy reflections.

### `auto-coordinate` skill (existing, body + matcher change)

The existing skill at `~/.claude/skills/auto-coordinate/SKILL.md` reacts to `coord_create_issue`, `coord_create_todo`, `coord_close_issue`. **The wiring is more than a one-line frontmatter change** — the skill body has to learn how to resolve a session-buddy `t-{hex}` task ID to a reflection URL and persist the branch link into session-buddy's storage, not mahavishnu's. v1 needs:

1. Update `description:` text in `auto-coordinate/SKILL.md` to include "after Claude calls tasks_create / tasks_complete"
2. Add a new entity-type branch in the skill body (similar to its existing `coord_*` handling)
3. Optionally also add a `PostToolUse` matcher to `mahavishnu/.claude/settings.json` hooks block targeting `mcp__session-buddy__tasks_create|mcp__session-buddy__tasks_complete` (defense in depth)

Verified by reading the existing skill; the body branch is real work. The frontmatter description update is one line; the body branch is ~30 LOC.

### `task-system` skill (new, UX layer)

Single `SKILL.md` in `session-buddy/.claude/skills/bodai-session-buddy-task-system/`. **Skill name must match the federation materialization path** (`bodai-session-buddy-task-system`) to avoid duplicate-trigger ambiguity from co-location vs federation.

See "Draft SKILL.md" section for the full frontmatter, trigger phrases, decision tree, and body skeleton. The skill is auto-**discoverable** through `mcp__akosha__list_ecosystem_skills`; the user confirms installation via the existing `ecosystem-skill-loader` skill (note: hyphenated name, not underscore).

## Authz Model

A v1.0 requirement, not v1.1. Single-user trust is not enough — the MCP caller identity is the authz boundary regardless of how many humans share the deployment.

### Server-derived fields

These fields are **always set server-side** from the authenticated MCP caller identity; caller-supplied values are silently overwritten:

| Field | Source | Notes |
|---|---|---|
| `Task.owner` | `caller_identity` | Stable per identity; not transferable via `tasks_update` in v1 |
| `Task.created_by` | `caller_identity` at `tasks_create` time | Audit trail; read-only after creation |
| `Task.completed_by` | `caller_identity` at `tasks_complete` time | Audit trail; read-only after completion |
| `TaskEvent.actor` | `caller_identity` at event emission | Forged actor = spoofable audit |

The only way to bypass (e.g., for admin operations) is an explicit `actor: admin` role, which is **not** in v1.

### Read-path visibility filter

Every read tool (`tasks_list`, `tasks_get`, `tasks_search`, `tasks_history`, akosha `tasks_*` tools) enforces server-side:

```
if visibility == "private" and caller_identity != task.owner:
    skip row
elif visibility == "team":
    # v1 does NOT implement team ACL — treat as private
    # team-mode is v1.1
    skip row if caller_identity != task.owner
elif visibility == "public":
    return row
```

`tasks_list(owner=None)` does NOT widen past the caller's privilege — it returns only the caller's own tasks + public ones.

### Acceptance

Every tool that reads rows must include a unit test asserting "user X cannot read user Y's `visibility=private` tasks" and "user X CAN read `visibility=public` tasks."

## Data Model

```python
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid7
from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

TASK_ID_PATTERN = r"^t-[0-9a-f]{32}$"
OWNER_PATTERN = r"^(user:[a-zA-Z0-9._@-]+|agent:[a-zA-Z0-9._:-]+)$"

class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    content: Annotated[str, Field(min_length=1, max_length=4096)]
    owner: Annotated[str | None, Field(pattern=OWNER_PATTERN)] = None  # server overwrites
    visibility: Literal["private", "team", "public"] = "private"
    status: Literal["open", "in_progress", "blocked", "done", "cancelled"] = "open"
    priority: Literal["critical", "high", "normal", "low"] = "normal"
    effort: Literal["xs", "s", "m", "l", "xl"] | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=64)]]
    parent_task_id: Annotated[str | None, Field(pattern=TASK_ID_PATTERN)] = None
    workflow_id: str | None = None
    due_at: datetime | None = None  # must be timezone-aware (validator below)
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None    # server-set
    completed_at: datetime | None = None
    completed_by: str | None = None  # server-set
    result_notes: Annotated[str | None, Field(max_length=4096)] = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_tz_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("due_at must be timezone-aware (ISO 8601 with offset)")
        return v

    @field_validator("tags")
    @classmethod
    def tags_must_include_task_discriminator(cls, v: list[str]) -> list[str]:
        if "task" not in v:
            raise ValueError('tags must include "task" discriminator')
        return v

    @field_validator("metadata")
    @classmethod
    def metadata_size_cap(cls, v: dict[str, JsonValue]) -> dict[str, JsonValue]:
        import json
        if len(json.dumps(v)) > 1024:
            raise ValueError("metadata serialized size > 1 KiB")
        return v


class UpdateTaskRequest(BaseModel):
    """Bounded updatable fields. Excludes id, created_at, created_by (immutable)."""
    content: str | None = None
    visibility: Literal["private", "team", "public"] | None = None
    status: Literal["open", "in_progress", "blocked", "done", "cancelled"] | None = None
    priority: Literal["critical", "high", "normal", "low"] | None = None
    effort: Literal["xs", "s", "m", "l", "xl"] | None = None
    due_at: datetime | None = None
    tags: list[str] | None = None
    parent_task_id: str | None = None
    result_notes: str | None = None
    metadata: dict[str, JsonValue] | None = None
    # `workflow_id` is server-set on handoff only; not user-updatable


class TaskListResult(BaseModel):
    items: list[Task]
    next_cursor: str | None = None
    total: int


class TaskHistoryResult(BaseModel):
    items: list[TaskEvent]
    next_cursor: str | None = None


class TaskEvent(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    event_type: Literal["created", "updated", "completed", "cancelled",
                       "handoff_started", "handoff_completed", "handoff_orphan"]
    actor: str | None = None  # server-set
    timestamp: datetime
    diff: dict[str, tuple[Any, Any]] | None = None  # field → (old, new)
    notes: str | None = None


class HandoffParams(BaseModel):
    """Typed parameters for dispatch. Replaces free-form `dict`."""
    timeout_seconds: int | None = None
    pool_selector: Literal["least_loaded", "round_robin", "affinity"] = "least_loaded"
    pool_name: str | None = None
    idempotency_key: str | None = None
    extra_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class HandoffResult(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    adapter: Literal["prefect", "llamaindex", "agno"]
    started_at: datetime
    pool_name: str


# Backwards-compat envelope for legacy `tags=["todo"]` rows. Returned only
# when `include_legacy=True`; v1 default is False.
class LegacyTaskRow(BaseModel):
    id: str  # reflection ID, not t-{hex}
    content: str
    tags: list[str]
    coerced: bool = True  # marker that this was a legacy row
    note: str = "Legacy store_reflection row; not a typed Task. Use tasks_create for new work."
```

### ID format

`Task.id` is the **full UUID7 with dashes + `t-` prefix**: `t-0190a3b4-c5d6-7abc-9def-1234567890ab`. Pattern: `^t-[0-9a-f]{32}$` (dashes stripped for the pattern; canonical form includes dashes).

Why full UUID7 (not the previously-considered `t-{12-14 hex}` compact form):

- 12 hex chars = 48 bits total. UUID7's first 48 bits are the timestamp; with only 12 hex there's **zero random bits** — same-millisecond creates collide, and the entire ID is a deterministic function of creation time. An attacker who knows roughly when a task was created can guess its ID and read/update/complete it. (security-auditor BLOCKING #1 caught this in v1 review.)
- The chat ergonomics concern ("`t-0190a3b4-c5d6-7abc-9def-1234567890ab` is long") is solved by the `metadata.uuid_alias` field, which stores the compact form for display in skill output, logs, and CLI summaries. **Canonical storage is the full UUID7** so the security property holds.

```python
def new_task_id() -> str:
    return f"t-{uuid7().hex}"  # canonical; full 32 hex after t-
```

A separate `display_id()` helper returns the compact form (`t-{12 hex}`) for chat/log display. The display form is NOT a valid lookup key.

### Tags

Required: `["task", "<domain>"]`. `<domain>` is free-form (e.g., `refactor`, `audit`, `infra`).

**Single source of truth**: the typed `priority` / `status` / `effort` fields. The `priority:critical|high|normal|low`, `status:open|in_progress|...`, `effort:xs|s|m|l|xl` structured-tag forms are **read-only server-side aliases derived from the typed field** — the server strips them from caller-supplied tags on write and re-emits them on read for akosha indexing parity. Callers cannot spoof `priority:critical` on a `priority="low"` task.

## Data Flow

### 1. `tasks_create` write path

```
caller (skill, subagent, direct)
   │
   ▼
session-buddy.tasks_create(...)
   │ 1. validate typed schema (Field patterns, JsonValue, size caps)
   │ 2. server-derive owner/created_by from MCP caller identity
   │ 3. strip priority:/status:/effort: tags (server-side aliases only)
   │ 4. store_reflection(content, metadata={kind=task, owner=caller,
   │                                         uuid_alias=t-{12hex}, ...},
   │                     tags=["task", <domain>, ...])
   │
   ├─► emits bodai:events  task.created{TaskCreatedPayload}
   │
   ├─► auto-coordinate skill (PostToolUse matcher) → git branch link
   │
   └─► return Task to caller
                                                    │
                                                    ▼
                                              akosha reindex (~30s lag)
```

### 2. `tasks_list` / `tasks_search` read path

```
caller
   │
   ▼
session-buddy.tasks_list(...)
   │ 1. enforce visibility filter (server-side; caller_identity check)
   │ 2. apply filters (status, owner, tag, parent_task_id, include_legacy)
   │ 3. paginate (k, cursor)
   ▼
TaskListResult{items, next_cursor, total}
   │
   │  (optional) akosha.tasks_similar_to(task_id)  for "find tasks like X"
   │  (optional) akosha.tasks_overdue_for(owner)   for "what's overdue for me"
   ▼
caller
```

**Fast read path**: for "what's on my plate?", use `tasks_list(status="open", owner=caller_identity)` — immediate, write-side. Reserve akosha queries for analytical questions where the ~30s reindex lag is acceptable.

### 3. `tasks_complete` — no auto-handoff

```
tasks_complete(task_id, result_notes=None)
   │
   ▼
session-buddy updates status=done, completed_at=now, completed_by=caller_identity
   │
   ├─► emits bodai:events  task.completed{TaskCompletedPayload}
   │
   └─► return Task to caller
   (no dispatch — caller invokes tasks_handoff_to_workflow as a separate step if desired)
```

**Why no implicit dispatch**: any path that fires `dispatch_to_pool` based on `result_notes` content (a) cannot be schema-validated by MCP, (b) is forgeable by subagents/skills processing untrusted input, and (c) violates the spec's own layering rule (session-buddy detecting dispatch intent). The skill teaches Claude to call `tasks_handoff_to_workflow` as a separate step when forward motion is desired.

### 4. `tasks_handoff_to_workflow` — explicit dispatch (the *only* dispatch edge)

```
caller (skill, user)
   │
   ▼
mahavishnu.tasks_handoff_to_workflow(task_id, adapter, params)
   │
   ├─[1]► session-buddy.tasks_get(task_id)        # fail-fast if down
   │         also: validate task.content, result_notes, metadata against
   │         the create-time schema (length cap, control-char strip,
   │         no embedded tool-call syntax); refuse dispatch if invalid
   │
   ├─[2]► dispatch_to_pool(prompt=validated_content, ...)
   │         # fail → task not updated; user retries
   │
   └─[3]► session-buddy.tasks_update(task_id,
           UpdateTaskRequest(metadata__workflow_id=returned))
              # fail → emit task.handoff_orphan event
   │
   ╔══════════════════════════════════════════════════════════════╗
   ║  try/finally wraps steps 2+3.                                ║
   ║  If asyncio.CancelledError fires between step 2 and step 3    ║
   ║  (caller disconnect), emit task.handoff_orphan so the v1.1  ║
   ║  sweeper can re-link.                                       ║
   ╚══════════════════════════════════════════════════════════════╝
```

## Event Payload Schemas

All events emitted on `bodai:events` Redis Stream are typed `BaseModel`s. Namespace: `task.*` exclusively (per mcp-integration-expert SHOULD-FIX #11; no mixed `workflow.*` or `handoff.*` prefixes).

```python
class TaskCreatedPayload(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    owner: str
    actor: str  # = owner for create
    created_at: datetime
    content_hash: str  # sha256 of content for log dedup


class TaskUpdatedPayload(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    actor: str
    updated_at: datetime
    diff: dict[str, tuple[Any, Any]]


class TaskCompletedPayload(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    actor: str
    completed_at: datetime
    has_workflow_id: bool  # whether task.workflow_id is set


class TaskHandoffStartedPayload(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    actor: str
    adapter: Literal["prefect","llamaindex","agno"]
    started_at: datetime


class TaskHandoffCompletedPayload(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    actor: str
    completed_at: datetime


class TaskHandoffOrphanPayload(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    actor: str
    reason: Literal["step_3_update_failed", "caller_disconnected",
                     "session_buddy_down_at_step_3"]
    orphaned_at: datetime
```

Each event payload is published as a single Redis Stream entry. Tag discriminators stay on the `tags` field of the underlying reflection, not in the event payload (events are ephemeral).

**Field sanitization**: all string fields in event payloads (`actor`, `content_hash` are hex-only, but other custom fields if added later) are sanitized via `serialize_event_field()`: strips control chars except `\t`, escapes Redis-Streams-sensitive bytes, normalizes newlines to `\n`. Prevents log poisoning, terminal escape injection, and consumer-parser corruption.

## Input Limits

| Field | Limit | Why |
|---|---|---|
| `content` | ≤ 4 KiB | Pydantic-OOM resistance; akosha embedding budget; Redis Stream XADD payload size |
| `result_notes` | ≤ 4 KiB | Same as content |
| `tags` (list) | ≤ 32 items | Prevents abusive tagging |
| per-tag string | ≤ 64 chars | UI rendering sanity |
| `metadata` (serialized JSON) | ≤ 1 KiB | Pydantic-validator-enforced via `field_validator` |
| `due_at` | any timezone-aware datetime | Naive datetimes rejected |
| Rate limit `tasks_create` | 60/min per caller_identity | Subagent-runaway protection |
| Rate limit `tasks_update` + `tasks_complete` | 120/min per caller_identity | Same |
| Rate limit `tasks_handoff_to_workflow` | 10/min per caller_identity | Most expensive op; tightest cap |

Limits are enforced server-side; callers exceeding get a typed `RateLimitError` (mahavishnu tool) or `{"status": "error", "error_code": "rate_limited"}` envelope (session-buddy / akosha).

## Error Handling Matrix

| Step | Failure mode | Behavior | User-visible message |
|---|---|---|---|
| `tasks_create` → session-buddy down | Connection refused / 500 | Fail-fast; no partial state | `tasks_create failed: session-buddy unreachable. Retry, or fall back to /tmp/todos-<sid>.md.` |
| `tasks_create` → caller lacks permission for `owner` reassignment | Caller-supplied owner not allowed | Server overwrites with caller_identity; logged | (silent) |
| `tasks_create` → store succeeds, akosha reindex fails | Reindex scheduled, async | Eventual consistency | (silent — read layer catches up) |
| `tasks_create` → auto-coordinate fails (git link) | Already git-isolated task | Logged; not user-blocking | `Task created; git branch link deferred.` |
| `tasks_complete` → caller not the `owner` | Authz fail | Reject; status unchanged | `tasks_complete rejected: caller is not the task owner.` |
| `tasks_handoff_to_workflow` step 1 (lookup) fails | session-buddy down | Fail-fast; no dispatch | `Cannot handoff: task <id> not found.` |
| `tasks_handoff_to_workflow` step 2 (dispatch) fails | Pool exhausted / timeout | Don't update task; user retries | `Handoff failed: pool <pool> unavailable. Task not updated.` |
| `tasks_handoff_to_workflow` step 3 (update) fails | session-buddy down after dispatch succeeded | Emit `task.handoff_orphan` (reason=step_3_update_failed); workflow proceeds | Workflow proceeds; user re-links via `tasks_update` |
| **`tasks_handoff_to_workflow` caller disconnect between step 2 and step 3** | `asyncio.CancelledError` | try/finally emits `task.handoff_orphan` (reason=caller_disconnected); workflow proceeds | Workflow proceeds in background; eventual re-link |
| `tasks_handoff_to_workflow` content validation fails | Content fails schema (length cap, control chars, tool-call syntax) | Fail-fast before dispatch | `Handoff rejected: task content fails validation: <reason>.` |
| `tasks_list` → akosha semantic query fails | Falls back to session-buddy | Degraded read quality | (silent — caller picks fallback) |
| Akosha index stale (event not yet processed) | Akosha reindex lag | Reads return pre-event state; eventually consistent | Documented in skill: "akosha queries are eventually consistent (~30s lag)" |
| Rate limit exceeded | 60/min create, 120/min update+complete, 10/min handoff | Typed rejection | `Rate limit exceeded: <limit>/min. Retry after <seconds>.` |
| Input size cap exceeded | Per-field limits above | Validation error | `Field <name> exceeds limit: <size> > <limit>` |
| `task_id` format invalid | Pattern check | Typed rejection | `Invalid task_id format: expected ^t-[0-9a-f]{32}$, got <input>.` |

### Orphan window (acknowledged in v1, sweeper in v1.1)

The `task.handoff_orphan` window between step 2 and step 3 of `tasks_handoff_to_workflow` is bounded by session-buddy's downtime OR a caller disconnect (new in v1.1). v1 documents this. v1.1 adds `akosha.tasks_find_orphaned_workflows` (sweeper) that consumes the `task.handoff_orphan` event stream and re-links tasks. Atomic handoff (rollback dispatch on update failure, or queue-and-retry) was considered and rejected for v1 — see "Rejected Alternatives".

### Error surface decision rule

To prevent drift between Bodai tools:

- **session-buddy and akosha tools return error envelopes**: `{"status": "error", "error_code": "...", "message": "...", "details": {...}}`
- **mahavishnu tools raise typed exceptions** for transient infra failures (`MahavishnuUnavailableError`, `RateLimitError`, `PoolExhaustedError`); return envelopes for logical errors (e.g., `{"status": "error", "error_code": "task_not_handoffable", ...}`)

This is a deliberate consistency break with the existing tool surface (which is itself inconsistent) — v1.1 should align the rest of Bodai to this rule.

## Cross-Repo PR Strategy

**Two PRs, hard merge order**:

| PR | Repo | Scope | Depends on |
|---|---|---|---|
| **#1** | session-buddy | `tasks_*` tools + Pydantic schemas + ID generation + the skill file (`session-buddy/.claude/skills/bodai-session-buddy-task-system/SKILL.md`) + auto-coordinate body branch | (nothing) |
| **#2** | mahavishnu | `tasks_handoff_to_workflow` adapter + orphan-event emission | **PR #1 must be merged first** |

**Pin rule**: PR #2's pyproject pins `session-buddy >= <PR1-tag>` until PR #2 lands. If the pin is too tight, the CI for PR #2 will fail until PR #1 is merged.

**Feature-flag fallback**: in case PR #2 must land without PR #1 first (emergency), `tasks_handoff_to_workflow` is registered in mahavishnu's MCP server but raises `ToolError("tasks_handoff_to_workflow not yet wired — depends on session-buddy PR #1")` until the pin is satisfied.

**`auto-coordinate` wiring**: PR #1 updates the auto-coordinate skill (in `~/.claude/skills/auto-coordinate/SKILL.md`) with the body branch for `tasks_*` entity resolution. That's a write to the user's `~/.claude/` directory, which is tracked under `~/.claude` (separate git repo) — PR #1 must be reviewed by the user (not merged without explicit approval per the project's `feedback-no-backwards-compat-pre-1.0.md` rule).

**`akosha` `tasks_*` tools**: rolled into PR #1 (session-buddy indexes the discriminator, akosha picks it up; akosha tools are 6 thin wrappers). Alternatively split into PR #3 if reviewer load warrants.

## Skill Placement

**Path:** `session-buddy/.claude/skills/bodai-session-buddy-task-system/SKILL.md`

**Skill name in frontmatter**: `bodai-session-buddy-task-system` (matches the federation materialization path; pinned to avoid duplicate-trigger ambiguity from co-location vs federation)

**Discovery paths** (any of these):
1. **Co-located in session-buddy repo** (primary). User symlinks: `ln -s ~/Projects/session-buddy/.claude/skills/bodai-session-buddy-task-system ~/.claude/skills/`.
2. **Auto-discoverable via `mcp__akosha__list_ecosystem_skills`** (NOT auto-loaded — that's `ecosystem-skill-loader` with explicit user confirmation, see below). User confirms via `ecosystem-skill-loader` (hyphenated name).
3. **Manually copied** if Akosha isn't reachable.

**Why source-repo co-location for THIS skill and not others**: all 30+ existing Bodai skills live at `~/.claude/skills/`. `task-system` is co-located in session-buddy because its source-of-truth (the `tasks_*` tool API) lives in session-buddy's `mcp/tools/`. Co-location guarantees the skill and its backing tools evolve together — no API drift. For other skills (e.g., `bodai-radar`, `auto-coordinate`), the backing tools are either too distributed or are already owned by separate repos, so the `~/.claude/skills/` location is correct. **This is an asymmetric pattern, justified per skill; not a policy of "all skills move to source repos."** A future cross-skill migration would need a separate design.

## Draft SKILL.md

```yaml
---
name: bodai-session-buddy-task-system
description: Use when the user asks to track, list, or complete work items that should survive the session — "what's on my plate", "create a todo", "show my open tasks", "what's overdue for me", "what's blocking me", "find tasks like X", "complete task t-...", or "track this for later". Routes to one of 5 backends (in-session checklist, subagent TodoWrite delegation, session-buddy tasks_*, mahavishnu workflows, akosha read) using the decision tree in the body.
allowed-tools: mcp__session-buddy__tasks_*, mcp__mahavishnu__tasks_handoff_to_workflow, mcp__akosha__tasks_*, Read, Write
---

# task-system (Bodai)

## Decision tree

| Condition | Backend |
|---|---|
| Ephemeral, single-session, <5 items | In-session markdown checklist or `/tmp/todos-<sid>.md` |
| Subagent dispatched, subagent HAS TodoWrite (`feature-dev:*`, `Explore`, `claude-security:*`) | Pass nothing; let subagent own its TodoWrite list |
| Subagent dispatched, subagent LACKS TodoWrite (`mahavishnu-orchestrator`, generic worker) | Call `mcp__session-buddy__tasks_create` BEFORE `Agent` dispatch with content = the subagent's task; pass `task_id` in the dispatch prompt so the worker can update via `tasks_complete` |
| Cross-session persistence needed | `mcp__session-buddy__tasks_create` |
| Triggers async follow-on work | `mcp__session-buddy__tasks_create` + `mcp__mahavishnu__tasks_handoff_to_workflow` (two separate calls) |
| Read-only analytics ("what's blocking me?", "tasks like X") | `mcp__akosha__tasks_blocking` / `tasks_overdue_for` / `tasks_similar_to` |
| Fast read ("what's on my plate?") | `mcp__session-buddy__tasks_list(status="open")` — immediate, write-side |

## Subagent handoff decision

```
If subagent has TodoWrite (feature-dev:*, Explore, claude-security:*):
    Pass nothing extra; let the subagent maintain its own list.
If subagent lacks TodoWrite (mahavishnu-orchestrator, generic Mahavishnu worker):
    Call mcp__session-buddy__tasks_create BEFORE Agent dispatch with content = the subagent's task.
    Pass task_id in the dispatch prompt so the worker can update via tasks_complete.
    Worker should call mcp__session-buddy__tasks_complete when done.
```

## Backend selection rules

1. **Ephemeral, single-session, <5 items** → in-session checklist. Skip the tools entirely.
2. **Subagent has TodoWrite** → pass nothing; subagent owns its list.
3. **Cross-session persistence** → `tasks_create` (session-buddy).
4. **Async follow-on work** → `tasks_create` then `tasks_handoff_to_workflow` (two calls; never implicit).
5. **Read-only analytics** → akosha `tasks_*` tools (eventual consistency ~30s).
6. **Fast read of "what's on my plate"** → `tasks_list(status="open")` from session-buddy (immediate).

## Negative trigger phrases

DO NOT use this skill for:
- Pure exploratory questions with no task to track ("how does X work?")
- Ephemeral session-local notes (use `/tmp/todos-<sid>.md`)
- Git-branch-only operations (use `auto-coordinate`)

## Schema

```
Task.id            = "t-{32 hex}"  (full UUID7 with t- prefix; compact form in metadata.uuid_alias for display)
Task.owner         = "user:<email>" | "agent:<id>"  (server-derived from caller)
Task.tags          = ["task", "<domain>", ...optional]
Task.status        = open | in_progress | blocked | done | cancelled
Task.priority      = critical | high | normal | low
Task.effort        = xs | s | m | l | xl
```

## Events

All `tasks_*` mutations emit typed events on `bodai:events` Redis Stream under the `task.*` namespace. Akosha indexes them; akosha reindex lag is ~30s.
```

The draft body is intentionally minimal — real Claude Code skill content is typically ~50-150 lines, including failure modes, examples, and cross-references to the auto-coordinate and ecosystem-skill-loader skills.

## Migration & Backwards Compatibility

### Existing `store_reflection` rows with `tags=["todo", ...]`

**Decision: leave as-is on disk.** v1's read path supports them via an explicit `include_legacy=True` flag, **defaulting to False** so legacy noise doesn't surface as ghost tasks.

### Coercion policy (defined explicitly per security-auditor SHOULD-FIX #7)

When `tasks_list(include_legacy=True)` matches a row with `tags ⊇ ["todo"]` and no `metadata.kind`:

| Field | Coerced value | Reason |
|---|---|---|
| `id` | reflection ID (not `t-{hex}`) | Can't synthesize a UUID7 retroactively |
| `owner` | `created_by` if present, else `None` | Legacy rows may have caller info but no `owner` field |
| `visibility` | `"private"` | Conservative default; safest until user claims it |
| `status`, `priority`, `effort` | field defaults | Unknown — assume middle of the road |
| `created_at`, `updated_at` | reflection timestamps | Best available |
| `content`, `tags` | as-is from reflection | Untouched |
| `_coerced: true` flag | True | Marker that this row is not a typed Task |

**Excluded from default `tasks_list()`** (which has `include_legacy=False`). User opts in explicitly. The skill teaches Claude: "if you see a row with `_coerced: true`, it's a legacy entry — claim it with `tasks_update(owner=caller_identity)` or delete it."

**Rows whose content fails the same validation as new tasks** (length cap, control chars) are rejected during coercion and logged. They do NOT appear in any list output.

### `mcp__session-buddy__store_reflection(content, tags=["todo", "<topic>"])`

**Decision: continue to work, document the upgrade path.** New `tasks_create` is recommended; old pattern is grandfathered. The skill teaches Claude to prefer `tasks_create`.

### If `TaskCreate` / `TodoWrite` come back

**Decision: stay on the new system.** It is strictly more capable:

- Cross-session persistence (Claude Code's tools die with the session)
- Server-side authz (Claude Code's tools don't enforce caller identity)
- Akosha semantic search (Claude Code's `TaskList` is filter-only)
- `auto-coordinate` git linking (not in default tools)
- Explicit `tasks_handoff_to_workflow` (not in default tools; no implicit dispatch)
- Multi-agent ownership (not in default tools)

The `task-system` skill mentions `TaskCreate` as a *legacy option*, not a recommendation.

## Test Strategy

### Unit tests (pytest)

| Test surface | Coverage |
|---|---|
| `tasks_create` Pydantic validation | All fields, all status/priority/effort enums, owner regex, tag discriminator, due_at tz-aware, metadata size cap, rate limits |
| UUID7 ID generation | Uniqueness over 1M iterations; sortability; full UUID7 with dashes; pattern validation |
| `tasks_list` filtering | by status, owner, tag, parent_task_id, `include_legacy=False/True`; pagination cursor |
| `tasks_list` visibility filter | User X cannot read User Y's `visibility="private"`; User X CAN read `visibility="public"` |
| `tasks_list` authz | `owner=None` does NOT widen past caller's privilege |
| `tasks_update` schema | All bounded fields in `UpdateTaskRequest`; rejects caller-supplied owner changes |
| `tasks_complete` invariants | status transition open→done; `completed_at` populated; `completed_by` server-set; rejects caller ≠ owner |
| `tasks_handoff_to_workflow` step 2/3 atomicity | Simulated session-buddy failure between step 2 and step 3 → `task.handoff_orphan` event emitted |
| `tasks_handoff_to_workflow` asyncio.CancelledError | Mid-flight cancellation → orphan event emitted with reason=caller_disconnected |
| `tasks_handoff_to_workflow` content validation | Refuses dispatch when content fails schema |
| ID format validation | `^t-[0-9a-f]{32}$` pattern enforced at tool boundary |
| Tag taxonomy | Server strips `priority:`/`status:`/`effort:` prefixes on write; re-emits on read |
| Event sanitization | Control chars stripped; log-injection-resistant |
| Rate limits | 60/min create, 120/min update+complete, 10/min handoff enforced |
| Error messages | Exact strings match the matrix |
| Legacy coercion | `include_legacy=True` returns `LegacyTaskRow` with `_coerced=True`; default excludes them |

### Integration tests

| Test | Coverage |
|---|---|
| Cross-session persistence | Create task in session A, query in session B (simulated by separate Task instances) |
| `auto-coordinate` trigger | `tasks_create` call emits the right PostToolUse matcher signature; auto-coordinate body branch resolves `t-{hex}` to reflection URL |
| Akosha indexing | Create task, wait 60s, `search_all_systems` returns it |
| Handoff end-to-end | Create task → handoff → verify `workflow_id` populated → verify `workflow.completed` event updates `tasks_history` |
| Concurrent updates | Two `tasks_update` calls on same task → last-write-wins with diff in history |
| Authz isolation | Two MCP caller identities in parallel; verify each can only read/write their own tasks |

### End-to-end smoke tests

| Test | Coverage |
|---|---|
| Full happy path | User creates task → auto-coordinates → reads back via `tasks_list(status="open")` (fast path) → completes → no handoff |
| Forward handoff (explicit) | User creates task → explicitly calls `mahavishnu.tasks_handoff_to_workflow` → workflow runs → task shows `workflow_id` |
| Caller disconnect mid-handoff | Start handoff, abort the MCP request between step 2 and step 3 → verify `task.handoff_orphan` event in Redis Stream |
| Backwards compat | Legacy `store_reflection(tags=["todo"])` row: `tasks_list(include_legacy=False)` excludes it; `tasks_list(include_legacy=True)` returns it with `_coerced=True` |

## Acceptance Criteria

A v1 ship is complete when **all** of the following hold:

- [ ] All 7 `tasks_*` tools callable on session-buddy as `async def` with documented typed return envelopes
- [ ] `tasks_handoff_to_workflow` callable on mahavishnu; orphan event emits on step-3 failure AND on caller-disconnect
- [ ] All 6 `tasks_*` tools callable on akosha with split `scope`/`owner` for `tasks_anomalies` and `Literal` metric for `tasks_correlate`
- [ ] `bodai-session-buddy-task-system` skill discoverable via Akosha Phase 4 federation AND co-located in `session-buddy/.claude/skills/`
- [ ] `auto-coordinate` body branch handles `tasks_*` entity resolution (not just matcher)
- [ ] **Server-side authz**: `owner`, `created_by`, `completed_by`, `actor` derived from caller identity; visibility filter enforced on read path
- [ ] ID format: `^t-[0-9a-f]{32}$` enforced at tool boundary; canonical UUID7 with dashes; compact form available as `metadata.uuid_alias`
- [ ] Event payload schemas defined as typed `BaseModel`s under `task.*` namespace; field sanitization in place
- [ ] Input limits enforced: content ≤ 4 KiB, tags ≤ 32, metadata ≤ 1 KiB, rate limits per field
- [ ] Cross-repo PR ordering: PR #2 (mahavishnu) cannot merge before PR #1 (session-buddy); pin enforced in PR #2's pyproject
- [ ] Unit test coverage ≥ 89% (per project convention from `pyproject.toml`)
- [ ] Integration tests pass against running session-buddy + mahavishnu + akosha
- [ ] `docs/task-system.md` (or equivalent) ships with PR #1, cross-linked from `CLAUDE.md` in both session-buddy and mahavishnu repos
- [ ] Existing `store_reflection(tags=["todo"])` rows queryable only via explicit `include_legacy=True`; not in default output
- [ ] E2E smoke test: create → fast read → complete → no auto-handoff (explicit path required for dispatch)

## v1.1 Follow-Ups (out of scope for v1)

| Item | Description | Effort |
|---|---|---|
| `akosha.tasks_find_orphaned_workflows` | Sweeper for `task.handoff_orphan` events; re-links tasks via `tasks_update(workflow_id)` | ~50 LOC akosha |
| Akosha `tasks_anomalies` tuning | Calibrate thresholds against real task corpus once v1 has been live for ≥30 days | Not estimated; will scope after data exists |
| Team-mode visibility (`visibility="team"`) | ACL enforcement; UI for team lists | New skill, ~1 day after v1 |
| `claude-plugins-official` submission | Once stable, publish the skill to the marketplace | Process overhead, not LOC |
| Migrate remaining Bodai tools to the error-surface decision rule (session-buddy/akosha return envelopes; mahavishnu raises) | Consistency cleanup across the ecosystem | Mechanical |

## Rejected Alternatives

| Alternative | Why rejected |
|---|---|
| Standalone `bodai-tasks` MCP server | 6th Bodai component to deploy, monitor, secure, keep fed. Cost > value vs. extending session-buddy. |
| All-in-mahavishnu (`coord_create_*` already there) | Mixes personal-todo semantics with ecosystem-orchestration semantics. `coord_*` is cross-repo Bodai issue tracking; `tasks_*` is personal/cross-session work-items. Different concerns. |
| All-in-session-buddy (session-buddy gains mahavishnu dependency) | Wrong layering — session-buddy shouldn't know about pool dispatch. The HANDOFF magic-prefix attempt to add this was rejected as a layering violation (architecture-council BLOCKING #1) and a prompt-injection vector (security-auditor BLOCKING #2). |
| New `bodai-task-system` monorepo | New-repo setup is itself a 6-week project. Co-locating the skill in session-buddy + Akosha federation solves the same problem at lower cost. |
| Direct Akosha write path | Akosha is intelligence/read-path; session-buddy is the system of record. Adding a write path to akosha duplicates reflection storage and splits the source of truth. Akosha already indexes session-buddy reflections — that's the right asymmetric relationship. |
| Dhara adapter registration for `task-system` | Dhara adapters are runtime-swappable capability providers (like pool adapters). Task management isn't a swappable capability — it's a system-of-record concern. Using Dhara here would also fail the MCP discoverability test (adapter tools don't publish through `mcp__akosha__list_skills`). |
| Atomic handoff (rollback on update failure OR queue-and-retry) | Inverts `dispatch_to_pool`'s C-NEW-5 fire-and-forget semantics. Adds latency tax on every handoff to solve a rare, bounded orphan window. Orphan sweeper in v1.1 is the correct trade-off. |
| Compact UUID7 (`t-{12-14 hex}`) as canonical | The 12-hex form gives zero random bits; IDs are deterministic from creation time, breaking the security property. Compact form is now `metadata.uuid_alias` for display only. |
| UUID4 short IDs | Loses k-sortability. UUID7 strictly better. |
| `DISABLE_TELEMETRY=1` workaround to recover `TaskCreate` | Per anthropics#80305, costs 1M context, `/remote-control`, `--bg`, Agent View, 1h prompt-cache TTL, remote killswitches. The new system is more capable than what we'd recover. |
| HANDOFF magic-string in `result_notes` | Schema-undiscoverable, layer-violating, prompt-injectable, accidentally-triggerable. Replaced by explicit `tasks_handoff_to_workflow` call. |
| Implicit dispatch from `tasks_complete` | Same problem class as HANDOFF magic-string; removed entirely. |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `auto-coordinate` matcher + body branch conflicts with existing triggers | Low | Medium | Body change is reversible; matcher update is one line; tested in isolation |
| Akosha reindex lag makes `tasks_search` feel "missing data" | Medium | Low | Document the lag in skill; fast read path documented; `tasks_list` from session-buddy is always immediate |
| Cross-repo merge order violation (PR #2 lands before PR #1) | Low | High | Pin `session-buddy >= <PR1-tag>` in PR #2's pyproject; CI fails otherwise |
| Caller-disconnect mid-handoff leaves orphan workflows | Medium | Low | try/finally in `tasks_handoff_to_workflow` emits `task.handoff_orphan`; v1.1 sweeper closes the loop |
| Authz bypass via crafted task_id (predictable ID guessing) | Low | High | Full UUID7 with 64 random bits (after time prefix) makes ID guessing computationally infeasible; pattern validation at tool boundary |
| Subagent claims tasks owned by another agent via `tasks_update(owner=...)` | Low | High | Server rejects caller-supplied owner changes; `tasks_update` cannot mutate owner in v1 |
| Legacy `tags=["todo"]` rows surface as ghost tasks | Medium | Low | `include_legacy=False` default; explicit opt-in via flag; coercion policy documents behavior |
| `metadata: dict[str, JsonValue]` strict-mode rejects existing payloads with non-JSON values | Medium | Medium | Migration window with soft-validation; tighten validator in v1.1 |
| Caller-supplied `priority:`/`status:`/`effort:` tag spoofing | Low | Medium | Server strips structured prefixes on write; re-emits on read |
| Bodai ecosystem error-surface inconsistency perpetuated | Medium | Low | v1 pins the rule for new tools; v1.1 migrates existing |

## References

- anthropics/claude-code issue [#80487](https://github.com/anthropics/claude-code/issues/80487) — server-side task-tools gate; no client override
- anthropics/claude-code issue [#80305](https://github.com/anthropics/claude-code/issues/80305) — `CLAUDE_CODE_ENABLE_TASKS` ineffective; only `DISABLE_TELEMETRY=1` works (with trade-offs)
- anthropics/claude-code issue [#80401](https://github.com/anthropics/claude-code/issues/80401) — Task tools intermittently unregister
- CLAUDE.md `Memory Routing` section — distinguishes `user`/`feedback` (CC memory) from `project`/`reference` (Session-Buddy `store_reflection`)
- CLAUDE.md `Crackerjack-Compliant Code` — `from __future__ import annotations`, Python 3.14, hard limits (100 char line, 10 args, 89% coverage)
- Bodai CLAUDE.md `SessionBuddyPool` and `MahavishnuPool` — `dispatch_to_pool` is C-NEW-5 fire-and-forget
- Existing skill precedent: `~/.claude/skills/bodai-radar/SKILL.md` (referenced from `docs/specs/2026-04-14-bodai-radar-design.md`)
- Review artifacts: 4-agent multi-lens review (MCP / Bodai architecture / Claude Code skill UX / Security) — see commit history
