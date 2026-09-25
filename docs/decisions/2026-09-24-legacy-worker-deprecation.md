---
status: accepted
date: 2026-09-25
supersedes: (none)
related: .claude/plans/nifty-gliding-stallman.md v3, Phase 4 + 4.5b + Phase 1m
---

# 2026-09-25 — Retire the legacy isolated-worker surface (`apple_container`, `e2b_sandbox`); keep `shepherd_backend`

## Status

Accepted, 2026-09-25. Implements Phase 4 + Phase 4.5b of the v3 plan.

## Context

`mahavishnu/workers/manager.py::_create_isolated_worker` historically supported
three isolated-worker backends:

- `apple_container` — Apple silicon microVMs (Phase 2 surface).
- `e2b_sandbox` — cloud microVMs (Phase 2 surface).
- `shepherd` — OS-level syscall-jail (added in Phase 3 v2 plan).

The `apple_container.py`, `e2b_sandbox.py`, and other legacy worker modules
have become dead-code-only (no production importers; only test files
reference them). The pool-based orchestration layer (`mahavishnu/pools/`)
has superseded the worker-manager dispatch path for new workloads. The
remaining live path is `shepherd` via `mahavishnu/workers/shepherd_backend.py`,
which the user elected to KEEP per the v3 plan's "no backwards compat"
stance.

## Decision

`_create_isolated_worker` now supports ONLY `worker_type="shepherd"`. Any
other value (e.g. `"apple-container"`, `"e2b-sandbox"`, `"apple_container"`,
`"e2b"`, etc.) raises `ValueError` with a helpful message that points to
this ADR.

The 11 dead worker files in `mahavishnu/workers/` are deleted by Phase 4.5b
in the same release:

- `a2a.py`, `apple_container.py`, `application.py`, `crow.py`,
  `e2b_sandbox.py`, `generic_shell.py`, `ollama.py`, `openclaw_gateway.py`,
  `protocol.py`
- `capabilities/_cache.py`, `capabilities/_static.py`

Live infrastructure retained:

- `__init__.py` (shrunk to live symbols)
- `base.py` (BaseWorker, WorkerResult)
- `capabilities/{_observability,_probes,_report,_safe,_states}.py`
- `contract/` (7 files — settle infrastructure, still live)
- `manager.py` (load-bearing — keeps its `WorkerManager` outer class;
  only `_create_isolated_worker` is narrowed)
- `registry.py` (the `WORKER_REGISTRY` that callers use)
- `cloud_worker.py` — until the post-Phase-3b cleanup fully drains it
- `openhands.py` (OpenHands adapter; live)
- `shepherd_backend.py` (the surviving isolated-worker backend)
- `_exec_guard.py` (still referenced by `shepherd_backend.py`)

## Caller migration path

For legacy callers:

- Replaced Apple-container / E2B-sandbox calls: use
  `worker_type="shepherd"` with an explicit `writable_root` kwarg.
- Dispatch via `mahavishnu/pools/` for any new orchestrated workload.
  See `docs/POOL_ARCHITECTURE.md` and `mahavishnu/mcp/tools/pool_tools.py`.

## Consequences

- `_create_isolated_worker` becomes a 1-branch function: shepherd happy
  path + ValueError default. Simpler audit surface.
- `WorkerLifecycleState` and `WorkerRecordStore` machinery remains
  unchanged — settle infrastructure unaffected.
- Documentation drift: `CLAUDE.md:726` lists `e2b_sandbox` and
  `apple_container` as live isolated workers; Phase 4.5b updates the
  same commit that deletes the files.
- Test surface reduction: 14 of the 18 test files in Phase 4.5b's
  deletion list have NO replacement in the live surface (per
  `tests/unit/pools/test_mahavishnu_pool.py` etc. don't cover
  WorkerResult.from_dict). This is documented in §10 (Known Adjacent
  Gaps).

## Rollback signal

Live deployment failure if any historical caller is still reaching
`WorkerManager._create_isolated_worker` with a non-`shepherd` type.
Mitigated by the explicit `ValueError` envelope: every unsupported
worker_type results in a clear `ValueError` traceback that operators
can grep for. The ADR reference in the error message directs them
back to this file.

## Follow-ups

- Cloud worker requires transition to `mahavishnu/core/model_routing.py`
  post-Phase 3b (already done; tracked under §10).
- `_main_cli.py` may have vestigial references to deleted worker types;
  audit per Phase 0's Phase 4.5b task. (Phase 0 inventory found ZERO
  such references; no action.)
- `pools/mahavishnu_pool.py` still imports `WorkerManager` and
  `get_worker_entry` from `mahavishnu.workers.manager`/`registry` —
  a follow-up refactor should switch the pool to `pool_manager.route_task`
  shape and drop the worker-manager wrapping entirely.

## References

- `.claude/plans/nifty-gliding-stallman.md` v3 — Phase 4 + 4.5b
- `mahavishnu/workers/manager.py` — `_create_isolated_worker` (narrowed)
- `mahavishnu/workers/shepherd_backend.py` — surviving isolated backend
- `docs/CLAUDE.md` (root project's index) — line 726 update in Phase 4.5b
- `docs/architecture/MEMORY_ARCHITECTURE.md` — references pool tools; unaffected
- `docs/POOL_ARCHITECTURE.md` — documents the canonical orchestration layer
