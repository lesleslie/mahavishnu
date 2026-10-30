# Task → Workflow Back-Link Contract (design)

**Date:** 2026-10-30
**Status:** Approved for implementation
**Repos:** `session-buddy` (field owner), `mahavishnu` (dispatch edge)
**Supersedes:** the never-implemented `UpdateTaskRequest(metadata__workflow_id=...)` channel in
`docs/specs/.archive/2026-09-29-task-system-design.md` (line 164) and the
`docs/specs/2026-10-02-bodai-task-system-v1.1.md` back-link wording.

---

## 1. The problem

A session-buddy task is supposed to be dispatchable to a running workflow, and the
resulting `workflow_id` is supposed to be recorded on the task so the link survives
and can be recovered when it doesn't.

**No `workflow_id` has ever existed anywhere in the fleet.** The chain is broken in four
independent places, and each was verified by reading the source or by probing the live
servers — not inferred.

| # | Break | Evidence |
|---|---|---|
| B1 | The spec's write channel was never implemented. `UpdateTaskRequest(metadata__workflow_id=...)` appears once, in a docstring added by `780ebb91`. There is no such parameter. | `rg metadata__workflow_id` across both repos → 1 hit, a string |
| B2 | `tasks_update` never persisted `metadata` at all, and `_build_task` reads `workflow_id` from the **top-level** sidecar blob key — a key nothing ever writes. | `session_buddy/mcp/tools/tasks_tools.py` |
| B3 | mahavishnu's step 3 wrote `tasks_update(metadata={"workflow_id": ...})`, which lands in the nested metadata bag. `task.workflow_id` therefore stays `None` forever. | `mahavishnu/mcp/tools/tasks_handoff.py:504` |
| B4 | The handoff tool was registered with **no** `session_buddy_client` and **no** dispatch function, so it died at step 1 and misreported it as "task not found". | Live probe: tool returns `[MHV-101] Task not found`; session-buddy's own `tasks_get` returns a `not_found` **dict** for the same id, so a wired client would have said "task content is empty". The tool never contacted session-buddy. |

Two more consequences follow from B3/B4:

- **The orphan sweeper never converges.** Its idempotency check is
  `task.get("workflow_id")` — always `None` — so it re-links forever without ever
  satisfying its own check.
- **The sweeper discards its input.** `get_session_buddy_client()` returns `None`
  (an explicit stub), so every `task.handoff_orphan` event is consumed off the
  `bodai:events` Redis stream and dropped with a log line. The error-handling matrix
  the v1.1 spec describes — orphan event → sweeper re-link — has never executed.

And one gap sits *upstream* of all of it:

- **B5 — the dispatch step cannot produce a `workflow_id`.** `tasks_handoff_to_workflow`
  calls `pool_route_execute`, which returns `{pool_id, status, result}`. There is no
  `workflow_id` in `mahavishnu/pools/` at all. The tool would raise
  `WorkflowNotReturnedError` (MHV-102) even with a bound client.
  The spec's step 2 says `dispatch_to_pool` — **a tool that does not exist** in
  mahavishnu. It is referenced by agent descriptions, by
  `mahavishnu/mcp/tools/_workflow_id_guard.py`, and by comments, but there is no
  `async def dispatch_to_pool` in the source.

The contract below fixes the field channel, the authorization, the dispatch target, and
the wiring — because fixing only the field channel would leave a contract that is
correct and unreachable.

---

## 2. The contract

### C1 — `Task.workflow_id` is written only through a dedicated typed channel

New session-buddy MCP tool:

```
tasks_link_workflow(task_id: str, workflow_id: str) -> Task | error envelope
```

It is the **only** writer of `Task.workflow_id`. The generic `UpdateTaskRequest.metadata`
bag cannot reach the field — the field is written to a top-level sidecar key, never into
the metadata bag. That property already holds; the dedicated tool gives it a single,
greppable write site and makes it enforceable by test rather than by inspection.

### C2 — Authorization: owner-scoped, same trust domain

`tasks_link_workflow` requires `Permission.WRITE` and applies the same visibility filter
as `tasks_update`. A caller that cannot see the task receives `not_found` — the
404-shaped envelope, so a private task's existence is not leaked.

**This is an interface-level guarantee, not an identity-level one, and the spec says so
in those words.** On the current deployment (substrate auth gate off, loopback) every MCP
client — Claude Code, akosha, the sweeper, any local tool — reaches session-buddy as
`user:les`. Distinguishing "mahavishnu" from "anyone else" by identity would require
turning the auth gate on fleet-wide, adding a scope to `mcp_common.auth.permissions`
(today: read/write/delete/admin), and publishing mcp-common before the consumer may
depend on it. That is a separate posture change and is **out of scope** here (see §4).

The guarantee that does hold, structurally, is the one that matters: **the field cannot
be reached through a generic caller-supplied container.** That is what the existing
`test_workflow_id_cannot_be_spoofed_through_caller_metadata` pins, and it stays pinned.

**Bounded harm.** The only consumer of `task.workflow_id` in the entire fleet is the
orphan sweeper's idempotency check, applied to the caller's own task. A forged value
suppresses orphan recovery for the caller's own task and nothing else. It grants no
access to another owner's task (the visibility filter still applies) and creates no
workflow. The field is audit data, not an access-control decision.

### C3 — Link-once semantics

A task binds to exactly one workflow.

| Current state | New `workflow_id` | Result |
|---|---|---|
| unset | any | link succeeds |
| set | same value | **idempotent success** — task returned unchanged, no event, no history entry |
| set | different value | error envelope `workflow_already_linked` |

Re-linking would orphan the first workflow's audit trail: the task would claim a
workflow it is not running under while the original workflow keeps running. The first
link wins.

### C4 — Provenance

The link records, alongside `workflow_id`:

- `workflow_linked_at` — server clock (UTC), server-written.
- `workflow_linked_by` — the derived caller identity, server-written.

Both are first-class `Task` fields, populated by `_build_task` from the sidecar and
readable through `tasks_get`. The `task.updated` event carries the `workflow_id` diff,
so the link is visible in `tasks_history` as well as in the record.

### C5 — `workflow_id` shape

`workflow_id` must match:

```
^[A-Za-z0-9._-]{1,128}$
```

This is **not** a new invention: mahavishnu already enforces exactly this pattern in
`mahavishnu/mcp/tools/_workflow_id_guard.py` (`WORKFLOW_ID_PATTERN`), because workflow
ids are spliced into MCP key paths (`workflow-results/{workflow_id}/`) and must be safe
path fragments. session-buddy validates with the identical pattern so the two repos
agree on what a workflow id is and the value remains safe wherever it is later used as
a key or path segment. The two pattern definitions are pinned by a test on each side.

### C6 — The dispatch edge produces a durable-workflow id

mahavishnu's `tasks_handoff_to_workflow` step 2 dispatches through the **durable
workflow** path — `trigger_workflow(adapter=..., task_type=..., params=..., timeout=...)`
— not through `pool_route_execute`.

Rationale:

- `trigger_workflow` is the only path in the fleet that returns a `workflow_id`
  (`{"workflow_id", "status", "result", "repos_processed", ...}`), and that id is
  pollable via `get_workflow_status` and published on the `workflow:{id}` WebSocket
  channel. A pool dispatch returns a *result*, not a *handle*; there is nothing to
  back-link to.
- The handoff tool already carries an `adapter: Literal["prefect","llamaindex","agno"]`
  parameter and a `HandoffResult.adapter` field. `pool_route_execute` has no adapter
  concept at all. The implementation contradicted its own signature.
- The task system's premise (mahavishnu's CLAUDE.md: "the only path from a
  session-buddy task to a running workflow") is about a *running workflow* with an id
  that can be orphaned and later recovered.

### C7 — `HandoffResult` reflects the durable workflow

`HandoffResult` is defined in **both** repos — session-buddy's `tasks_models.py` is the
source of truth and mahavishnu keeps an inline copy so a session-buddy upgrade cannot
break the tool signature mid-flight. Both change together:

```python
class HandoffResult(BaseModel):
    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    adapter: Literal["prefect", "llamaindex", "agno"]
    started_at: datetime
    status: str            # queued | running | completed | failed  (from trigger_workflow)
    repos_processed: int   # from trigger_workflow
```

`pool_name` is **dropped**: a durable workflow has no pool. It is replaced by `status`
and `repos_processed`, both of which `trigger_workflow` already returns. The two repos'
copies must be kept in lockstep; `tests/unit/test_tasks_handoff.py::TestHandoffEnvelopes`
pins the shape on the mahavishnu side.

### C8 — The sweeper converges

With C1 and C6 in place, the sweeper's idempotency check (`task.get("workflow_id")`)
becomes meaningful: a linked task is skipped, an unlinked orphan is linked once, and
C3's idempotency rule makes a retry of the same link a no-op rather than an error.

The sweeper's `re_linked_at` / `re_link_reason` breadcrumbs are **not** written to the
task record. They were never contract fields, and putting them in the metadata bag
would collide with `tasks_update`'s replace-not-merge semantics for `metadata`. The
sweeper's own synthetic `task.handoff_completed` event already carries the outcome to
the stream.

### C9 — Wiring

mahavishnu binds, at registration time:

- **`session_buddy_client`** → a thin adapter over the existing
  `mahavishnu/mcp/bodai_component_client.py::BodaiComponentClient` (streamable HTTP,
  `call_tool(name, arguments)`), exposing `tasks_get` and `tasks_link_workflow` with
  the shapes `tasks_handoff.py` and the sweeper expect. The URL comes from
  `MahavishnuSettings` (the same source the pool manager uses for its session-buddy
  pool).
- **`workflow_dispatch_fn`** → the raw `trigger_workflow` coroutine. FastMCP 4.x's
  `@server.tool()` returns a `FunctionTool`, so the undecorated function is
  `FunctionTool.fn`.

And `mahavishnu/mcp/lifecycle.py::get_session_buddy_client()` — currently `return None`
with a docstring saying "a follow-up wires the real client" — returns that client, so
the sweeper stops dropping every orphan it consumes.

`register_tasks_handoff_tools` keeps its injectable-seam signature; production simply
passes the two bindings it was designed to accept.

### C10 — Failure semantics are unchanged

| Step | Failure | Event | Envelope |
|---|---|---|---|
| 1 | session-buddy unreachable / task missing | — | `TaskNotFoundError` (MHV-101) |
| 2 | dispatch failed | `task.handoff_orphan` `reason="step_2_dispatch_failed"` | re-raise |
| 2 | dispatch returned no `workflow_id` | **none** (a phantom orphan would be worse) | `WorkflowNotReturnedError` (MHV-102) |
| 3 | link failed | `task.handoff_orphan` `reason="step_3_update_failed"` + `workflow_id` | re-raise |
| — | caller disconnected between 2 and 3 | `task.handoff_orphan` `reason="caller_disconnected"` | `CancelledError` |

C9 is what makes this matrix real rather than theoretical: today the sweeper that is
supposed to consume the step-3 orphan has no client.

---

## 3. Non-goals

- **Not** turning on session-buddy's auth gate, adding a scope to `mcp_common`, or
  publishing mcp-common. A fleet-wide posture change, and a separate decision.
- **Not** changing `UpdateTaskRequest.metadata` semantics. `tasks_update(metadata=...)`
  currently *replaces* the whole metadata bag rather than merging into it. That is a
  real wart, but it is orthogonal to this contract and fixing it here would widen the
  blast radius.
- **Not** adding a `dispatch_to_pool` tool to mahavishnu, even though agent
  descriptions and CLAUDE.md reference it. The reference is stale; the durable-workflow
  path (C6) already covers the need.
- **Not** changing the pool router's contract or `pool_route_execute`.
- **Not** touching the `task.handoff_orphan` event envelope.

## 4. Follow-ups this design explicitly leaves open

1. **Identity-grade authorization**, if the operator ever wants it: enable session-buddy's
   auth gate, add a `Permission.HANDOFF` to mcp_common, publish mcp-common, and issue
   mahavishnu a Bearer token. C1/C2's channel does not change — only the check inside
   it tightens. That is the point of choosing an interface-level guarantee now.
2. **The `metadata` replace-vs-merge wart**, if it starts biting.
3. **`Task.metadata["uuid_alias"]`** — the compact display id the model docstring names
   is stored in the blob's top-level `uuid_alias` key, not in `metadata`. Unrelated to
   this contract; still open from earlier work.
4. **The stale `dispatch_to_pool` references** in mahavishnu's CLAUDE.md and agent
   descriptions.

## 5. Operator-owned steps (not automated here)

- session-buddy must be **tagged** before mahavishnu's PR #2 can merge
  (cross-repo PR dependency, per mahavishnu's CLAUDE.md).
- The `session-buddy>=0.30.0` pin in mahavishnu's `pyproject.toml` is bumped **by the
  operator**, never by an agent (`feedback-mcp-common-version-bump-is-user`).
- Push is user-controlled. Nothing in this work is pushed without explicit approval.

---

## 6. What "done" looks like

1. `tasks_link_workflow` exists in session-buddy, is owner-scoped, link-once, validates
   the workflow-id pattern, persists `workflow_id` + provenance, and emits the
   `task.updated` diff.
2. The metadata bag still cannot reach `workflow_id` — pinned by test.
3. mahavishnu's step 3 and the sweeper both call `tasks_link_workflow`.
4. The handoff tool and the sweeper have real, bound clients.
5. A live task is created, handed off, and comes back with a populated `workflow_id`;
   the task survives a session-buddy restart with the link intact.
6. The sweeper skips an already-linked orphan and re-links an unlinked one exactly once.

---

## 7. Revisions (2026-10-30, after independent review)

An independent reviewer read this document against the source and found
several claims wrong or incomplete, and the implementation surfaced two
more. The corrections are recorded here rather than silently folded in,
because several of them change what the contract promises.

### 7.1 Corrections to §1

- **B2 was stale.** `tasks_update` DID persist `metadata` as of
  session-buddy `086a64c1` (same day). The operative conclusion stands —
  `_build_task` reads `workflow_id` from the **top-level** sidecar key,
  and `tasks_create` already writes `metadata["workflow_id"] = None`
  there, so the top-level channel C1 assumes already existed.
- **B6 was missing: mahavishnu never published the orphan event.**
  `session_buddy.mcp.tools.tasks_events._publisher` is assigned in
  exactly one place in the whole fleet — `session_buddy/server_optimized.py:346`,
  inside the session-buddy server process. `publish_task_event_raw`
  returns early when it is `None`, and mahavishnu never sets it. So
  `_publish_task_handoff_orphan` was a silent no-op: **the sweeper had
  nothing to consume.** Binding a client to the sweeper (C9) would not
  have made it work. Mahavishnu now publishes onto `bodai:events`
  itself, in the flat-fields XADD shape the stream adapter expects.
- **B7 was missing: the gate took the whole server down.**
  `register_tasks_handoff_tools` raised `RuntimeError` when the contract
  was unavailable, and it is called from `_register_tools()` →
  `FastMCPServer.__init__`. A version skew cost the fleet the
  orchestrator, not just the handoff edge. The gate now SKIPS
  registration.

### 7.2 C2 — owner-scoped, with a service-principal allowlist

C2 originally said the link was gated on "the same visibility filter as
`tasks_update`". That is wrong, and the user's chosen option said
"owner-scoped" while the implementation said "visibility-filtered".

The visibility filter lets **any** caller read — and write — a `public`
task. `workflow_id` is a server-set field: a link asserts "this task is
running under that workflow", and the orphan sweeper trusts that
assertion. A stranger could bind someone else's public task to a
workflow it never dispatched.

**Revised C2:** the gate is the task's **owner**, the same check
`tasks_complete` uses, plus an explicit allowlist of service
principals (`task_system.link_service_principals`, empty by default).
The allowlist is how mahavishnu's orphan sweeper recovers a task it
does not own without opening the channel to every caller. The
visibility filter is *replaced*, not added to: the owner passes it
anyway, and an allow-listed principal has to be able to see the task it
is recovering.

### 7.3 C3 — the link-once decision is atomic

C3 originally described a read-check-then-write. Two concurrent linkers
could both observe an unlinked task and both write, and the second
write won silently. That is not hypothetical: the handoff's step 3 and
the sweeper's recovery are two independent attempts at the same link,
and the sweeper exists to retry a link that failed.

**Revised C3:** the decision is a single conditional `UPDATE`:

```sql
UPDATE reflections
   SET metadata = json_patch(COALESCE(metadata, '{}'), :patch)
 WHERE id = :id
   AND (json_extract(metadata, '$.workflow_id') IS NULL
        OR json_extract(metadata, '$.workflow_id') = :workflow_id)
```

The `WHERE` clause *is* the invariant — a conflicting link matches zero
rows and the first binding stands. `json_patch` is RFC 7386
merge-patch, so the write touches only the keys it carries and a
concurrent update to the task's priority or status is not clobbered.

### 7.4 C5 — the pattern admits dot-segments

`^[A-Za-z0-9._-]{1,128}$` admits `.` and `..`. They match the character
class but are path-traversal segments where the id is consumed
(`workflow-results/{workflow_id}/`). They are now rejected separately,
on **both** sides, and the pattern is applied to the model fields so a
value that reached the row by another route is not served as a valid
task. The validation uses `fullmatch`, not `match`: `$` also matches
immediately before a trailing newline.

### 7.5 C6 — the dispatch is fire-and-forget, and repo-scoped

C6 originally said the dispatch goes through `trigger_workflow`. That
path is wrong in two ways, both verified against the source:

- `trigger_workflow`'s docstring claims "Returns a `workflow_id`
  immediately (fire-and-forget)" but its body **awaits**
  `execute_workflow_parallel` — it blocks for the whole workflow. The
  docstring describes the intent; the body does not implement it.
- With `repos=None` and `tag=None` it resolves **every repository in
  the catalog** and runs the workflow over all of them.

**Revised C6:** the handoff dispatches through a new
`dispatch_workflow_async`, which creates the workflow id and state,
validates pre-execution QC inline (so a QC failure is reported rather
than leaving a phantom running workflow), schedules the execution in
the background, and returns `{"workflow_id", "status": "running"}`
immediately. The workflow is therefore still **running** when the
binding is written — which is what makes the orphan case recoverable.

The dispatch is scoped to **one repository**, from `params.repo` or the
task's `metadata["repo"]`. A task with neither is refused
(`NoRepoScopeError`, MHV-103) rather than fanned out over the catalog.

`trigger_workflow` itself is untouched: it still blocks, and its two
callers (`jot/drain.py`) still get a blocking dispatch.

### 7.6 C9 — the client, and the gate

C9 named the class `BodaiComponentClient`; the real name is
`BodaiComponentMCPClient`. The adapter over it lives in
`mahavishnu/mcp/tools/tasks_session_buddy_client.py` and exposes
`tasks_get` and `tasks_link_workflow` — and deliberately NOT
`tasks_update`, so the generic metadata path is not part of the
back-link client at all.

The gate (`tasks_handoff_gate.py`) now compares the two repos' shared
envelopes field-for-field instead of only checking importability, and
the caller skips registration rather than raising.

### 7.7 §5 — the operator steps are different

- The pin is `session-buddy>=0.33.1` (installed 0.37.1), not 0.30.0.
- **session-buddy must be PUBLISHED and installed into mahavishnu's
  venv before the handoff edge activates.** mahavishnu depends on the
  published wheel, and the gate compares the two repos' envelopes — so
  until session-buddy ships the new contract, the gate correctly
  reports "unavailable" and the handoff tool is simply not registered.
  That is the cross-repo publish dependency working as intended, not a
  regression.
- The version bump in `pyproject.toml` remains operator-owned.

### 7.8 Still open

- `HandoffParams` in session-buddy and mahavishnu keep inline copies.
  The gate now compares them, but the duplication is still duplication.
- The `metadata` bag's replace-not-merge semantics are unchanged (out
  of scope, §3).
- `Task.metadata["uuid_alias"]` still lives in the blob's top-level
  `uuid_alias` key — unrelated to this contract.
