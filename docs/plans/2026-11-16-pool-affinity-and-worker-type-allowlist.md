---
status: complete
role: implementation
kind: plan
date: 2026-11-16
last_reviewed: 2026-11-16
superseded_by: null
topic: pool-routing-affinity
title: "Make pool affinity reachable and the worker-type allowlist agree with the registry"
requirements:
- id: REQ-AFFINITY-001
  title: "pool_affinity honours a server-side, operator-configured allowlist"
- id: REQ-AFFINITY-002
  title: "The affinity allowlist is derived from settings, never from wire input"
- id: REQ-WORKERTYPE-001
  title: "The CLI and the MCP spawn tool accept the same pool-capable worker types"
- id: REQ-WORKERTYPE-002
  title: "The pool-capable worker-type set is derived from the worker registry"
---

# Make pool affinity reachable and the worker-type allowlist agree with the registry

## 1. Outcome

`mahavishnu_pool_route_execute(pool_selector="affinity", pool_affinity="<pool_id>")`
dispatches to the pool the caller named, and `mahavishnu pool spawn --worker-type
terminal-claude` is accepted by the CLI the same way the MCP tool accepts it.

**Success signal:** a dispatch naming a registered pool lands on that pool (the
response's `pool_id` equals the one named) instead of falling back to
LEAST_LOADED; and `mahavishnu pool spawn --worker-type terminal-claude` exits 0.

## 2. Goals

1. Wire `caller_pool_allowlist` so the AFFINITY selector can honour a pool.
1. Keep ADR-014's boundary: the allowlist is server-side, never wire-supplied.
1. Make the allowlist operator-configurable per caller kind.
1. Derive the pool-capable worker-type set from the worker registry so the CLI
   and the MCP tool cannot drift apart again.
1. Correct the "retired on 2026-09-24" claim about the `terminal-*` worker types,
   which the pool path has been running live ever since.

## 3. Non-Goals

1. Not changing the pool selection *order* — only making AFFINITY reachable.
1. Not adding a new MCP tool, and not changing `pool_route_execute`'s schema.
1. Not reintroducing the `apple-container` / `e2b-sandbox` / `container-executor`
   backends; their modules are deleted.
1. Not changing `CallerKind`'s quota semantics — it stays attribution-only.

## 4. Current Findings

1. **`pool_affinity` is a silent no-op.** `PoolManager._route_by_affinity`
   (`mahavishnu/pools/manager.py:1320`) refuses to honour affinity unless
   `caller_pool_allowlist` is non-`None`, and falls back to LEAST_LOADED with
   only a `logger.debug`. Nothing in the repo sets it: the MCP tool's
   `_dispatch_internal` (`mahavishnu/mcp/tools/pool_tools.py:462`) does not
   pass it, and no settings key binds it. Observed 2026-11-16: three
   dispatches naming a pool all landed on `mahavishnu_4844515216`.

1. **The CLI refuses the worker types the pool path runs.** The CLI's
   `SPAWN_WORKER_TYPE_ALLOWLIST` (`mahavishnu/_main_cli.py:2036`) is
   `{"shepherd", "gateway-openclaw"}`, and its comment claims `terminal-claude`
   and friends "were retired on 2026-09-24". The ADR it cites
   (`docs/decisions/2026-09-24-legacy-worker-deprecation.md`) retired
   `apple_container` and `e2b_sandbox` and explicitly *retained* `registry.py`
   ("the `WORKER_REGISTRY` that callers use"); it narrowed
   `_create_isolated_worker` to `shepherd`, which is a different surface.
   `WorkerManager._create_worker` (`mahavishnu/workers/manager.py:530`) routes
   every `RuntimeKind.SHELL` entry to `ShellWorker`. Observed 2026-11-16: a
   `terminal-claude` pool (`merge-review`, `claude-pool`) ran a real Claude
   Code session and returned `result: "PONG"`.

1. **The MCP tool is the looser of the two, and it is the one that is wrong.**
   `mahavishnu_pool_spawn` validates against `WORKER_REGISTRY.keys()`, which
   still lists `apple-container` and `e2b-sandbox` — the backends whose modules
   were deleted. So the CLI refuses the working types and the MCP tool admits
   the dead ones.

1. **The repo already documents the contradiction.** The "no pool available that
   can honour task['cwd']" refusal in `mahavishnu/pools/manager.py:897` tells the
   operator to run `mahavishnu pool spawn --type mahavishnu --name merge-review
   --worker-type terminal-claude` — a command the CLI refuses.

1. **The registry carries the fact the allowlist needs.** `WorkerConfig` has
   `runtime_kind`, and `MahavishnuPool.__init__`
   (`mahavishnu/pools/mahavishnu_pool.py:179`) already computes
   `_worker_runtime_kind` from it. The pool already knows whether its worker
   carries a prompt.

## 4.5 Requirements

- **REQ-AFFINITY-001** — `pool_affinity` names the pool the dispatch lands on,
  when that pool is in the caller's allowlist.
- **REQ-AFFINITY-002** — the allowlist comes from settings. A wire caller
  cannot widen or narrow it; `caller_kind` stays attribution-only.
- **REQ-WORKERTYPE-001** — the CLI and the MCP spawn tool accept and reject the
  same worker types.
- **REQ-WORKERTYPE-002** — the accepted set is computed from the worker
  registry, so a new registry entry cannot need a matching allowlist edit.

## 5. Phases

### Phase 1 — Derive the pool-capable worker-type set

Add `pool_capable_worker_types()` to `mahavishnu/workers/registry.py`: every
`RuntimeKind.SHELL` entry, plus `shepherd`, plus `gateway-openclaw`. Use it in
`mahavishnu/_main_cli.py` (allowlist, error hint, help text) and in
`mahavishnu/mcp/tools/pool_tools.py` (`pool_spawn` validation).

Rewrites `tests/unit/cli/test_spawn_allowlist.py`, which currently pins the
inverse — that `terminal-claude` is rejected.

**Integration Contract**

- Triggered from: `mahavishnu pool spawn`, `mahavishnu_pool_spawn`.
- Returns to / updates: the operator's spawn command; the pool registry.
- Demonstrable by: `mahavishnu pool spawn --worker-type terminal-claude` exits 0.
- Rollback signal: a spawn that used to succeed now fails the allowlist check.
- Observability added: the error hint enumerates the live set.
- Requirements: REQ-WORKERTYPE-001, REQ-WORKERTYPE-002.

### Phase 2 — Wire the affinity allowlist

Add `pools.caller_pool_allowlist` to `PoolConfig` (`mahavishnu/core/config.py`):
a mapping of caller kind → pool names/ids, with `"*"` for "all registered
pools". `PoolManager` resolves it per call — names to ids via `_pools_by_name`
— and `route_task` uses it when the caller did not supply one.

**Integration Contract**

- Triggered from: every `PoolManager.route_task` call.
- Returns to / updates: the pool selection decision; the routing-decision audit
  record.
- Demonstrable by: a dispatch naming a registered pool returns that pool's id.
- Rollback signal: a dispatch that reached a pool by name now does not.
- Observability added: the routing-decision record carries the effective
  allowlist.
- Requirements: REQ-AFFINITY-001, REQ-AFFINITY-002.

### Phase 3 — Correct the documentation

`docs/pools/POOL_ARCHITECTURE.md`, the CLI error hint, and
`docs/followups/2026-10-09-spawn-cli-stale-worker-allowlist.md` all carry the
incorrect "retired" claim. Correct them and record the registry-derived rule.

**Integration Contract**

- Triggered from: a reader following the retirement note.
- Returns to / updates: the docs.
- Demonstrable by: no doc claims `terminal-claude` is retired.
- Rollback signal: n/a — prose.
- Observability added: n/a — prose.
- Requirements: REQ-WORKERTYPE-001.

## 6. Verification

1. `pytest tests/unit/cli/test_spawn_allowlist.py tests/unit/pools/ -q`
1. `pytest tests/unit/mcp/test_pool_tools.py tests/unit/test_mcp_pool_tools.py -q`
1. `pyscn analyze --config .pyscn.toml --select complexity --min-complexity 16`
1. `ty check` on every touched file.
1. A live dispatch naming a registered pool returns that pool's id.
