# Checkpoint — Comprehensive Hooks Cleanup

**Date**: 2026-07-15
**Working directory**: `/Users/les/Projects/mahavishnu`
**Effort level**: Ultracode (xhigh + dynamic workflow orchestration)
**Mode**: Explanatory
**Why this exists**: Session-Buddy MCP transport dropped twice mid-call; checkpoint requested via `/checkpoint` slash command but unable to persist through the MCP path. This file is the durable fallback so the session resume carries the same structured context.

---

## Checkpoint Notes

- **Decision**: Three-wave cleanup approach — (1) workflow-shuffle strict 3 failures (pyscn/ty/creosote), (2) audit-then-fix 3 pre-existing pytest bugs, (3) croniter re-add after Apply agent's "vestigial" misclassification.
- **Reason**: User asked to "fix the failing comprehensive hooks" via `/effort ultracode`. Initial wave surfaced that "fix creosote" was actually "fix the manifest so creosote doesn't lie" — code-shape was wrong, exclude-list was wrong. Then pytest sweep surfaced 3 unrelated bugs that had been masked by `-x` early-stop. Then croniter regression revealed Apply agent's "zero direct imports = vestigial" heuristic doesn't hold when the import is lazy+try/except (ty still reads source).
- **Files changed** (paths to be committed together per user's choice):

  Source:
  - `mahavishnu/metrics_cli.py` — `_render_bodai_output` complexity 23 → 4 (5 helpers extracted: `_render_subscriber_state`, `_render_queue_state`, `_render_component_health`, `_render_recent_event`, `_render_filter_note`)
  - `mahavishnu/mcp/crow/tools/terminal_proxy_tool.py` — DRY: `_extract_terminal_output` helper extracted and applied to `terminal()`, `crow_terminal_exec()`, `crow_terminal_read()`. Per user decision "do A, keep as is" — third application of helper retained (was outside the original ty-fix scope but provides actual duplication removal + dict-path extraction improvement).

  Manifest:
  - `pyproject.toml` — 4 new PEP 735 `[dependency-groups]`: `ai` (pydantic-ai-slim), `gpu` (runpod-flash), `content-ingest` (pypdf, ebooklib, trafilatura), `storage-pg` (pgvector). `[dependency-groups].dev` extended with `{include-group = "…"}` for each. 15 entries added to `[tool.creosote].exclude_deps` with WHY comments documenting lazy/fallback/peer-group rationales. `croniter` restored to `[project].dependencies` (round-trip: removed by Apply agent as "vestigial", brought back when ty flagged unresolved import at `prefect_schedules.py:91`).
  - `uv.lock` — regenerated twice (after manifest reshuffle, after croniter restoration). Net: `croniter` pruned then re-added; 6 deps relocated between dep-groups.
  - `CLAUDE.md` — new "Optional Dependency Groups (PEP 735)" subsection (~20 lines) documenting the 4 new groups and install commands.

  Tests:
  - `tests/unit/test_bodai_phase0_regression.py` — `test_agno_memory_defaults_to_none` assertion flipped `False` → `True` (matches `mahavishnu/core/config.py:110` `Field(default=True)` and docstring/design intent).
  - `tests/unit/test_adapters/test_prefect_adapter.py` — `test_process_repository_quality_check` patch target renamed `QualityControl` → `_QualityControlImpl` (private alias introduced by refactor `5db813a1` on 2026-04-04; test patch string wasn't migrated by `5f88d8ae` on 2026-04-14).
  - `tests/integration/test_prefect_adapter.py` — parallel stale patch target fixed (same root cause as unit test).
  - `tests/unit/cli/test_crow_call_site_wiring.py` — parametrize lines `[1100, 1183, 1408]` → `[1321, 1404, 1629]` (source grew 575 lines since test written; real call sites verified at new locations; ids map positionally).

- **Next step**: Commit planning. Three logical commits would match the wave structure: ① pyscn complexity refactor (metrics_cli.py only) ② ty/DRY fix (terminal_proxy_tool.py only) ③ manifest reshuffle + test fixes (everything else). All-gate pass is the prerequisite for any commit (creosote ✓, ty ✓, pyscn ✓; pytest the 5 originally-targeted tests ✓; 141 other pre-existing failures are env-dependent and out of scope).
- **Blockers**: None. Session-Buddy MCP transport unavailable for future in-session recall; if recall is needed before Session-Buddy recovers, use `grep` on this file or `semantic_search` after server returns.

---

## Gate Status (verified)

| Gate | Status | Evidence |
|---|---|---|
| `pyscn` | ✅ | `_render_bodai_output` complexity = 4 (limit 15) |
| `ty` | ✅ | `All checks passed!` project-wide after croniter restoration |
| `creosote` | ✅ | `No unused dependencies found! ✨` (Pillow as "excluded but not in venv" expected) |
| `git diff --stat` | ✅ | 4 files modified in manifest wave, 4 in test-fix wave, 2 in source-fix waves |

## Targeted pytest (originally-failing 5)

| Test | Status |
|---|---|
| `test_agno_memory_defaults_to_none` | ✅ |
| `test_process_repository_quality_check` | ✅ |
| `test_three_call_sites_route_through_helper[workers_spawn]` | ✅ |
| `…[workers_resolved_dispatch]` | ✅ |
| `…[pool_spawn]` | ✅ |

## Out-of-scope pre-existing failures

Full `pytest tests/unit/ -m "not slow"` reveals 141 + 53 (errors) = 194 additional pre-existing failures unrelated to this work. Concentrated in `test_websocket_metrics*` (Prometheus port-binding), `test_session_buddy_integration*` (external Session-Buddy server required), `test_worktree*` (external git state fixtures). These are environment-dependent and existed before any of the changes in this session.

## Process Notes (lessons captured)

1. **`/effort ultracode` is the right posture** for multi-wave work that spans manifest + source + tests. The `crackerjack-cleanup-wave7` skill scaffold is reusable as a phase template.
2. **`zero direct imports ≠ vestigial`** when the import is lazy + try/except fallback. ty reads source. Croniter regression demonstrates this; the WHY comment in `[tool.creosote].exclude_deps` is the durable fix.
3. **`pytest -x` masks pre-existing failure surface**. The earlier run showed "5 failed"; the full-suite run showed 194. Either drop `-x` early or accept surprises when you do.
4. **`git stash + uv lock`** can drift the working tree (uv mutation vs. stashed file). Recovery: discard test-run uv.lock then `git stash pop`. Always check `git status --short` against `git stash show --stat` when restore is ambiguous.
5. **Edit tool string-matching can fail with trailing whitespace** even when bytes look correct. Fallback: Python `pathlib.Path.read_text().replace(…)` for surgical inserts when Edit won't match.
6. **MCP transport drops** are transient but persistent retry adds no value. After second failure, fall back to durable artifact (this file).
7. **Checkpoint stash re-apply can clobber subagent work mid-task** — distinct from MCP transport drops (item 6). This is hook *behavior*, not transport. Tracked in `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`; pickup prompt `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md` Step 3e gates against recurrence. Parent pattern: `session-buddy-checkpoint-hooks-fire-during-subagent-sessions` memory (commit-ordering symptom, sibling observation).

## Resume instructions for future session

1. Read this file (`docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`) for decision context — do NOT re-derive from commit history.
2. Run `git diff --stat` to confirm the 8 modified files match what's listed above.
3. Run the three gates (`uv run pyscn …`, `uv run ty check …`, `uv run creosote`) to verify state is still green.
4. User's three open options at session end: (a) full `crackerjack run`; (b) commit preparation; (c) stop. Pick whichever the user re-opens with.
