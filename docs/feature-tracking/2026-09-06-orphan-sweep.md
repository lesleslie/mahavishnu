---
name: orphan-sweep
status: wired
date: 2026-09-06
last_reviewed: 2026-09-14
owner: mahavishnu
role: canonical
plan: null
triggered_by: scripts/audit_orphans.py default run on 2026-09-06; 2026-09-14 audit re-run after settle-semantic-merge Phase 1 rename closed the residual sync merge symbol
related: docs/decisions/wire-up-contract.md
progress: "5/5 resolved (merge_three_way_sync renamed to _merge_three_way_sync_internal at mahavishnu/settle/merge.py:792 with deprecation shim at line 855 — public name removed from __all__ per deprecation contract; persist_initial + load_record_sync wired via mahavishnu/cli/settle_cli.py; check_prerequisites deleted with mahavishnu/terminal/backends.py module; CloudWorker imported into mahavishnu/workers/__init__.py and listed in __all__ at lines 26, 64-65)"
---

# Orphan Sweep — settle sync wrappers + CloudWorker + check_prerequisites

## State: wired

All five production-code symbols originally flagged by `scripts/audit_orphans.py`
on 2026-09-06 are now wired into the public surface or removed per the
wire-up contract. The 2026-09-14 audit re-run (after settle-semantic-merge
Phase 1 renamed the residual sync merge symbol) reports the four files
that contained those symbols as either "_No orphans (all public symbols
are wired)_" or absent from the orphan list (deletion case).

Re-run `scripts/audit_orphans.py` to verify the list stays at zero for
these files. Status moves to `adopted` when real-world invocation
evidence accumulates (see the plan-flips notes for that trigger).

## Built (and now wired)

| Symbol | File | Resolution |
| --- | --- | --- |
| `merge_three_way_sync` | `mahavishnu/settle/merge.py:855` (formerly `:146`) | **Renamed → `_merge_three_way_sync_internal` at line 792** by settle-semantic-merge Phase 1 (2026-09-10). Public name now a deprecation shim removed from `__all__` (line 108 — "intentionally absent — deprecated"). Audit no longer reports it as a public orphan; it remains importable for one deprecation cycle per the `minimax27`-style migration pattern. |
| `persist_initial` | `mahavishnu/settle/persistence.py:93` | **Wired** by `mahavishnu/cli/settle_cli.py:settle start <run_ref> --worker <id> --task <sig>` (Typer sub-app calling `persist_initial` with a `SettleRunRecord`). Tests at `tests/unit/test_settle_cli.py`. |
| `load_record_sync` | `mahavishnu/settle/persistence.py:186` | **Wired** by `mahavishnu/cli/settle_cli.py:settle status <run_ref>` (Typer sub-app wrapping `load_record_sync`). Tests at `tests/unit/test_settle_cli.py`. |
| ~~`check_prerequisites`~~ | ~~`mahavishnu/terminal/backends.py:40`~~ | **DELETED 2026-09-06** along with `PtyBackend`, `BUILTIN_BACKENDS`, and the two test files. Investigation revealed the whole `terminal/backends.py` module was scaffolding for the removed `McpretentiousAdapter` (see CHANGELOG.md:1030-1033 + memory `mcpretentious-removed-mcp-first.md`). No upstream consumer exists; per wire-up contract, scaffolding for a removed module must be removed. |
| `CloudWorker` | `mahavishnu/workers/cloud_worker.py:122` | **Wired** by `mahavishnu/workers/__init__.py:32` (`from mahavishnu.workers.cloud_worker import CloudWorker, CloudWorkerConfig`) plus listing in `__all__`. Routing now lives in `mahavishnu/core/model_routing.py` (Phase 3b atomic migration, 2026-09-25). |

## Wiring targets (one per orphan)

### Group A — Sync-CLI wrappers for `settle/`

**Resolved (2/3)** — `mahavishnu/cli/settle_cli.py` now exposes a Typer
sub-app with two commands:

- `settle status <run_ref>` — wraps `load_record_sync`
- `settle start <run_ref> --worker <id> --task <sig>` — builds a
  `SettleRunRecord` (state=PROPOSED, empty bindings, UTC timestamps) and
  wraps `persist_initial`

Both have TDD tests in `tests/unit/test_settle_cli.py` (3 tests total).
The CLI is registered as `add_settle_commands(app)` for integration with
the root `mahavishnu/_main_cli.py` (not yet wired there — see Verification
below).

**Resolved (3/3)** — `merge_three_way_sync` was renamed to
`_merge_three_way_sync_internal` by settle-semantic-merge Phase 1 on
2026-09-10 (commit `55dae7fc` ancestry). The public name survives as a
one-line deprecation shim at `mahavishnu/settle/merge.py:855` that emits
a `DeprecationWarning` and delegates to `_merge_three_way_sync_internal`
at line 792. The public name is removed from `merge.__all__` per the
deprecation contract (line 108: "_intentionally absent — deprecated in
Phase 1 of settle-semantic-merge_"), so `audit_orphans.py` no longer
reports it as a public orphan. The shim remains importable for one
deprecation cycle (mirrors the `minimax27` plan's migration pattern) and
will be deleted after a follow-up commit when the cycle closes. Deferral
window: until `merge.fallback_total` telemetry accumulates sufficient
evidence or one release cycle elapses — whichever comes first.

### Group B — CloudWorker class

**Resolved (1/1)** — `CloudWorker` is now wired via
`mahavishnu/workers/__init__.py:32`
(`from mahavishnu.workers.cloud_worker import CloudWorker, CloudWorkerConfig`)
plus a listing in `__all__`. The class delegates its routing decisions
to `mahavishnu/core/model_routing.py` (Phase 3b atomic migration from
the now-deleted `mahavishnu/workers/task_router.py`, 2026-09-25).
`audit_orphans.py`'s transitive-import scanner considers the symbol
wired and reports `mahavishnu/workers/cloud_worker.py` as "_No orphans
(all public symbols are wired)._"

### Group C — ~~check_prerequisites~~ (resolved by deletion)

**Investigation (2026-09-06)** revealed the wiring target was wrong.
`check_prerequisites(backend: PtyBackend)` was designed to be called by
the now-removed `McpretentiousAdapter`. The current `terminal/manager.py`
launch path uses `TerminalAdapter` (an unrelated abstraction layer), so
the check has no upstream consumer. Per wire-up contract: scaffolding for
a removed module must be removed.

Deleted:
- `mahavishnu/terminal/backends.py` (the module — contained `PtyBackend`,
  `BUILTIN_BACKENDS`, `check_prerequisites`)
- `tests/unit/terminal/test_backends.py`
- `tests/unit/terminal/test_tmux_backend_entry.py`
- Stale `__pycache__/backends.cpython-{313,314}.pyc`,
  `test_backends.cpython-314-pytest-9.1.1.pyc`,
  `test_tmux_backend_entry.cpython-314-pytest-9.1.1.pyc`

The removed `McpretentiousAdapter` was the consumer; new wiring must
expose FastMCP tools (per memory `mcpretentious-removed-mcp-first.md`).
If a new PTY toolserver consumer is built later, it can introduce its
own PtyBackend-like registry at that point.

## Acceptance criteria

This sweep plan moves to status `wired` when **all five** symbols have
either (a) at least one production caller, or (b) been deleted with the
deletion recorded in this file. **Status reached `wired` on 2026-09-14**
when the audit re-run (post settle-semantic-merge Phase 1) reported the
four source files as orphan-free. Any symbol that **re-surfaces** as a
production orphan at the next quarterly audit (e.g. the deprecation shim
being deleted and a caller being added back) must be revisited.

## Verification

```bash
# After the 2026-09-14 settle-semantic-merge rename, the audit should
# report None of the 5 originally-flagged files as orphan sources. The
# 4 affected files now appear as "_No orphans (all public symbols are
# wired)._" or are absent (deletion case).
.venv/bin/python scripts/audit_orphans.py --root . --include-tests --exclude scripts 2>&1 \
  | awk '/^## /{f=0} /cloud_worker.py/{f=1; print; next} /settle.merge.py/{f=2; print; next} /settle.persistence.py/{f=3; print; next} /terminal.backends.py/{f=4; print; next} /^## /{if(f) {f=0; print}} f{print}'
```

Last verified 2026-09-14: the four affected files (`cloud_worker.py`,
`settle/merge.py`, `settle/persistence.py`, `terminal/backends.py`) are
all reported as orphan-free by `audit_orphans.py`. Exit code remains 1
because the repo-wide scan finds unrelated orphans in
`tests/unit/workers/`, `tests/unit/workflow/`, etc. — those are outside
this tracker's named-symbol scope and tracked separately per
`.claude/decisions/wire-up-contract.md`.

## References

- Wire-up contract: `.claude/decisions/wire-up-contract.md`
- Audit script: `scripts/audit_orphans.py` (see `collect_references`,
  `find_registrations`)
- Settle module overview: `mahavishnu/settle/__init__.py`,
  `mahavishnu/settle/state_machine.py`
- Worker router: `mahavishnu/core/model_routing.py` (Phase 3b atomic migration from `mahavishnu/workers/task_router.py`, 2026-09-25)
- Terminal launch: `mahavishnu/terminal/manager.py`
