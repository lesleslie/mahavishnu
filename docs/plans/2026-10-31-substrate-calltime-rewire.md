---
status: active
role: canonical
kind: plan
date: 2026-10-31
last_reviewed: 2026-10-31
superseded_by: null
topic: substrate-calltime-rewire
title: "Bind the substrate call sites to the live store instead of a dead module lookup"
requirements:
  - id: REQ-SUBSTR-001
    title: "No call site resolves a substrate function by dynamic module lookup"
  - id: REQ-SUBSTR-002
    title: "The substrate and the KV tools share one store instance"
  - id: REQ-SUBSTR-003
    title: "Substrate writes persist and reads return the stored payload"
  - id: REQ-SUBSTR-004
    title: "Each call site's sync/async shape matches the substrate contract"
  - id: REQ-SUBSTR-005
    title: "A reader outside the server process reads through the server"
---

# Bind the substrate call sites to the live store instead of a dead module lookup

## 1. Outcome

The substrate call sites stop silently discarding data.

Today `mahavishnu/core/_mcp_substrate_compat.py` resolves
`importlib.import_module("mcp")` and reads `mcp.<name>`. The name `mcp`
now resolves to the **MCP Python SDK**, which has none of the retired
service's functions, so every lookup returns `None` and every caller
takes its "substrate not bound" branch. The durable ecosystem registry,
the workflow outcome log, the approval decision log and the webhook
ingress log are all written *nowhere*.

Success signal: `mahavishnu_upsert_service` followed by
`mahavishnu_list_services` returns the record; a workflow outcome
written by the executor is readable by `workflow_get_outcome_tool`; and
no module in `mahavishnu/` calls `mcp_calltime`.

## 2. Goals

1. Replace the dynamic module lookup with a real substrate binding.
2. Give the substrate the call contract the call sites actually use —
   a synchronous `put`, an awaitable `get`, a synchronous `list`.
3. Make the substrate and the `mahavishnu_kv_*` tools share one store, so
   a sibling component reading through the public KV surface sees what
   the server wrote.
4. Fix the one call site whose sync/async shape contradicts the others.

## 3. Non-Goals

1. **Making the store durable across processes.** The KV store is
   process-local by design (see the substrate rewire plan, § 4.2), and
   the ecosystem registry inherits that. Moving the store to shared
   storage is a separate piece of work with its own durability contract.
2. **Adding the analytics series back.** Unrelated to this defect.
3. **Wiring `approval_cli` as a CLI command.** It has no entry point
   today; this plan makes it correct, not reachable.

## 4. Current Findings

### 4.1 The lookup resolves to the wrong package

Verified in the project's venv:

```
mcp -> /Users/les/Projects/mahavishnu/.venv/lib/python3.14/site-packages/mcp/__init__.py
  mcp.put                 -> None
  mcp.get                 -> None
  mcp.list                -> None
  mcp.delete              -> None
  mcp.query_time_series   -> None
  mcp.aggregate_patterns  -> None
```

The name `mcp` belonged to the retired service's **client package**. The
shim's own docstring still describes it that way ("the optional ``mcp``
module", "the ``mcp`` package is not importable"). Its premise — that
the substrate might not be installed, and that call sites should degrade
gracefully — is obsolete: the substrate is mahavishnu's own server, in
the same process.

### 4.2 Fifteen call sites across seven modules, all no-opping

| Module | `put` | `get` | `list` | Shape used |
|---|---|---|---|---|
| `core/ecosystem_state.py` | 5 | 4 | — | `put` sync, `get` awaited |
| `core/workflow/outcome_writer.py` | 1 | — | — | `put` sync |
| `core/approval/decision_writer.py` | 1 | — | — | `put` sync |
| `mcp/tools/workflow_tools.py` | — | 1 | — | `get` awaited |
| `webhooks/receiver.py` | 1 | — | — | `put` sync |
| `webhooks/replay.py` | — | 1 | — | `get` **sync** |
| `cli/approval_cli.py` | — | — | 1 | `list` sync |

Two of these are live user-facing surfaces:

- **`AsyncEcosystemStateStore` backs the five durable ecosystem-state MCP
  tools** (`mahavishnu_upsert_service`, `_get_service`, `_list_services`,
  `_record_event`, `_list_events`) — the registry sibling components use
  to discover each other. `upsert_service_async` logs
  `ecosystem_state_upsert_skipped` and returns the validated record
  anyway, so the tool *reports success while writing nothing*.
- **`webhook_replay_tool`** and **`workflow_get_outcome_tool`** read
  records that were never written.

### 4.3 The contract the call sites use

The retired client was an MCP client, so `get` was an **awaitable** and
`put` was **fire-and-forget** (sync). The stored value was the
serialized payload:

- `get(key)` → awaited → returns the stored object: a `dict` for a
  record, a `list` for an index, `None` for a miss.
- `put(key, value)` → sync → stores a `dict`, a `list`, or a `msgspec`
  `Struct`.
- `list(prefix, since=..., status=...)` → sync → returns a list of
  payload dicts, filtered by `since` (a timestamp lower bound) and
  `status` (an exact match).

### 4.4 Two call sites disagree about `get`

`webhooks/replay.py` calls `get` **synchronously**
(`payload = get(f"webhook-ingress/{webhook_id}/")`) while
`workflow_tools.py` and `ecosystem_state.py` **await** it. Both cannot be
right against one function.

The tests pin each shape independently — `test_webhooks_replay.py` uses
a `MagicMock`, `test_workflow_tools.py` uses an `AsyncMock` — so
neither test catches the contradiction.

The awaitable shape is the correct one: `get` was an MCP tool call, so
it was a coroutine. `replay.py`'s synchronous call is therefore a latent
bug that has been masked by the lookup always returning `None`: with a
bound substrate it would hand `msgspec.convert` a coroutine instead of a
payload.

### 4.5 Six of the seven modules run inside the server process

| Module | Runs in | Process |
|---|---|---|
| `core/ecosystem_state.py` | the MCP server (behind `ecosystem_state_tools.py`) | server |
| `core/workflow/outcome_writer.py` | `core/workflow_execution.py` | server |
| `core/approval/decision_writer.py` | `core/approval_manager.py` | server |
| `mcp/tools/workflow_tools.py` | the MCP server | server |
| `webhooks/receiver.py` | a FastAPI route on the server | server |
| `webhooks/replay.py` | `mcp/tools/webhook_tools.py` | server |
| `cli/approval_cli.py` | a CLI invocation | **its own** |

So a substrate bound to the server's own in-process store serves six of
the seven correctly. `approval_cli` is the exception: it reads records
the server wrote, from a different process. Its signature already
anticipates that — it takes a bearer `token` and gates on JWT shape.

### 4.6 The store the substrate should use

`mahavishnu/mcp/tools/kv_tools.py` already holds the server's KV store:
a module-level `_ProcessLocalKV` (a dict under a `threading.Lock`), and
the four `mahavishnu_kv_*` tools read and write it. It is the server's
own substrate.

Binding the call sites to that same store means:

- the ecosystem registry, workflow outcomes, approval decisions and
  webhook ingress become readable through the public KV surface — which
  is how a sibling component is meant to discover them;
- no HTTP round-trip, no auth, and no dependency on the listener being
  bound (which the state backend does have).

The store lives under `mcp/tools/`, but `core/` must not import from
`mcp/` — the dependency already runs the other way. So the store moves
to `core/kv_store.py` and `mcp/tools/kv_tools.py` imports it from
there. One instance, one owner, no layering inversion.

### 4.7 The store is one value per key — the approval key must be per record

The retired `mcp.put` **appended** to a list held under one key, and
`mcp.list` returned that list. `ProcessLocalKV.put` is
`self._data[key] = value` — one value per key.

For most producers this is invisible: a service record, an event, a
workflow outcome and a webhook receipt are each naturally identified by
their key, so "latest wins" is the right semantic.

The approval history is the exception. `ApprovalLog` is documented as
*"Approval history entry — append-only"*, and the consumer is
`list_approval_history` — a *history*, not a current state. Writing every
decision to the single key `approval-history/{approval_id}/` would make
a second decision **overwrite** the first, silently narrowing the
contract from a history to a single record.

The fix is in the key layout, not the store: each decision is written
under its own key **inside** the approval's namespace —
`approval-history/{approval_id}/{timestamp}-{nonce}`. The store's
prefix listing then returns every decision for that approval, the
history stays append-only, and the reader's prefix query is unchanged.
The timestamp makes the key sortable; the nonce keeps two decisions in
the same microsecond from colliding.

This also keeps the write shape identical to the retired API's
*observable* behaviour: `list` returned every record, and it still does.


## 5. Requirements

```yaml
requirements:
  - id: REQ-SUBSTR-001
    title: "No call site resolves a substrate function by dynamic module lookup"
  - id: REQ-SUBSTR-002
    title: "The substrate and the KV tools share one store instance"
  - id: REQ-SUBSTR-003
    title: "Substrate writes persist and reads return the stored payload"
  - id: REQ-SUBSTR-004
    title: "Each call site's sync/async shape matches the substrate contract"
  - id: REQ-SUBSTR-005
    title: "A reader outside the server process reads through the server"
```

## 6. Implementation Phases

### Phase 1: One store, one substrate facade

**Goal:** a substrate the call sites can bind to, with the contract they
use.

**Tasks:**
1. Move the process-local store to `mahavishnu/core/kv_store.py`; have
   `mcp/tools/kv_tools.py` import it. (REQ-SUBSTR-002)
2. Add `mahavishnu/core/substrate.py` — `put` (sync), `get` (awaitable),
   `list` (sync, with `since` / `status` filters) over that store,
   JSON-encoding dicts / lists / `msgspec` structs on write and decoding
   them on read. (REQ-SUBSTR-003)

**Exit criteria:** the four `mahavishnu_kv_*` tools still round-trip
through the same store; `substrate.put` then `await substrate.get`
returns the original payload.

#### Integration Contract

- **Triggered from:** any substrate call site (the seven modules in § 4.2).
- **Returns to / updates:** the process-local store in
  `mahavishnu/core/kv_store.py`, keyed `ecosystem-services/…`,
  `ecosystem-events/…`, `workflow-results/…`, `approval-history/…`,
  `webhook-ingress/…`. The approval namespace holds one key **per
  decision** (`approval-history/{id}/{timestamp}-{nonce}`) so the
  history stays append-only — see § 4.7.
- **Demonstrable by:** `pytest tests/unit/test_substrate.py
  tests/unit/mcp/tools/test_kv_tools.py` → green.
- **Rollback signal:** the KV tools' round-trip test fails, or a
  sibling's `mahavishnu_kv_get` returns `None` for a key the server
  wrote.
- **Observability added:** none new — the substrate is in-process, so
  there is no network hop to observe.

### Phase 2: Rebind the call sites

**Goal:** every call site reaches the substrate.

**Tasks:**
1. Replace all fifteen `mcp_calltime(...)` lookups with the facade.
   (REQ-SUBSTR-001)
2. `webhooks/replay.py` becomes `async def` and awaits `get`; the
   caller in `mcp/tools/webhook_tools.py` awaits it. (REQ-SUBSTR-004)
3. `cli/approval_cli.py` reads through the server over HTTP rather than
   a local store, because it is the only reader outside the server
   process. (REQ-SUBSTR-005)
4. Delete `mahavishnu/core/_mcp_substrate_compat.py`. (REQ-SUBSTR-001)

**Exit criteria:** `grep -rn "mcp_calltime" mahavishnu/` returns
nothing; `mahavishnu_upsert_service` then `mahavishnu_list_services`
returns the record; a workflow outcome written by the executor is
readable by `workflow_get_outcome_tool`.

#### Integration Contract

- **Triggered from:** `mahavishnu_upsert_service` / `_record_event` /
  `_list_services` / `_list_events`; the workflow executor; the approval
  manager; the `/webhook` route; `workflow_get_outcome_tool`;
  `webhook_replay_tool`.
- **Returns to / updates:** the store keys listed in Phase 1.
- **Demonstrable by:** `pytest tests/unit/mcp/tools/test_ecosystem_state_tools.py
  tests/unit/approval/ tests/unit/test_webhooks_replay.py
  tests/unit/mcp/tools/test_workflow_tools.py` → green; a live
  `mahavishnu_upsert_service` → `mahavishnu_list_services` round-trip
  returns the record.
- **Rollback signal:** `ecosystem_state_upsert_skipped` appears in the
  server log again, or `mahavishnu_list_services` returns an empty list
  for a service that was just upserted.
- **Observability added:** the `*_skipped` warnings that fired on every
  call stop firing; their absence becomes the signal that the substrate
  is bound.

## 7. Verification

1. `grep -rn "mcp_calltime" -- mahavishnu/` → no hits.
2. Live: `mahavishnu_upsert_service` then `mahavishnu_list_services`
   returns the record.
3. Live: a workflow outcome is readable via `workflow_get_outcome_tool`.
4. `pytest tests/unit/test_substrate.py
   tests/unit/mcp/tools/test_ecosystem_state_tools.py
   tests/unit/approval/ tests/unit/test_webhooks_replay.py
   tests/unit/mcp/tools/test_workflow_tools.py
   tests/unit/mcp/tools/test_ecosystem_state_tools.py` → green.
5. `python scripts/audit_requirements.py` → 0 orphans, 0 phantoms.
6. `crackerjack run -v -f` → gate passes.

## 8. Risks

- **The substrate is process-local.** The registry is durable only for
  the life of the server process. That is the KV store's existing
  contract (§ 3, non-goal 1) — this plan does not change it, but it
  does make the data's fate visible for the first time.
- **`replay.py` changes shape.** `webhook_replay` becomes awaitable, so
  its caller and its tests change with it. That is the point: the
  current sync call is the latent bug in § 4.4.
- **Moving the store changes an import path.** `kv_tools.py` keeps its
  behaviour; only where `_ProcessLocalKV` lives changes.

## 9. Status

Implemented (2026-10-31). Both phases are landed:

- **Phase 1** — `mahavishnu/core/kv_store.py` (the shared store) and
  `mahavishnu/core/substrate.py` (the facade) are new; `kv_tools.py`
  imports the store from `core/`, so the substrate and the four
  `mahavishnu_kv_*` tools share one instance.
- **Phase 2** — all fifteen call sites are rebound to the facade;
  `webhooks/replay.py` is awaitable; `cli/approval_cli.py` reads over
  HTTP; `mahavishnu/core/_mcp_substrate_compat.py` is deleted.

Verification status:

| Check | Result |
|---|---|
| `grep -rn "mcp_calltime" -- mahavishnu/` | no hits |
| Affected suite (substrate, ecosystem state, approval, webhooks, workflow) | 100 passed |
| `scripts/audit_requirements.py` | 0 orphans, 0 phantoms |
| `scripts/audit_orphans.py` | new modules wired (no orphans reported) |
| `ruff check` / `ty check` on the changed files | clean |
| Live round-trip (real HTTP + real auth + real registration, in-process) | all checks passed |
| Live server after restart | 160 tools; the four `mahavishnu_kv_*` and the five ecosystem-state tools present |
| Full suite | 110 failed / 19785 passed — no failure is attributable to this change (see below) |
| `crackerjack run -v -f --changed-only` | 18/18 hooks passed |

### The live round-trip, in detail

`scripts/launch_mcp.py:build_server()` boots the real server; the probe
serves it on an ephemeral loopback port and calls the tools over HTTP
from the **same process** — which is required, because the internal
self-call credential is a random per-process token. Verified:

- `mahavishnu_kv_put` → `mahavishnu_kv_get` returns the stored value.
- `mahavishnu_upsert_service` → `mahavishnu_list_services` returns the
  record, with its own fields intact. **This is the defect**: the
  upsert used to report success and store nothing.
- `mahavishnu_record_event` → `mahavishnu_list_events` returns the event.
- `mahavishnu_kv_list("ecosystem-services/")` sees the record the
  ecosystem-state tool wrote — the shared-store property, read through
  the public KV surface a sibling component would use.
- `mahavishnu_kv_list("approval-history/")` is **denied** for the
  internal principal: the namespace's owning permission is required, and
  the internal service role holds ecosystem-state rights only (§ 10.1).
- `mahavishnu_kv_list("")` and `mahavishnu_kv_list("a")` are **denied**:
  both reach every (or the approval) namespace, so they need the
  corresponding read permissions (§ 10.1, "the prefix direction").
- `mahavishnu_kv_put("approval-history/…")` is **denied**: the domain
  namespaces are write-protected (§ 10.1, "a read permission must not
  authorise a mutation").

### The full-suite failures are pre-existing

128 unique failing test IDs were extracted from the full run and
re-run against a pristine `HEAD` worktree: **122 fail identically at
HEAD**. Of the remaining six, four also fail in that worktree's own
full run (global-counter / registry assertions that are
order-dependent), and the last two have explanations that have nothing
to do with this change:

- `test_register_atomic_under_concurrent_writes` — an artifact of the
  `--import-mode=importlib` workaround, not of this change. The default
  import mode cannot collect the whole suite because
  `tests/unit/test_config.py` and `tests/unit/test_core/test_config.py`
  share a module basename and neither directory has an `__init__.py`
  (pre-existing; `git grep` shows both files unchanged since
  2026-10-30). Under `importlib` mode pytest names the test module
  `tests.integration.test_worktree_session_registry_concurrent`, and
  the `multiprocessing` spawn child then fails to import it — because
  `tests` resolves to `site-packages/tests`, which shadows the repo's
  own `tests` package on the child's `sys.path`. Under the default
  prepend mode the module is named flat and the child's import works;
  the test passes here in that mode.
- `test_generate_embedding_returns_mock_on_no_sources` — not an
  assertion failure at all: the xdist worker **crashed** while running
  it under the parallel load. It passes in isolation.

**No failure in the full run is attributable to this change.**

## 10. Security review findings

An automated security review of the committed change raised three
findings. All three were accepted as valid, and all three are addressed
below. Two of them were *introduced* by this plan, which is exactly why
they are worth writing down.

### 10.1 The shared store widened the KV tools' blast radius

**Finding.** The four `mahavishnu_kv_*` tools are gated on
`READ/WRITE_ECOSYSTEM_STATE` and can now reach **any** key in the
shared store — including `approval-history/`, `webhook-ingress/` and
`workflow-results/`. Before the store was shared, their blast radius
was the plan_index lock keys only. A principal that could read the
ecosystem registry could thereby read every approval decision, every
webhook receipt and every workflow outcome.

**Response.** Namespace-scoped permissions. Each domain-owned namespace
carries the permission that owns **reading** it, and the KV tools
require **both** the base permission and the namespace's:

| Namespace | Owning read permission |
|---|---|
| `approval-history/` | `READ_APPROVAL` |
| `webhook-ingress/` | `READ_WEBHOOK` |
| `workflow-results/` | `VIEW_WORKFLOW_STATUS` |
| everything else (`plan_index/`, budgets, envelopes, …) | base only |

The tool body asks the same question the decorator asked — via
`resolved_user_id()`, which reads the middleware's Context state
through the `get_context()` contextvar, so the namespace check
authorizes the same principal the gate did. The internal self-call
role holds ecosystem-state rights only, so it cannot reach the
domain-owned namespaces.

Two refinements, both of them real bypasses found by a second review
of the first implementation:

**The prefix direction.** The store matches keys by prefix, so a
listing prefix reaches a protected namespace in **two** directions,
and checking only one of them leaks it:

- `prefix.startswith(namespace)` — the prefix is inside the namespace
  (`"approval-history/apr-1/"`).
- `namespace.startswith(prefix)` — the prefix *truncates* the
  namespace, so the listing still returns its records. The empty
  prefix truncates every namespace; so does `"a"` for the approval
  namespace; so does `"approval-history"` without its trailing
  separator.

The first implementation checked only the forward direction, so
`mahavishnu_kv_list("")` — which returns *every* key in the store —
was readable by any principal holding the base permission. The
scoping now resolves the namespace from the **matched keys**, in both
directions, and requires *every* implicated permission.

Defence in depth: after the listing, each returned key is checked
against its own namespace, and an item the caller may not read is
dropped. A mis-scoped prefix cannot leak a record even if the prefix
logic is wrong again.

**A read permission must not authorise a mutation.** The domain
namespaces are written by the server's **own** producers, in process,
through the substrate facade — never through the public KV surface.
There is no write permission for them, and `READ_APPROVAL` must not
stand in for one. `mahavishnu_kv_put` and `mahavishnu_kv_delete`
therefore **deny** those namespaces outright
(`NAMESPACE_WRITE_PROTECTED`) rather than authorise the mutation with
a read permission.

### 10.2 The approval reader discarded the caller's credential

**Finding.** `list_approval_history` checked that the caller's token
was JWT-*shaped* (`len(token.split(".")) == 3`), then threw it away and
read the records under the **internal** self-call credential. Any
three-segment string therefore passed the gate.

**Response.** The reader now verifies the token against the configured
JWT secret — signature and expiry, via `JWTManager.verify_token` — and
reads as the principal that token names. The server applies that
principal's RBAC, and the namespace check of § 10.1 applies on top.
A missing, malformed, expired or unsigned token yields no identity and
the read is refused. The internal credential is no longer used for a
user-facing read.

Defence in depth: a record whose `approval_id` does not match the
requested one is skipped rather than returned.

### 10.3 The producers reported success for a write that never landed

**Finding.** `substrate.put` swallowed its own write failures, and
every producer incremented `succeeded` unconditionally. A missing audit
record was indistinguishable from a written one — the `*_persistence_skipped`
counters and warnings that made it detectable had been removed along
with the "substrate unbound" branch.

**Response.** `substrate.put` returns whether the record landed, and the
producers report accordingly: `succeeded` only when it did, `skipped`
and a `*_persistence_skipped` warning when it did not. The counters
and warnings are back — they now report a *failed write* rather than an
*unbound substrate*, but they are the same control.

### 10.4 Residual gaps (not introduced here, not closed here)
1. The MCP tools' identity is argument-derived for **non-internal**
   principals: `require_mcp_auth` reads the `user_id` argument, and
   `extract_auth_from_request` prefers that argument over the
   `Authorization` header without verifying a signature. A caller that
   reaches the server directly can therefore claim any registered user
   id. Closing this means making the gate prefer the middleware's
   *verified* identity — a change to the auth model for every tool,
   well beyond this plan's scope. The internal principal is already
   credential-gated.
2. The store is process-local (§ 3, non-goal 1), so the approval,
   webhook and workflow logs do not survive a restart.

**Follow-ups not in this plan:**

1. The live server was restarted as part of this change so it runs the
   fixed code. The in-process store starts empty, so the ecosystem
   registry, the workflow outcome log, the approval decision log and the
   webhook ingress log begin empty — they were being written nowhere
   before, so nothing was lost.
2. The duplicate test-module basename (`tests/unit/test_config.py` vs
   `tests/unit/test_core/test_config.py`) blocks a default-mode
   full-suite collection. It is pre-existing and out of scope here, but
   it makes `--import-mode=importlib` necessary, and that mode breaks
   the `multiprocessing`-spawn tests via the `site-packages/tests`
   shadow. Worth fixing separately (add `__init__.py` files, or
   rename one of the two).
   **Resolved 2026-11-05:** `tests/unit/test_core/` is now a package, so
   its `test_config.py` resolves to `test_core.test_config` and no longer
   collides. Default-mode collection now succeeds with 0 errors, and the
   `multiprocessing`-spawn tests pass in that mode.
   `scripts/audit_test_module_names.py` guards the invariant.
