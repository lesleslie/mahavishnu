---
status: draft
role: implementation
topic: tooling
date: 2026-09-29
last_reviewed: 2026-09-29
superseded_by: null
blocks_on: []
---

# Bodai Task System Design

## **Goal:** A unified cross-component replacement for Claude Code's default `TaskCreate` / `TodoWrite` tool family, currently disabled by Anthropic's `tengu_vellum_ash` server-side gate on `MiniMax-M3`, `Opus 4.8`, `Sonnet 5`, and `Fable 5`. Tasks persist across sessions, link to git branches via `auto-coordinate`, hand off to mahavishnu workflows, and surface analytics through akosha. **Architecture:** Three-Bodai-component split: session-buddy owns CRUD (write path), mahavishnu owns workflow handoff (intent path), akosha owns read/analytics (intelligence path). Plus a Claude Code skill for UX. No new MCP server. **Tech Stack:** Python 3.14 (target per `CLAUDE.md`), FastMCP, Pydantic v2, `uuid.uuid7()`, existing Bodai WebSocket event bus (`bodai:events` Redis Stream), existing Akosha reindex, existing `auto-coordinate` skill.

## Context

The default Claude Code `TaskCreate` / `TodoWrite` / `TaskUpdate` / `TaskList` / `TaskGet` tools are unavailable in this session because:

1. The model proxy at `https://api.minimax.io/anthropic` does not advertise `TodoWrite` in the tool schema.
2. Claude Code's "Background Tasks" feature is gated by Anthropic's remote-config flag `tengu_vellum_ash` against a model allowlist (`claude-opus-4-8`, `claude-sonnet-5`, `claude-fable-5`). Per issue [anthropics/claude-code#80487](https://github.com/anthropics/claude-code/issues/80487) the gate has no client-side override. Per issue #80305 the only known workaround (`DISABLE_TELEMETRY=1`) costs 1M context, `/remote-control`, `--bg`, Agent View, 1h prompt-cache TTL, and remote killswitches.

This is not a temporary outage — the design ships a permanent Bodai-native replacement that is strictly more capable than the default tools (cross-session persistence, git-branch linking via `auto-coordinate`, semantic search via akosha, workflow handoff via mahavishnu).

## Goals & Non-Goals

### Goals

1. **Cross-session persistence** — tasks survive Claude Code session restarts
2. **Git-branch linking** — tasks get auto-linked to the working branch via `auto-coordinate` skill
3. **Multi-step orchestration handoff** — `tasks_complete` may trigger `dispatch_to_pool` for follow-on work
4. **Semantic read surface** — akosha powers "what's blocking me?", "tasks like this", "tasks overdue for me"
5. **Subagent compatibility** — works from subagents dispatched via `Agent` tool, even when those subagents lack `TodoWrite` themselves
6. **Backwards-compat with existing pattern** — `mcp__session-buddy__store_reflection(content, tags=["todo", ...])` continues to work; new `tasks_*` tools are a strictly-typed layer above it

### Non-Goals (v1)

- **Not a Claude Code marketplace plugin.** Skills yes, but no `claude-plugins-official` submission in v1.
- **Not a stand-alone MCP server.** Reuses existing session-buddy, mahavishnu, akosha servers. (`bodai-tasks` MCP considered and rejected.)
- **Not atomic handoff.** Orphan window acknowledged; sweeper deferred to v1.1.
- **Not multi-tenant team features.** Schema supports `visibility` but no UI / sharing / permissions in v1.
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
  ┌──────────┐       ┌──────────────┐     ┌────────────┐     ┌────────────┐
  │ session- │       │ mahavishnu   │     │ akosha     │     │ auto-coord │
  │ buddy    │       │              │     │            │     │ (existing) │
  │ WRITE    │       │ ORCHESTRATE  │     │ ANALYZE    │     │ GIT-LINK   │
  │ CRUD     │       │ handoff to   │     │ read/      │     │ existing   │
  │          │       │ workflows    │     │ analytics  │     │ skill      │
  └──────────┘       └──────────────┘     └────────────┘     └────────────┘
        │                  │                   │
        │ emits:           │ dispatches:        │ reads via:
        │ bodai:events     │ bodai:events       │ semantic index
        │ Redis Stream     │ Redis Stream       │ (already indexed)
        ▼                  ▼                   ▼
   [task.created]      [workflow.dispatched]   [search_all_systems]
   [task.updated]      [handoff.orphan]        [analyze_trends]
   [task.completed]                           [correlate_systems]
```

Each component does what it's best at. session-buddy already persists reflections; mahavishnu already has the pool/dispatch surface; akosha already has the semantic and correlation primitives. This design composes them rather than building a parallel system.

## Components & Responsibilities

### session-buddy (write path — new tools)

```python
# All under existing mcp__session-buddy__ namespace
mcp.tool() def tasks_create(content, tags, owner=None, due=None,
                            priority="normal", effort=None,
                            parent_task_id=None) -> Task: ...
mcp.tool() def tasks_list(status="open", owner=None, tag=None,
                          k=20, cursor=None) -> list[Task]: ...
mcp.tool() def tasks_get(task_id) -> Task: ...
mcp.tool() def tasks_update(task_id, **fields) -> Task: ...
mcp.tool() def tasks_complete(task_id, result_notes=None) -> Task: ...
mcp.tool() def tasks_search(query, k=10) -> list[Task]: ...
mcp.tool() def tasks_history(task_id) -> list[TaskEvent]: ...
```

Backed by `store_reflection` with `metadata.kind = "task"` discriminator. Reuses the existing reflection indexing so akosha's semantic search, anomaly detection, and correlation work for free.

### mahavishnu (orchestration handoff — new tool)

```python
# Under existing mcp__mahavishnu__ namespace
@mcp.tool()
async def tasks_handoff_to_workflow(
    task_id: str,
    adapter: Literal["prefect", "llamaindex", "agno"] = "prefect",
    params: dict | None = None,
    timeout: int | None = None,
) -> HandoffResult:
    """Dispatch task.content as a workflow; store workflow_id on task.

    Three sequential steps: lookup task, dispatch_to_pool, update task.
    See error handling matrix for failure semantics per step.
    """
```

Calls `dispatch_to_pool` internally. No new transport — reuses existing `bodai:events` and `workflow:*` WebSocket channels.

### akosha (read/analysis path — new tools, full 6)

```python
mcp.tool() def tasks_similar_to(task_id, k=10) -> list[Task]: ...
mcp.tool() def tasks_blocking(owner) -> list[Task]: ...
mcp.tool() def tasks_overdue_for(owner) -> list[Task]: ...
mcp.tool() def tasks_velocity(owner, window="7d") -> VelocityStats: ...
mcp.tool() def tasks_anomalies(scope="all|owner:<id>") -> list[Anomaly]: ...
mcp.tool() def tasks_correlate(metric="completion_rate",
                               window="30d") -> CorrelationReport: ...
```

All 6 ship in v1 per design decision. No new storage engine — these are thin query shapes over the existing akosha semantic index of session-buddy reflections.

### `auto-coordinate` skill (existing, one-line extension)

The existing skill reacts to `coord_create_issue`, `coord_create_todo`, `coord_close_issue`. Add `tasks_create` and `tasks_complete` to the matcher list (one-line frontmatter change). The skill already knows how to link tasks to git branches; we just expand what triggers it.

### `task-system` skill (new, UX layer)

Single `SKILL.md` in `session-buddy/.claude/skills/task-system/`. Names the 4 backends (in-session checklist, subagent TodoWrite delegation, session-buddy tasks, mahavishnu workflows, akosha read), gives Claude a decision tree for "use which when," and documents the `tags=["task", "<domain>"]` schema.

The skill is auto-discoverable through Akosha's Phase 4 skill federation (`ecosystem_skill_loader` materializes it to `~/.claude/skills/bodai-session-buddy-task-system/` on first reference).

## Data Model

```python
class Task(BaseModel):
    id: str                          # "t-{12-14 hex chars of UUID7}"
    content: str                     # user-facing description
    owner: str | None                # "user:les@wedgwoodwebworks.com" or "agent:<id>" or None
    visibility: Literal["private","team","public"] = "private"
    status: Literal["open","in_progress","blocked","done","cancelled"] = "open"
    priority: Literal["critical","high","normal","low"] = "normal"
    effort: Literal["xs","s","m","l","xl"] | None = None
    tags: list[str]                  # canonical: ["task", "<domain>", ...optional]
    parent_task_id: str | None      # sub-task pointer
    workflow_id: str | None         # populated by tasks_handoff_to_workflow
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    completed_at: datetime | None
    completed_by: str | None
    result_notes: str | None
    metadata: dict[str, Any]         # escape hatch (always includes uuid_full)

class TaskEvent(BaseModel):
    task_id: str
    event_type: Literal["created","updated","completed","cancelled","handoff"]
    actor: str | None
    timestamp: datetime
    diff: dict[str, Any] | None      # field-level changes for updated/completed
    notes: str | None
```

### ID format

`t-{12-14 hex chars of uuid7().hex}` — compact UUID7 with `t-` prefix. Example: `t-0190a3b4c5d6`. Reasoning:

- UUID7 is k-sortable (lexicographic = chronological)
- 48-bit time prefix + ~16-24 bits random → 4B+ distinct IDs per millisecond
- `t-` prefix separates task namespace from `wf-` (workflow), `r-` (reflection), etc.
- Short enough for chat, scripts, commit messages

Full UUID7 always stored in `metadata.uuid_full` for debugging / cross-system correlation.

### Tags

Required: `["task", "<domain>"]` where `<domain>` is free-form (e.g., `refactor`, `audit`, `infra`).

Optional structured tags validated by the Pydantic model:
- `priority:critical|high|normal|low`
- `status:open|in_progress|blocked|done|cancelled` (mirrors the dedicated `status` field; either is acceptable)
- `effort:xs|s|m|l|xl`

The required `task` tag is the discriminator — it lets akosha filter for `kind:task` reflections without inspecting `metadata`.

## Data Flow

### 1. `tasks_create` write path

```
caller (skill, subagent, direct)
   │
   ▼
session-buddy.tasks_create(...)
   │
   ├─► store_reflection(content, metadata={kind=task, ...}, tags=["task", domain])
   │       │
   │       └─► emits bodai:events  task.created{task_id, owner, content}
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
session-buddy.tasks_list(...)  ──► filter+paginate ──► Task[]
   │                                  │
   │  (optional) akosha.tasks_similar_to(task_id)  for "find tasks like X"
   │  (optional) akosha.tasks_overdue_for(owner)   for "what's overdue for me"
   ▼
caller
```

### 3. `tasks_complete` with conditional handoff

```
tasks_complete(task_id, result_notes=None)
   │
   ▼
session-buddy updates status=done, completed_at=now
   │
   ├─► emits bodai:events  task.completed{task_id, workflow_id?}
   │
   └─► if workflow_id present AND `result_notes` starts with the literal token `HANDOFF: `:
        strip the `HANDOFF: ` prefix to recover the next-prompt body, then:
        mahavishnu.tasks_handoff_to_workflow(task_id, prompt_body=stripped, ...)
            │
            └─► dispatch_to_pool(prompt=stripped + task context) → returns workflow_id
                  │
                  └─► session-buddy.tasks_update(task_id, metadata.workflow_id=...)
```

The `HANDOFF: ` prefix is the anti-flap guard. Default `tasks_complete` records the result of *current* work; the prefix explicitly signals *forward* intent and recovers the next-prompt body. This prevents infinite re-dispatch loops while keeping the API one-call (no separate `tasks_handoff` call required after `tasks_complete`).

### 4. `tasks_handoff_to_workflow` direct call

```
caller (skill, user)
   │
   ▼
mahavishnu.tasks_handoff_to_workflow(task_id, adapter, params)
   │
   ├─[1]► session-buddy.tasks_get(task_id)        # if fails → fail-fast
   ├─[2]► dispatch_to_pool(prompt=task.content+context, adapter, params)
   │        # if fails → task not updated; user can retry
   └─[3]► session-buddy.tasks_update(task_id, metadata.workflow_id=returned)
            # if fails → workflow IS running; emit handoff.workflow_orphan event
```

## Error Handling Matrix

| Step | Failure mode | Behavior | User-visible message |
|---|---|---|---|
| `tasks_create` → session-buddy down | Connection refused / 500 | Fail-fast; no partial state | `tasks_create failed: session-buddy unreachable. Retry, or fall back to /tmp/todos-<sid>.md.` |
| `tasks_create` → store succeeds, akosha reindex fails | Reindex scheduled, async | Eventual consistency | (silent — read layer catches up) |
| `tasks_create` → auto-coordinate fails (git link) | Already git-isolated task | Logged; not user-blocking | `Task created; git branch link deferred.` |
| `tasks_complete` → dispatch fails (handoff path) | Two-step atomicity | Mark complete in session-buddy first, attempt dispatch in try/except; on dispatch failure set `metadata.handoff_failed=true` | `Task completed; handoff to <workflow> failed: <err>. See tasks_history.` |
| `tasks_handoff_to_workflow` step 1 (lookup) fails | session-buddy down | Fail-fast; no dispatch | `Cannot handoff: task <id> not found.` |
| `tasks_handoff_to_workflow` step 2 (dispatch) fails | Pool exhausted / timeout | Don't update task; user retries | `Handoff failed: pool <pool> unavailable. Task not updated.` |
| `tasks_handoff_to_workflow` step 3 (update) fails | session-buddy down after dispatch succeeded | Workflow IS running, just not linked | Emit `handoff.workflow_orphan` event; workflow proceeds; user re-links via `tasks_update` |
| `tasks_list` → akosha semantic query fails | Falls back to session-buddy | Degraded read quality | (silent — caller picks fallback) |
| Akosha index stale (event not yet processed) | Akosha reindex lag | Reads return pre-event state; eventually consistent | Documented in skill: "akosha queries are eventually consistent (~30s lag)" |

### Orphan window (acknowledged in v1, sweeper in v1.1)

The `handoff.workflow_orphan` window between step 2 and step 3 of `tasks_handoff_to_workflow` is bounded by session-buddy's downtime. v1 documents this. v1.1 adds `akosha.tasks_find_orphaned_workflows` (sweeper) that consumes the `handoff.workflow_orphan` event stream and re-links tasks. Atomic handoff (rollback dispatch on update failure, or queue-and-retry) was considered and rejected for v1 — see "Rejected alternatives" below.

## Cross-Repo PR Strategy

Two coordinated PRs, reviewed in parallel:

| PR | Repo | Scope | Files (approx) |
|---|---|---|---|
| **#1** | session-buddy | `tasks_*` tools + Pydantic schema + ID generation + the skill file (`session-buddy/.claude/skills/task-system/SKILL.md`) | ~5 files, ~400 LOC |
| **#2** | mahavishnu | `tasks_handoff_to_workflow` adapter (depends on PR #1's API) | ~2 files, ~80 LOC |

`auto-coordinate` skill matcher update: one-line frontmatter change, included in PR #1.

`akosha` `tasks_*` tools: rolled into PR #1 (session-buddy indexes the discriminator, akosha picks it up; akosha tools are 6 thin wrappers). Alternatively split into PR #3 if reviewer load warrants.

## Skill Placement

**Path:** `session-buddy/.claude/skills/task-system/SKILL.md`

Discovery paths (any of these):
1. **Co-located in session-buddy repo** (primary). Symlinked by the user into `~/.claude/skills/`.
2. **Auto-loaded via Akosha Phase 4 federation** — `mcp__akosha__list_ecosystem_skills` surfaces session-buddy's published skills; `ecosystem_skill_loader` materializes them.
3. **Manually copied** — user can copy `session-buddy/.claude/skills/task-system/SKILL.md` to `~/.claude/skills/` if Akosha isn't reachable.

Co-location + federation avoids the versioning problem of a separate `bodai-task-system` repo (which version of session-buddy's `tasks_*` API does the skill match?).

## Migration & Backwards Compatibility

### Existing `store_reflection` rows with `tags=["todo", ...]`

**Decision: leave as-is.** Existing rows are valid reflections; converting them is a destructive migration with no clear benefit. The new `tasks_*` tools read BOTH:

- Rows with `metadata.kind = "task"` → returned as Task objects
- Rows with `tags ⊇ ["todo"]` and no `metadata.kind` → returned as Task-like objects (Pydantic coercion with default values)

This means existing data continues to be queryable through the new API without migration.

### `mcp__session-buddy__store_reflection(content, tags=["todo", "<topic>"])`

**Decision: continue to work, document the upgrade path.** The new `tasks_create` is the recommended path going forward; the old pattern is grandfathered. The `task-system` skill teaches Claude "use `tasks_create`; if you see `store_reflection(tags=["todo"])` it's the legacy equivalent."

### If `TaskCreate` / `TodoWrite` come back

**Decision: stay on the new system.** It is strictly more capable:

- Cross-session persistence (Claude Code's tools die with the session)
- Akosha semantic search (Claude Code's `TaskList` is filter-only)
- `auto-coordinate` git linking (not in default tools)
- `tasks_handoff_to_workflow` (not in default tools)
- Multi-agent ownership (not in default tools)

The `task-system` skill will mention `TaskCreate` as a *legacy option*, not a recommendation.

## Test Strategy

### Unit tests (pytest)

| Test surface | Coverage |
|---|---|
| `tasks_create` Pydantic validation | All fields, all status/priority/effort enums, owner format, tag discriminator |
| UUID7 generation | Uniqueness over 100k iterations; sortability; collision rate |
| `tasks_list` filtering | by status, owner, tag, parent_task_id; pagination cursor |
| `tasks_search` semantic | delegates to `store_reflection` semantic; returns Task-shaped objects |
| `tasks_complete` invariants | status transition open→done; `completed_at` populated; `result_notes` optional |
| `tasks_handoff_to_workflow` step 2/3 atomicity | simulated session-buddy failure between dispatch and update → orphan event emitted |
| Error messages | exact strings match the matrix above |

### Integration tests

| Test | Coverage |
|---|---|
| Cross-session persistence | Create task in session A, query in session B (simulated by separate Task instances) |
| `auto-coordinate` trigger | `tasks_create` call emits the right PostToolUse matcher signature |
| Akosha indexing | Create task, wait 60s, `search_all_systems` returns it |
| Handoff end-to-end | Create task → handoff → verify `workflow_id` populated → verify `workflow.completed` event updates `tasks_history` |
| Concurrent updates | Two `tasks_update` calls on same task → last-write-wins with diff in history |

### End-to-end smoke tests

| Test | Coverage |
|---|---|
| Full happy path | user creates task → auto-coordinates → reads back via akosha semantic search → completes → no handoff |
| Forward handoff | user creates task → calls handoff → workflow runs → completes task with `result_notes` → history shows workflow linkage |
| Backwards compat | legacy `store_reflection(tags=["todo"])` row is readable via `tasks_search` |

## Acceptance Criteria

A v1 ship is complete when **all** of the following hold:

- [ ] All 7 `tasks_*` tools callable on session-buddy with documented return types
- [ ] `tasks_handoff_to_workflow` callable on mahavishnu; orphan event emits on step-3 failure
- [ ] All 6 `tasks_*` tools callable on akosha, querying the indexed `kind:task` reflections
- [ ] `task-system` skill discoverable via Akosha Phase 4 federation AND co-located in `session-buddy/.claude/skills/`
- [ ] `auto-coordinate` matcher reacts to `tasks_create` and `tasks_complete`
- [ ] Unit test coverage ≥ 89% (per project convention from `pyproject.toml`)
- [ ] Integration tests pass against running session-buddy + mahavishnu + akosha
- [ ] `docs/task-system.md` (or equivalent) ships with PR #1, cross-linked from `CLAUDE.md` in both session-buddy and mahavishnu repos
- [ ] Existing `store_reflection(tags=["todo"])` rows still queryable through `tasks_*` API
- [ ] E2E smoke test: create → akosha semantic search → complete → history shows full lifecycle

## v1.1 Follow-Ups (out of scope for v1)

| Item | Description | Effort |
|---|---|---|
| `akosha.tasks_find_orphaned_workflows` | Sweeper for `handoff.workflow_orphan` events; re-links tasks | ~50 LOC akosha |
| Akosha `tasks_anomalies` tuning | Calibrate thresholds against real task corpus once v1 has been live for ≥30 days | Not estimated; will scope after data exists |
| Multi-tenant visibility | Team / public modes; UI; sharing | New skill, ~1 day after v1 |
| `claude-plugins-official` submission | Once stable, publish the skill to the marketplace | Process overhead, not LOC |
| Full UUID7 with dashes as canonical | Currently only compact form is canonical; switch if needed for cross-system traceability | Mechanical; 2-line change in `id_generator` |

## Rejected Alternatives

| Alternative | Why rejected |
|---|---|
| Standalone `bodai-tasks` MCP server | 6th Bodai component to deploy, monitor, secure, keep fed. Cost > value vs. extending session-buddy. |
| All-in-mahavishnu (`coord_create_*` already there) | Mixes personal-todo semantics with ecosystem-orchestration semantics. `coord_*` is cross-repo Bodai issue tracking; `tasks_*` is personal/cross-session work-items. Different concerns. |
| All-in-session-buddy (session-buddy gains mahavishnu dependency) | Wrong layering — session-buddy shouldn't know about pool dispatch. |
| New `bodai-task-system` monorepo | New-repo setup is itself a 6-week project. Co-locating the skill in session-buddy + Akosha federation solves the same problem at lower cost. |
| Atomic handoff (rollback on update failure OR queue-and-retry) | Inverts `dispatch_to_pool`'s C-NEW-5 fire-and-forget semantics. Adds latency tax on every handoff to solve a rare, bounded orphan window. Orphan sweeper in v1.1 is the correct trade-off. |
| Full UUID7 (no prefix) | Mixes with workflow IDs, reflection IDs. Hard to grep. |
| UUID4 short IDs | Loses k-sortability. UUID7 strictly better. |
| `DISABLE_TELEMETRY=1` workaround to recover `TaskCreate` | Per anthropics#80305, costs 1M context, `/remote-control`, `--bg`, Agent View, 1h prompt-cache TTL, remote killswitches. The new system is more capable than what we'd recover. |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `auto-coordinate` matcher conflicts with existing triggers | Low | Medium | One-line matcher change is reversible; can disable per-call |
| Akosha reindex lag makes `tasks_search` feel "missing data" | Medium | Low | Document the lag in skill; surface staleness in returned metadata |
| session-buddy schema migration of existing rows breaks `tasks_search` | Low | High | v1 reads BOTH metadata.kind=task rows AND legacy tags=[todo] rows; verified in acceptance criteria |
| Mahavishnu `dispatch_to_pool` API changes mid-implementation | Low | Medium | Pin mahavishnu version in PR #1; spec calls out the dependency |
| `tasks_handoff_to_workflow` orphan window in v1 catches user off-guard | Medium | Low | Document the window in skill and skill frontmatter; v1.1 sweeper closes it |

## References

- anthropics/claude-code issue [#80487](https://github.com/anthropics/claude-code/issues/80487) — server-side task-tools gate; no client override
- anthropics/claude-code issue [#80305](https://github.com/anthropics/claude-code/issues/80305) — `CLAUDE_CODE_ENABLE_TASKS` ineffective; only `DISABLE_TELEMETRY=1` works (with trade-offs)
- anthropics/claude-code issue [#80401](https://github.com/anthropics/claude-code/issues/80401) — Task tools intermittently unregister
- CLAUDE.md `Memory Routing` section — distinguishes `user`/`feedback` (CC memory) from `project`/`reference` (Session-Buddy `store_reflection`)
- CLAUDE.md `Crackerjack-Compliant Code` — `from __future__ import annotations`, Python 3.14, hard limits (100 char line, 10 args, 89% coverage)
- Bodai CLAUDE.md `SessionBuddyPool` and `MahavishnuPool` — `dispatch_to_pool` is C-NEW-5 fire-and-forget
- Existing skill precedent: `~/.claude/skills/bodai-radar/SKILL.md` (referenced from `docs/superpowers/specs/2026-04-14-bodai-radar-design.md`)
