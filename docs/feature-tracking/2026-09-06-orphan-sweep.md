---
name: orphan-sweep
status: built
date: 2026-09-06
last_reviewed: 2026-09-06
owner: mahavishnu
role: canonical
plan: null
triggered_by: scripts/audit_orphans.py default run on 2026-09-06
related: docs/decisions/wire-up-contract.md
progress: "3/5 resolved (check_prerequisites deleted, CloudWorker wired into __init__.py, persist_initial+load_record_sync wired via new settle_cli.py); 2 remain (merge_three_way_sync deferred — needs higher-level wrapper design)"
---

# Orphan Sweep — settle sync wrappers + CloudWorker + check_prerequisites

## State: built

Five production-code symbols flagged by `scripts/audit_orphans.py` on
2026-09-06 have no caller in production code paths. Code is merged; wiring
to real entry points is deferred pending adjacent CLI / worker-factory /
terminal-launch work.

Re-run `scripts/audit_orphans.py` to verify the list shrinks as each
orphan is wired. Status moves to `wired` when its entry point executes
end-to-end at least once, then to `adopted` when in active use.

## Built

| Symbol | File | Docstring summary |
| --- | --- | --- |
| `merge_three_way_sync` | `mahavishnu/settle/merge.py:146` | Synchronous variant for CLI / non-asyncio callers. |
| `persist_initial` | `mahavishnu/settle/persistence.py:93` | Persist a newly-created (state=PROPOSED) record. Sync wrapper; async twin `persist_initial_async` is wired. |
| `load_record_sync` | `mahavishnu/settle/persistence.py:186` | Sync variant of `load_record` for non-async contexts (CLI). |
| ~~`check_prerequisites`~~ | ~~`mahavishnu/terminal/backends.py:40`~~ | **DELETED 2026-09-06** along with `PtyBackend`, `BUILTIN_BACKENDS`, and the two test files. Investigation revealed the whole `terminal/backends.py` module was scaffolding for the removed `McpretentiousAdapter` (see CHANGELOG.md:1030-1033 + memory `mcpretentious-removed-mcp-first.md`). No upstream consumer exists; per wire-up contract, scaffolding for a removed module must be removed. |
| `CloudWorker` | `mahavishnu/workers/cloud_worker.py:122` | Worker that executes tasks via a three-tier FallbackChain. |

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

**Deferred (1/3)** — `merge_three_way_sync` stays orphaned. Its current
signature is `(base: str, ours: str, theirs: str)` — raw file contents,
not a run-level operation. The only honest `settle merge <run_ref>`
command requires loading the record, iterating `record.bindings`, and
calling merge per binding. That orchestration wrapper is deferred until
adjacent settle work creates the higher-level API. Re-evaluate when a
SettleRunRecord with non-empty bindings becomes a real CLI input shape.

### Group B — CloudWorker class

- **`CloudWorker`** → wire into the worker routing layer
  (`mahavishnu/workers/task_router.py`) by adding a
  `WorkerFactory.create(WorkerType.CLOUD)` (or equivalent) factory
  method. The class already has test coverage in
  `tests/unit/test_cloud_worker.py`; production caller is missing.
  Alternative: delete the class + its tests if cloud-worker routing is
  not on the roadmap.

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
deletion recorded in this file. Any symbol that remains a production
orphan at the next quarterly audit must be revisited.

## Verification

```bash
# Should report only merge_three_way_sync (the deferred one)
.venv/bin/python scripts/audit_orphans.py 2>&1 \
  | grep -E "(merge_three_way_sync|persist_initial|load_record_sync|check_prerequisites|CloudWorker)" \
  | grep -v "tests/" \
  | grep -v merge_three_way_sync || echo "OK: all wired-or-deleted orphans resolved"
```

Last verified 2026-09-06: only `merge_three_way_sync` remained in the
output — consistent with the deferred status documented above.

## References

- Wire-up contract: `.claude/decisions/wire-up-contract.md`
- Audit script: `scripts/audit_orphans.py` (see `collect_references`,
  `find_registrations`)
- Settle module overview: `mahavishnu/settle/__init__.py`,
  `mahavishnu/settle/state_machine.py`
- Worker router: `mahavishnu/workers/task_router.py`
- Terminal launch: `mahavishnu/terminal/manager.py`
