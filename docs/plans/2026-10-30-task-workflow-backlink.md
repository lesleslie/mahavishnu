---
status: active
role: implementation
kind: plan
date: 2026-10-30
last_reviewed: 2026-10-30
superseded_by: null
topic: task-workflow-backlink
title: "Task → Workflow Back-Link — typed channel, durable dispatch, and wiring"
requirements:
  - id: REQ-001
    title: "session-buddy exposes tasks_link_workflow as the sole writer of Task.workflow_id"
    description: "A dedicated typed MCP tool writes the field; the generic UpdateTaskRequest.metadata bag cannot reach it."
  - id: REQ-002
    title: "The link is owner-scoped and link-once"
    description: "tasks_link_workflow requires Permission.WRITE, passes the visibility filter, and refuses a second link to a different workflow_id."
  - id: REQ-003
    title: "The link records provenance"
    description: "workflow_linked_at and workflow_linked_by are server-written first-class Task fields."
  - id: REQ-004
    title: "workflow_id is validated against the fleet's canonical pattern"
    description: "^[A-Za-z0-9._-]{1,128}$ — the same pattern mahavishnu's _workflow_id_guard enforces."
  - id: REQ-005
    title: "Caller metadata can never reach a server-set field"
    description: "Regression pin on the metadata bag's inability to forge workflow_id."
  - id: REQ-006
    title: "The handoff back-link step uses the typed channel"
    description: "mahavishnu's step 3 calls tasks_link_workflow instead of tasks_update(metadata={...})."
  - id: REQ-007
    title: "The dispatch step produces a real workflow_id"
    description: "Step 2 dispatches through the durable-workflow path, which is the only path that returns a workflow_id."
  - id: REQ-008
    title: "The handoff tool and the sweeper bind a real session-buddy client"
    description: "Both seams are bound at registration/lifespan time instead of raising NotImplementedError or returning None."
  - id: REQ-009
    title: "The orphan sweeper converges"
    description: "It skips an already-linked orphan and links an unlinked one exactly once."
---

# Task → Workflow Back-Link — typed channel, durable dispatch, and wiring

**Date:** 2026-10-30
**Status:** active
**Owner:** Claude (session `fbc2e53b`)
**Scope:** `session-buddy` (field owner) + `mahavishnu` (dispatch edge)
**Design:** [`docs/specs/2026-10-30-task-workflow-backlink-design.md`](../specs/2026-10-30-task-workflow-backlink-design.md)
**Purpose:** make the task→workflow back-link real, and make the dispatch edge able to produce a `workflow_id` at all.

---

## 1. Outcome

A session-buddy task that has been handed off comes back from `tasks_get` with a
populated `workflow_id` and its provenance (`workflow_linked_at`, `workflow_linked_by`),
and keeps them across a session-buddy restart.

**Success signal:** a live task is created, handed off through
`mcp__mahavishnu__tasks_handoff_to_workflow`, and `tasks_get` returns
`workflow_id == "<the durable workflow id>"` with `workflow_linked_at` and
`workflow_linked_by` populated — then returns the same values after a
`launchctl kickstart -k` restart of session-buddy.

## 2. Goals

1. `Task.workflow_id` has exactly one writer — a typed, owner-scoped channel — and the
   generic metadata bag provably cannot reach it.
2. The dispatch edge produces a real, pollable `workflow_id`.
3. The handoff tool and the orphan sweeper have real, bound session-buddy clients.
4. The orphan sweeper converges: it skips a linked orphan and re-links an unlinked one
   exactly once.
5. Both repos' specs and skill catalogs describe the contract that actually exists.

## 3. Non-Goals

1. Turning on session-buddy's auth gate, adding a scope to `mcp_common.auth.permissions`,
   or publishing mcp-common. A fleet-wide posture change — a separate decision.
2. Changing `UpdateTaskRequest.metadata`'s replace-vs-merge semantics. Real wart,
   orthogonal to this contract.
3. Adding a `dispatch_to_pool` tool to mahavishnu, despite stale references to it in
   CLAUDE.md and agent descriptions.
4. Changing the pool router's contract or `pool_route_execute`.
5. Changing the `task.handoff_orphan` event envelope.

## 4. Current Findings

Full detail and evidence in the design doc §1. Summary:

| # | Break | Location |
|---|---|---|
| B1 | `UpdateTaskRequest(metadata__workflow_id=...)` — the spec's write channel — was never implemented. One grep hit, in a docstring. | `session-buddy` `tasks_models.py:268` |
| B2 | `tasks_update` never persisted `metadata`; `_build_task` reads `workflow_id` from a top-level sidecar key nothing writes. | `session-buddy` `tasks_tools.py:442`, `:834` |
| B3 | Step 3 wrote `tasks_update(metadata={"workflow_id": ...})` → nested bag → `task.workflow_id` stays `None`. | `mahavishnu` `tasks_handoff.py:504` |
| B4 | Handoff registered with no client and no dispatch fn → died at step 1, misreported as "task not found". Runtime-probed. | `mahavishnu` `server_core.py:1563` |
| B5 | Step 2 calls `pool_route_execute`, which returns no `workflow_id` (none exists in `mahavishnu/pools/`). The spec's `dispatch_to_pool` is a phantom tool. | `mahavishnu` `tasks_handoff.py:472` |

## 4.5 Requirements

Declared in the frontmatter (that is where `scripts/audit_requirements.py` reads
declarations from). Each ID is referenced in code with `# req: REQ-NNN` /
`# Implements: REQ-NNN` / `@pytest.mark.req(["REQ-NNN"])`.

Session-buddy implements REQ-001 … REQ-005; mahavishnu implements REQ-006 … REQ-009 and
*depends on* REQ-001 … REQ-004 (its step 3 and the sweeper are consumers of that
contract, so the dependency is referenced in mahavishnu's code too).

---

## 5. Implementation Phases

### Phase 1: session-buddy — the typed link channel

**Goal:** `Task.workflow_id` gains exactly one writer.

**Tasks:**
- `tasks_models.py`: add `workflow_linked_at: datetime | None` and
  `workflow_linked_by: str | None` to `Task`; add `WORKFLOW_ID_PATTERN` matching
  `^[A-Za-z0-9._-]{1,128}$`; update `HandoffResult` (drop `pool_name`, add `status: str`
  and `repos_processed: int`) to match the durable-workflow edge.
- `tasks_tools.py`: implement `tasks_link_workflow(ctx, task_id, workflow_id)` —
  `Permission.WRITE`, visibility filter, link-once, pattern validation, persist
  `workflow_id` + provenance to the sidecar, append history, emit the `task.updated`
  diff. Register it in `register_tasks_tools`.
- `tasks_tools.py::_build_task`: populate the two provenance fields.
- `tasks_tools.py::_persist_task_update`: write `workflow_linked_at` / `workflow_linked_by`.
- Skill catalog `bodai-session-buddy-task-system.md`: replace the "do NOT set
  workflow_id via tasks_update" guidance with the real channel.

**Exit criteria:** new unit suite green; the existing
`test_workflow_id_cannot_be_spoofed_through_caller_metadata` still green.

#### Integration Contract — `tasks_link_workflow`
- **Triggered from:** MCP client call `tasks_link_workflow(task_id=..., workflow_id=...)`
  on session-buddy (port 8678); in production, mahavishnu's `tasks_handoff_to_workflow`
  step 3 and the orphan sweeper.
- **Returns to / updates:** session-buddy's task metadata sidecar
  (`~/.claude/data/tasks_metadata.sqlite`, row keyed by `reflection_id`) — top-level keys
  `workflow_id`, `workflow_linked_at`, `workflow_linked_by`; plus a `history` entry and a
  `task.updated` event on the `bodai:events` Redis stream.
- **Demonstrable by:** `tasks/unit/test_tasks_link_workflow.py` — a task linked once shows
  `workflow_id` populated; a second link to a different id returns `workflow_already_linked`;
  a second link to the same id is idempotent.
- **Rollback signal:** `workflow_already_linked` rejections climbing in the `task.updated`
  event stream, or `tasks_get` returning a task whose `workflow_id` disagrees with the
  sidecar's `workflow_id` key.
- **Observability added:** `task.updated` event with a `workflow_id` diff entry, and the
  sidecar's `history` entry (`field="workflow_id"`, `before`, `after`, `actor`, `at`).

---

### Phase 2: mahavishnu — the dispatch edge and its client

**Goal:** the handoff tool can actually run, end to end, and produce a real
`workflow_id`.

**Tasks:**
- `tasks_handoff.py`: update `HandoffResult` to the durable-workflow shape; replace the
  `pool_route_execute_fn` seam with `workflow_dispatch_fn`; step 2 calls the durable
  dispatch and surfaces its `workflow_id`; step 3 calls `tasks_link_workflow`; the
  client duck-type gains `tasks_link_workflow`.
- New `mahavishnu/mcp/tools/tasks_session_buddy_client.py`: a thin adapter over
  `BodaiComponentClient` exposing `tasks_get` and `tasks_link_workflow` with the shapes
  the handoff tool and sweeper expect (unwrapping FastMCP's `CallToolResult` envelope).
- `server_core.py`: bind both seams at registration —
  `workflow_dispatch_fn` = the raw `trigger_workflow` coroutine (FastMCP 4.x's
  `@server.tool()` returns a `FunctionTool`; the undecorated function is `.fn`), and
  `session_buddy_client` = the new adapter over the configured session-buddy URL.
- `tasks_handoff_gate.py`: make the docstring's claim true — verify the two repos'
  `HandoffResult` shapes match at registration, not merely that the import succeeds.

**Exit criteria:** `tests/unit/test_tasks_handoff.py` updated and green against the new
envelope; a new unit suite covers the client adapter.

#### Integration Contract — handoff step 2 + step 3
- **Triggered from:** MCP client call
  `mcp__mahavishnu__tasks_handoff_to_workflow(task_id=...)` on mahavishnu (port 8680).
- **Returns to / updates:** mahavishnu's durable workflow state
  (`workflow_state_manager`, keyed by `workflow_id`); then session-buddy's task sidecar
  via `tasks_link_workflow`; plus `task.handoff_started` / `task.handoff_completed`
  events on `bodai:events`.
- **Demonstrable by:** `tests/unit/test_tasks_handoff.py` — a stub dispatch returning
  `{"workflow_id": "wf_abc12345_code_review", "status": "completed",
  "repos_processed": 1}` yields a `HandoffResult` with that id, and the stub client
  records exactly one `tasks_link_workflow` call with that id.
- **Rollback signal:** `WorkflowNotReturnedError` (MHV-102) rate climbing, or
  `task.handoff_orphan` events with `reason="step_3_update_failed"` appearing on the
  stream.
- **Observability added:** `task.handoff_started` / `task.handoff_completed` /
  `task.handoff_orphan` events (already specified, now actually emitted end-to-end).

---

### Phase 3: mahavishnu — the sweeper converges

**Goal:** the sweeper stops dropping orphans and starts re-linking them exactly once.

**Tasks:**
- `lifecycle.py::get_session_buddy_client()`: return the real client instead of `None`.
- `task_orphan_sweeper.py`: re-link through `tasks_link_workflow`; drop the
  `re_linked_at` / `re_link_reason` breadcrumbs from the task record (they were never
  contract fields and collide with `metadata`'s replace semantics).
- The idempotency check (`task.get("workflow_id")`) becomes meaningful once Phase 1's
  channel and Phase 2's dispatch are live.

**Exit criteria:** sweeper unit tests green; a linked orphan is skipped; an unlinked
orphan is linked once and is skipped on the next cycle.

#### Integration Contract — orphan sweeper re-link
- **Triggered from:** the `task.handoff_orphan` event on the `bodai:events` Redis stream
  (consumer group `bodai-task-orphan-sweeper`), spawned by
  `mahavishnu/mcp/lifecycle.py::build_post_start_lifespan`.
- **Returns to / updates:** session-buddy's task metadata sidecar — the same top-level
  `workflow_id` key Phase 1 writes.
- **Demonstrable by:** `tests/unit/test_task_orphan_sweeper.py` — an orphan whose task
  already has `workflow_id` produces zero `tasks_link_workflow` calls; one without it
  produces exactly one; a second cycle over the same orphan produces zero (the task is
  now linked).
- **Rollback signal:** the sweeper logging "no session_buddy client bound; skipping
  recovery" — the exact line today's stub produces.
- **Observability added:** the sweeper's existing `entities_count` /
  `last_updated_timestamp` / `errors_total` counters (already surfaced in
  `/health`), now reflecting real recovery work rather than a skip-everything loop.

---

### Phase 4: contract amendments and live verification

**Goal:** the docs describe the contract that exists, and the contract is proven live.

**Tasks:**
- Amend `docs/specs/2026-10-02-bodai-task-system-v1.1.md` — replace the back-link
  wording with the typed channel; drop the `metadata__workflow_id` reference.
- Amend session-buddy's skill catalog `bodai-session-buddy-task-system.md` — document
  `tasks_link_workflow`, the link-once rule, and the provenance fields.
- Live end-to-end verification (below).
- `python scripts/audit_orphans.py` — no new orphan symbols.
- `python scripts/audit_requirements.py` — no orphans, no phantoms.

**Exit criteria:** live handoff produces a populated `workflow_id`; the link survives a
session-buddy restart; the sweeper converges.

#### Integration Contract — live verification
- **Triggered from:** an operator-facing MCP session: `tasks_create` on session-buddy,
  then `mcp__mahavishnu__tasks_handoff_to_workflow`, then `tasks_get`.
- **Returns to / updates:** the live task's sidecar row and its `workflow_id` field.
- **Demonstrable by:** `tasks_get` returns a non-null `workflow_id` equal to the id
  returned by the handoff, `workflow_linked_at` and `workflow_linked_by` populated, and
  the same values after `launchctl kickstart -k gui/$(id -u)/com.mcp.session-buddy`.
- **Rollback signal:** the handoff returning MHV-101/MHV-102, or `tasks_get` returning
  `workflow_id: null` after a successful handoff.
- **Observability added:** none new — this phase verifies the signal added in Phases 1–3.

---

## 6. Required Code Changes

### session-buddy

- [ ] `session_buddy/mcp/tools/tasks_models.py` — provenance fields, `WORKFLOW_ID_PATTERN`,
      `HandoffResult` shape.
- [ ] `session_buddy/mcp/tools/tasks_tools.py` — `tasks_link_workflow`, `_build_task`
      provenance, `_persist_task_update` provenance, tool registration.
- [ ] `session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md` — document the
      channel.
- [ ] `tests/unit/test_tasks_link_workflow.py` (new) — link, idempotent re-link,
      conflicting re-link, visibility, pattern validation, provenance.
- [ ] `tests/unit/test_tasks_persistence.py` — extend for the provenance round-trip.

### mahavishnu

- [ ] `mahavishnu/mcp/tools/tasks_handoff.py` — envelope, dispatch seam, step 3.
- [ ] `mahavishnu/mcp/tools/tasks_session_buddy_client.py` (new) — `BodaiComponentClient`
      adapter.
- [ ] `mahavishnu/mcp/server_core.py` — bind both seams.
- [ ] `mahavishnu/mcp/lifecycle.py` — real sweeper client.
- [ ] `mahavishnu/mcp/sweepers/task_orphan_sweeper.py` — link through the typed channel.
- [ ] `mahavishnu/mcp/tools/tasks_handoff_gate.py` — real shape parity check.
- [ ] `tests/unit/test_tasks_handoff.py` — update for the new envelope and step 3.
- [ ] `tests/unit/test_tasks_session_buddy_client.py` (new).
- [ ] `tests/unit/test_task_orphan_sweeper.py` — update for convergence.

### docs

- [ ] `docs/specs/2026-10-02-bodai-task-system-v1.1.md` — amend.
- [ ] `docs/specs/2026-10-30-task-workflow-backlink-design.md` — done.
- [ ] `docs/plans/2026-10-30-task-workflow-backlink.md` — this file.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `session-buddy/.venv/bin/pytest tests/unit/test_tasks_link_workflow.py tests/unit/test_tasks_persistence.py` | all pass | test output |
| `mahavishnu/.venv/bin/pytest tests/unit/test_tasks_handoff.py tests/unit/test_tasks_session_buddy_client.py tests/unit/test_task_orphan_sweeper.py` | all pass | test output |
| `python scripts/audit_requirements.py` | exit 0 — no orphans, no phantoms | script output |
| `python scripts/audit_orphans.py` | no new orphan symbols | script output |
| live `tasks_create` → `tasks_handoff_to_workflow` → `tasks_get` | `workflow_id` populated | MCP transcript |
| live session-buddy restart → `tasks_get` | `workflow_id` still populated | MCP transcript |
| live orphan sweep | linked orphan skipped; unlinked orphan linked once | sweeper log / stream |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `trigger_workflow` is a durable, potentially long-running dispatch; the handoff's rate limit (10/min) and step-3 timeout could interact badly | medium | `timeout` is threaded through to `trigger_workflow`; the orphan sweeper covers the case where the link fails after dispatch |
| The handoff's `HandoffResult` shape change breaks a consumer that reads `pool_name` | low | `pool_name` is not referenced outside `tasks_handoff.py` and its tests (grep-verified during implementation) |
| session-buddy and mahavishnu versions drift, so mahavishnu calls a `tasks_link_workflow` that the installed session-buddy does not have | medium | The gate's shape-parity check fails loudly at registration rather than at first call |
| Turning the durable path on makes the handoff much slower than a pool dispatch | medium | Documented in the design; the durable path is what produces a pollable `workflow_id` |
| A live handoff actually dispatches real work (costs money / burns a pool) | medium | Live verification uses a trivial probe task; the user is told before the live step |

## 9. Decision Rule

The plan is done when a live task comes back from `tasks_get` with a populated
`workflow_id` and provenance, the link survives a session-buddy restart, the sweeper
converges, both repos' unit suites are green, and both audit scripts exit 0.

If scope pressure forces a cut, **cut in this order**: (3) the sweeper's convergence
work, then (2) the shape-parity gate, then the provenance fields — but **never** cut
Phase 1 or Phase 2's core, because a link that no dispatch can produce is the status
quo this plan exists to end.

---

## References

- `docs/specs/2026-10-30-task-workflow-backlink-design.md` — the contract.
- `docs/specs/2026-10-02-bodai-task-system-v1.1.md` — the task-system spec being amended.
- `docs/specs/.archive/2026-09-29-task-system-design.md` — the original spec (archived;
  its `metadata__workflow_id` line is superseded, not edited).
- `docs/decisions/wire-up-contract.md` — the policy this plan implements.
- `session-buddy/session_buddy/mcp/skills_catalog/bodai-session-buddy-task-system.md` —
  the session-buddy-side contract doc.

---

## 8. Implementation status (2026-10-30)

The plan shipped with revisions. An independent review of the design
against the source found the mahavishnu half needed more than the plan
assumed, and the operator chose a fire-and-forget dispatch. The full
revision log is in the design doc §7; this is the build summary.

### Phase 1 — session-buddy: the typed link channel — **DONE**

- `tasks_link_workflow` is the single writer of `Task.workflow_id`.
  Owner-scoped (plus a `task_system.link_service_principals` allowlist
  for the sweeper); link-once and **atomic** (a conditional `UPDATE`,
  not a read-then-write); provenance in `workflow_linked_at` /
  `workflow_linked_by`; the workflow id validated against the shared
  pattern, with dot-segments rejected.
- The metadata bag still cannot reach a server-set field — pinned.
- The update path re-reads the sidecar row before writing, so an
  ordinary `tasks_update` cannot erase a link written in flight.
- Commits: `e642d6d4`, `023c7cd2`.

### Phase 2 — mahavishnu: the dispatch edge — **DONE**

- `dispatch_workflow_async` in `core/workflow_execution.py`: creates the
  workflow id and state, validates QC inline, schedules the execution in
  the background, returns `{"workflow_id", "status": "running"}`. The
  workflow is still RUNNING when the binding is written — which is what
  makes the orphan case recoverable. `trigger_workflow` is untouched
  and still blocks.
- `tasks_handoff_to_workflow` now: resolves the repo scope (refusing an
  unscoped dispatch with `NoRepoScopeError`), dispatches, rejects the
  literal `"unknown"` workflow id, and links through
  `tasks_link_workflow`.
- `SessionBuddyTaskClient` — a narrow adapter over
  `BodaiComponentMCPClient` exposing `tasks_get` and
  `tasks_link_workflow` (and deliberately NOT `tasks_update`).
- The contract gate compares the two repos' envelopes field-for-field
  and the caller SKIPS registration instead of raising — a version skew
  must not take the orchestrator down.

### Phase 3 — the sweeper converges — **DONE**

- `get_session_buddy_client()` returns the real client instead of
  `None`. The sweeper was consuming every orphan event and dropping it.
- The sweeper re-links through `tasks_link_workflow` — the previous
  `tasks_update(metadata={...})` shape never reached the field.
- mahavishnu publishes the orphan event ITSELF. It used to call
  session-buddy's `publish_task_event_raw`, which writes through a
  publisher singleton assigned only inside the session-buddy process —
  so from mahavishnu it was a silent no-op and the sweeper had nothing
  to consume.

### Phase 4 — docs and live verification — **PARTIAL**

- The design doc carries the revision log; the v1.1 spec's sweeper
  section is amended; session-buddy's skill catalog documents the
  channel.
- **Live-verified**: `tasks_link_workflow` is registered on the running
  session-buddy (225 tools, 8 task tools); a task created and linked
  comes back with `workflow_id`, `workflow_linked_at` and
  `workflow_linked_by`; a conflicting link is refused
  (`workflow_already_linked`); the same link is idempotent; a
  `metadata` forgery attempt does not move the field; a dot-segment id
  is refused (`invalid_workflow_id`).
- **Blocked on an operator step**: mahavishnu depends on the PUBLISHED
  session-buddy, and the gate compares the two repos' envelopes. Until
  session-buddy ships the new contract, the gate correctly reports the
  contract unavailable and the handoff tool is simply not registered.
  The live END-TO-END handoff needs (a) session-buddy published, (b)
  mahavishnu's venv re-synced, (c) the `session-buddy>=0.33.1` pin
  bumped — operator-owned, per `feedback-mcp-common-version-bump-is-user`.

### What was NOT done

- The auth gate was not turned on and no new `mcp_common` scope was
  added — the non-owner link path is closed by default instead.
- `metadata`'s replace-not-merge semantics are unchanged.
- The `uuid_alias` display-id gap is unchanged.
