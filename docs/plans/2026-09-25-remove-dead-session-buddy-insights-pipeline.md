---
date: 2026-09-25
status: shipped
role: implementation
topic: remove-sb-insights-pipeline
last_reviewed: 2026-10-15
superseded_by: null
---

# Plan: Remove dead Session-Buddy insights pipeline + fix two display-bug regressions

## Context

The user asked three things at once:

1. **`★ Insight ─...` blocks emitted by Claude Code's Explanatory output style should be auto-captured into Session-Buddy.** Exploration confirmed the feature was fully built but had no auto-trigger, and then a deeper audit (two independent reviewer agents — empirical usage + maintenance surface) agreed the entire insights pipeline is **dead code** with no production consumer, no Akosha traces in 9+ months, and zero callers of `db.search_insights`. The right fix is to **remove it**, not to wire it up. See "Empirical evidence" below.
2. **Fix `📁 Projects: 0` in `mcp__session-buddy__reflection_stats`** — wrapper signature missing `project` param; `get_stats()` doesn't aggregate projects. Same scope as before.
3. **Fix `📅 Date: Unknown` in `mcp__session-buddy__quick_search`** — wrapper reads `timestamp`, adapter returns `created_at`. Same scope as before.

### Empirical evidence for REMOVE (consolidated from two reviewer agents)

Both `mycelium-core:code-reviewer` (maintenance surface) and `akosha-specialist` (empirical usage) ran independently and converged on the same verdict. Highlights:

**Production call inventory (zero):**
- `db.search_insights` (`reflection_adapter_oneiric.py:2722`) — **zero production callers**, only test fixtures.
- `db.store_insight` (`reflection_adapter_oneiric.py:2608`) — called only by `_extract_and_store_insights` inside `session_manager.py:1588`.
- `_extract_and_store_insights` (`session_manager.py:1525`) — only callers are `checkpoint_session:1352` and `end_session:1850`, both gated by `enable_insight_extraction=True` default but never observably fired.
- `★ Insight` extractor (`session_buddy/insights/extractor.py:147`) — internal use only.
- No MCP tool reads from `reflections_v2 WHERE insight_type IS NOT NULL`. `quick_search` calls `search_reflections` (filters `insight_type IS NULL`); `search_by_concept` calls `search_conversations` (different table).

**Akosha trace evidence (zero):**
- `akosha_query_local_traces(system="session-buddy", task_class="insight_extract|capture|checkpoint|session_end|start")` → all empty.
- `akosha_search_all_systems(query="★ Insight extraction")` → 0 hits (fallback: "No websocket invocations indexed yet").

**Git activity (zero meaningful change since Jan 2026):**
- `session_buddy/insights/`: only `064a14a8` (initial Jan 2026 seed) + `7e0ebd8d` (ty-error mechanical batch). No feature commits, no refactors, no bug fixes.
- `session_buddy/ingesters/claude_code_transcript.py`: original commit + version-bump no-op. Same flavor of orphan.
- `commands/session-buddy-{checkpoint,end,start}.md`: no functional edits since creation.

**Latent bugs the maintenance reviewer caught:**
- `reflection_adapter_oneiric.py:2945` — `except duckdb.Error, OSError:` Python 2 comma-form silently drops `OSError` from the exception list.
- `search/progressive_search.py:587` `_search_insights` is mislabeled — it actually calls `db.search_reflections`, not `db.search_insights`.
- 4 dead schema columns on `reflections_v2`: `insight_type`, `usage_count`, `last_used_at`, `confidence_score` affect every reflection query.

**Companion skill drift (the maintenance reviewer flagged):**
- `~/.claude/skills/capture-insights/SKILL.md` (outside repo, 294 lines) claims `mcp__session-buddy__extract_and_store_memory_tool` does insight capture. That tool actually does LLM-based entity extraction (`session_buddy/mcp/tools/advanced/entity_extraction_tools.py:99`). The skill misdescribes the surface.
- `~/.claude/skills/search-insights/SKILL.md` (outside repo, 419 lines) queries Akosha (`mcp__akosha__search_all_systems`), NOT Session-Buddy's `db.search_insights`.
- `~/.claude/scripts/inject-insights.sh` (131 lines, outside repo) — built but never wired in `~/.claude/settings.json`. When invoked would call `db.search_conversations` (wrong system entirely).
- `docs/features/INSIGHTS_CAPTURE.md:540` — Phase 4 ("Injection Tools") explicitly "Planned, not started". Phase 5 (Advanced Features) and Phase 6 (Documentation) also "Planned, not started".

**No cross-repo dependency:**
- Nothing outside session-buddy references `★ Insight` capture or `db.search_insights` in production.
- No `MEMORY.md` or `CLAUDE.md` rule depends on insights being functional.
- Slash commands (`session-buddy-checkpoint`, `session-buddy-end`) handle the try/except around extraction gracefully — removing the pipeline leaves them functional.

### Why REMOVE — not "invest to bring it to Anthropic's bar"

The external-pattern reviewer (general-purpose) compared Session-Buddy's design to leading memory systems: Anthropic Claude Code MEMORY.md, Letta/MemGPT, Mem0, Cline Memory Bank, Cursor `.cursorrules`, Aider. The findings reinforce REMOVE as the right call:

- **The category is largely abandoned.** No production memory system auto-captures from a human-readable output style. All four leading systems use either agent-decides (Anthropic, Letta, Mem0, Cline) or user-curated (Cursor) writes. Regex-on-output-style-blocks is the literal hippocampal-noise anti-pattern Mem0 warns against: *"An agent's recall quality is bounded not by what it can store but by how well it can suppress everything irrelevant."*
- **Letta benchmark: filesystem (74.0%) beats Mem0 graph memory (68.5%) on LoCoMo.** The bottleneck is retrieval, not storage. A specialized write-only insights table isn't even addressing the actual bottleneck.
- **Anthropic's MEMORY.md auto-memory generated user opt-out demand within weeks of launch** (GitHub anthropics/claude-code#23544). Session-Buddy's regex version has none of Anthropic's safeguards (agent-decides, 200-line cap, type discrimination, skip-derivable, opt-out) — it would be far worse.
- **Even if the regex design were safe**, the Session-Buddy implementation is missing 7 of 9 industry-standard safeguards (agent-decides, hard cap, decay/pruning, retrieval side-car, per-project scoping, opt-out, etc.). Bringing it to Anthropic's bar is months of work whose value is unproven — Akosha already handles cross-repo pattern detection.

The right architectural lesson is not "fix the regex" but "the pattern itself is the wrong shape." A future re-implementation should be built fresh around **agent-decides extraction with bounded retrieval**, not around regex on `★ Insight` markers. The dead pipeline's existence is the cautionary tale.

### Possible follow-up features (NOT in this plan)

If the user later wants memory-capture functionality, these patterns would actually deliver value:

- **A `mark_insight` MCP tool** the user invokes from within a session — opt-in, not ambient. Replaces the framework-decides pattern with user-decides.
- **A "session-end review" UX pattern** — user reviews what the session produced and tags what's worth keeping. Mirrors Cline Memory Bank's design.
- **Embedding-cluster-based surfacing** — "you've been working on X a lot lately" based on session embedding clustering. Akosha already has the substrate.
- **A `weekly_session_digest` summarizer** — scheduled, uses existing conversation data, surfaces a summary the user can edit. Mirrors Mem0's "editorial decision about what to keep" framing.

These features would actually deliver value; the dead pipeline would not. Track as a separate plan if desired.

### Why REMOVE beats "wire it up"

| Option | Cost | Risk | Outcome |
|---|---|---|---|
| **REMOVE** (this plan) | ~6-10 hours, single PR | Low — zero production callers; try/except wrappers absorb the loss | -1,830 LOC maintenance debt, +1 latent bug eliminated, +4 dead schema columns dropped, +1 misleading skill retired, +1 orphaned ingester flagged |
| **Wire auto-capture** (previous plan) | ~16-20 hours | Medium — security surface (path gate, fcntl lock, redaction, MemoryGuard), 17 unit tests, e2e test, doctor extension, plugin distribution, MCP read tool to make it `wired` per feature-tracking | Built feature still has zero readers. The Phase 4 plan was never started, suggesting nobody wants the READ side either. |

The pipeline has been "ready to wire up" for 9 months without anyone doing it. The wiring work itself would not have made the feature adoptable — it would have shifted an archival store from "silently written" to "silently written with a hook trigger", still with no consumer. The right move is to delete the WRITE side and the orphan readers together in one PR.

## Approach: three commits on `main`, no PRs

Per `bodai-pre-1.0-merge-policy.md` (pre-1.0 = no PRs). Three commits:

1. `fix(memory): thread project through store_reflection wrapper and aggregate projects in stats`
2. `fix(memory): read created_at (and project) in quick_search result mapping`
3. `chore(insights): remove dead insights pipeline (1,830 LOC) + clean up doc drift`

Plus user-level edits: a new memory file `feedback-session-buddy-insights-pipeline-removed.md` documenting the REMOVE decision, dual-stored to Session-Buddy per `feedback-memories-must-be-dual-stored`.

## Work items

### Commit 1 — Bug 1 (project threaded + projects counted)

**Files:**
- `session_buddy/mcp/tools/memory/memory_tools.py` — wrapper signature, operation, impl, `_format_stats_old`
- `session_buddy/adapters/reflection_adapter_oneiric.py` — `get_stats()`
- `session_buddy/utils/tool_wrapper.py` — verify `format_reflection_result` accepts `project`; add if missing (default `None`)
- `tests/unit/test_memory_tools.py`, `tests/unit/test_reflection_adapter.py`

**Changes:**

1. `memory_tools.py:725` — add `project: str | None = None` to the `store_reflection` MCP signature; validate against `^[a-zA-Z0-9._-]{1,128}$` (defensive — MCP server has no auth, per the security review); pass through to `_store_reflection_impl(content, tags, project)`.
2. `memory_tools.py:118` (`_store_reflection_operation`) — add `project: str | None = None` param; call `db.store_reflection(content, tags=tags, project=project)`; include `project` in the returned dict.
3. `memory_tools.py:141` (`_store_reflection_impl`) — add `project: str | None = None` param; pass through to `_store_reflection_operation`.
4. `reflection_adapter_oneiric.py:1898` (`get_stats`) — add `SELECT COUNT(DISTINCT project) FROM reflections_v2 WHERE project IS NOT NULL`; include `total_projects` in the returned dict.
5. `memory_tools.py:579` (`_format_stats_old`) — change `stats.get('projects', 0)` → `stats.get('total_projects', 0)`. **WHY-COMMENT**: previous key was a stub that was never populated by `get_stats()` — explains why a rename is needed, not just a typo fix.

**Tests:**
- `tests/unit/test_memory_tools.py::TestStoreReflectionImpl::test_store_reflection_forwards_project` (new): mock `db.store_reflection`, assert called with `project="mahavishnu"`. Cover `project=None`, `project=""`, `project="mahavishnu/path/with/slashes"`, `project="unicode-名前"`. Also cover the rejection of an out-of-regex project string — defense against the unauthenticated MCP surface.
- `tests/unit/test_memory_tools.py::TestReflectionStatsImpl::test_reflection_stats_old_format_branch` (new): mock `get_stats` returning `{"total_conversations": 10, "total_reflections": 5, "total_projects": 3, ...}` with NO `conversations_count`; assert `"📁 Projects: 3"` renders. The existing `test_reflection_stats_success` exercises only the new-format branch.
- `tests/unit/test_reflection_adapter.py::test_get_stats_with_data` — extend with positive case (`store_reflection(project="foo")` + `store_reflection(project="bar")` → `total_projects == 2`), mixed case (one with project, one without → `total_projects == 1`), and the `WHERE project IS NOT NULL` regression guard (drop the WHERE clause → test catches it).
- Direct unit test of `_format_stats_old` with both the new key (`total_projects`) and the old key (`projects`) for backwards compat during transition.

**Backfill (deferred):** the 234 existing reflections have `project = NULL`. They will continue to show `📁 Projects: 0` until they get a `project` assigned. One-shot SQL `UPDATE reflections_v2 SET project = ... WHERE project IS NULL` script is a follow-up.

### Commit 2 — Bug 2 (Date: Unknown + project dropped from search results)

**Files:**
- `session_buddy/mcp/tools/memory/memory_tools.py` — `_quick_search_operation`
- `session_buddy/adapters/reflection_adapter_oneiric.py` — `_text_search_reflections` SELECT

**Changes:**

1. `memory_tools.py:224` — change `result.get('timestamp', 'Unknown')` → `ts = result.get("created_at") or "Unknown"` then `f"📅 Date: {ts}"`. **WHY-COMMENT**: adapter returns `created_at` (ISO string) not `timestamp`; the `or` chain handles `created_at=None` (NULL row) which would otherwise render as the literal string `"None"`.
2. `reflection_adapter_oneiric.py:2338` (`_text_search_reflections` SELECT) — extend the column list to include `project`. Update the dict comprehension at line 2349-2358 to surface `"project": row[idx]`. **WHY-COMMENT**: needed for `quick_search` to render the project line; the legacy `search_conversations` path already does this for v1.
3. Do NOT add `score` to the text-search return shape — lexical search has no score. Only the embedding path returns `similarity`.

**Tests:**
- `tests/unit/test_memory_tools.py::TestQuickSearchImpl::test_quick_search_with_results` — update mock to use the actual adapter return shape (`created_at` not `timestamp`); assert `"📅 Date: <real date>"` renders AND that `"Unknown"` does NOT appear. Also exercise the NULL-timestamp path (`result["created_at"] = None`) → assert `📅 Date: Unknown` renders correctly (not `"📅 Date: None"`).
- `tests/unit/test_reflection_adapter.py::test_text_search_reflections_returns_project_and_created_at` (NEW — dedicated test for the private method): pins the exact SELECT shape so future regressions in the private method are caught even if the public wrapper changes.
- Add `test_text_search_reflections_handles_null_timestamps` for the NULL row edge case.

### Commit 3 — Remove the dead insights pipeline

This is the new headline change. Single commit, deletes ~1,830 LOC of production code + ~1,000 LOC of tests + dead schema columns + doc drift.

#### 3.1 Production code to DELETE

| Path | LOC | What it is |
|---|---|---|
| `session_buddy/insights/` entire package | 1,225 | `extractor.py` (695) + `models.py` (301) + `console.py` (183) + `__init__.py` (46) |
| `session_buddy/core/session_manager.py:1525-1619` | ~95 | `_extract_and_store_insights(capture_point)` function |
| `session_buddy/core/session_manager.py:1352` | 1 | Call site in `checkpoint_session` |
| `session_buddy/core/session_manager.py:1850` | 1 | Call site in `end_session` |
| `session_buddy/adapters/reflection_adapter_oneiric.py:2608-3012` | ~405 | `db.store_insight`, `db.search_insights`, `_semantic_search_insights`, `_text_search_insights`, `_get_insight_statistics`, the `try/except duckdb.Error, OSError:` Python-2 comma-form bug at :2945 |
| `session_buddy/settings.py:357-395` | ~40 | `enable_insight_extraction`, `insight_extraction_confidence_threshold`, `insight_extraction_max_per_checkpoint`, `insight_auto_prune_enabled`, `insight_prune_age_days`, `insight_min_quality_score`, `insight_max_per_project` settings |
| `session_buddy/memory/schema_v2.py:108-111, 183-186` | ~10 | DDL comments referencing `store_insight` + the 4 dead schema columns (`insight_type`, `usage_count`, `last_used_at`, `confidence_score`) |
| `search/progressive_search.py:587-631` (`_search_insights` tier wrapper) | ~45 | Mislabeled — calls `db.search_reflections` not `db.search_insights`. Drop the wrapper or rename to `_search_reflections_high_confidence` and update callers |

Also delete the orphaned `session_buddy/ingesters/claude_code_transcript.py` (and its 2 tests) — same flavor of orphan, same verdict (no production caller; built + tested + never wired). Per the empirical reviewer: "the sibling orphan ingester … has 2 commits (initial + version bump), tests exist, but no production caller."

#### 3.2 Tests to DELETE

- `tests/unit/test_insights_extractor.py` (entire file)
- `tests/unit/test_insights_database.py` (entire file)
- `tests/unit/test_reflection_adapter.py` — drop the `test_has_store_insight_method`, `test_has_search_insights_method`, `test_store_insight_returns_id`, `test_search_insights_returns_results` cases; keep the rest
- `tests/unit/test_session_manager_high_impact.py` — drop the gate-behavior references; keep the rest
- `tests/unit/test_settings.py` — drop the `enable_insight_extraction` test; keep the rest
- `tests/unit/test_reflection_adapter_oneiric.py` — drop the adapter-level insight tests; keep the rest
- `tests/unit/test_progressive_search.py` — drop the `fake_db.search_insights` mocks; keep the rest
- `tests/unit/test_claude_code_transcript.py` (entire file, orphan)
- `tests/integration/test_claude_code_transcript.py` (entire file, orphan)
- `tests/conftest.py:1416` — drop `mock_settings_instance.enable_insight_extraction = True`
- `tests/e2e/test_e2e_insights_capture.py` (entire file, 225 lines)

#### 3.3 Slash commands — reword, do NOT delete

`commands/session-buddy-checkpoint.md` and `commands/session-buddy-end.md` reference "insights" in their descriptions. The underlying MCP tools (`mcp__session-buddy__checkpoint`, `mcp__session-buddy__end`) still work — they just won't synthesize insights anymore. Reword the descriptions to drop the "Generate insights" line and the user-facing copy will be accurate.

#### 3.4 Doc drift — DELETE / REWORD outside the repo

Per `docs-audit-mcp-uninstall-stale-refs` and `docs-audit-removed-but-referenced` patterns:

- `~/.claude/skills/capture-insights/SKILL.md` (294 lines, outside repo) — DELETE. Skill misdescribes `mcp__session-buddy__extract_and_store_memory_tool` as doing insight capture; that tool does LLM-based entity extraction, not `★ Insight` capture. Delete the entire skill directory; the user has no use for a skill that points at the wrong system.
- `~/.claude/skills/search-insights/SKILL.md` (419 lines, outside repo) — DELETE. Skill queries Akosha (`mcp__akosha__search_all_systems`), not Session-Buddy. It's a legitimate Akosha search skill misfiled under session-buddy semantics.
- `~/.claude/scripts/inject-insights.sh` (131 lines, outside repo) — DELETE. Built but never wired in `~/.claude/settings.json`. When invoked would call `db.search_conversations` (wrong system entirely).
- `docs/features/INSIGHTS_CAPTURE.md` (inside repo) — REWORD the "Planned, not started" Phase 4/5/6 sections to "Removed 2026-09-25 — see [commit](https://...)". Or just delete the doc; it documents a feature that no longer exists.

#### 3.5 Why a single commit, not three

The empirical reviewer recommended deletion as a single PR because every test deletion is bound to a production deletion (e.g., deleting `db.store_insight` requires deleting `test_insights_database.py` in the same commit — otherwise the test suite breaks on the next CI run). Splitting into "delete code", "delete tests", "delete docs" produces three intermediate states where the repo is broken. Single commit keeps `main` green at every intermediate state.

#### 3.6 Order of edits within the single commit

To keep the commit reviewable (~2,500 line diff), order the edits bottom-up:

1. Delete `tests/e2e/test_e2e_insights_capture.py` and the unit test files (no production impact).
2. Edit `session_buddy/settings.py` to drop the insight-related settings.
3. Edit `session_buddy/memory/schema_v2.py` to drop the dead DDL columns and comments.
4. Edit `session_buddy/adapters/reflection_adapter_oneiric.py` to delete `store_insight`, `search_insights`, `_semantic_search_insights`, `_text_search_insights`, `_get_insight_statistics` and fix the Python-2 comma-form `except` clause as a drive-by.
5. Edit `session_buddy/core/session_manager.py` to delete `_extract_and_store_insights` and the two call sites.
6. Delete the `session_buddy/insights/` package.
7. Delete `session_buddy/ingesters/claude_code_transcript.py` and its tests.
8. Edit `tests/conftest.py:1416` to drop the insight-extraction mock.
9. Edit `search/progressive_search.py` to remove or rename `_search_insights`.
10. Reword `commands/session-buddy-{checkpoint,end}.md`.
11. Reword `docs/features/INSIGHTS_CAPTURE.md` (or delete it).
12. Delete `~/.claude/skills/capture-insights/`, `~/.claude/skills/search-insights/`, `~/.claude/scripts/inject-insights.sh` (separate user-level edit, not committed to repo).

After every step, run `pytest tests/unit -x` to verify the repo still imports. The empirical reviewer warned that the test ordering matters — `test_insights_extractor.py` must be deleted before deleting `session_buddy/insights/` because `tests/conftest.py` may import from the package.

#### 3.7 Drive-by fix in commit 3

The Python-2 comma-form `except duckdb.Error, OSError:` at `reflection_adapter_oneiric.py:2945` (which catches only `duckdb.Error` and silently drops `OSError`) becomes natural to fix when deleting the `_text_search_insights` method that contains it. Per the project's memory `python-3.14-except-comma-form-acceptable.md`, the comma-form is valid syntax but emits `DeprecationWarning` and the user's CC memory rule says don't reflexively flag — but here we're already in the function deleting it, so the rename-to-parens fix is free.

#### 3.8 What is NOT in commit 3 (deferred)

- **Backfill of `project` for the 234 existing `project=NULL` reflections** — one-shot SQL script, follow-up (already deferred from Commit 1).
- **`/docs/feature-tracking/<slug>.md` entry** — since the feature is removed, no tracking entry needed.
- **`audit_orphans.py` post-removal audit** — run `python scripts/audit_orphans.py` after the commit to confirm no new orphans were introduced by the deletions.

## Critical files to modify

- `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/memory/memory_tools.py` (Commit 1 + 2)
- `/Users/les/Projects/session-buddy/session_buddy/adapters/reflection_adapter_oneiric.py` (Commit 1 + 2 + 3)
- `/Users/les/Projects/session-buddy/session_buddy/utils/tool_wrapper.py` (Commit 1)
- `/Users/les/Projects/session-buddy/session_buddy/core/session_manager.py` (Commit 3)
- `/Users/les/Projects/session-buddy/session_buddy/settings.py` (Commit 3)
- `/Users/les/Projects/session-buddy/session_buddy/memory/schema_v2.py` (Commit 3)
- `/Users/les/Projects/session-buddy/session_buddy/search/progressive_search.py` (Commit 3)
- `/Users/les/Projects/session-buddy/session_buddy/insights/` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/session_buddy/ingesters/claude_code_transcript.py` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_memory_tools.py` (Commit 1 + 2)
- `/Users/les/Projects/session-buddy/tests/unit/test_reflection_adapter.py` (Commit 1 + 2 + 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_insights_extractor.py` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_insights_database.py` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_session_manager_high_impact.py` (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_settings.py` (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_reflection_adapter_oneiric.py` (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_progressive_search.py` (Commit 3)
- `/Users/les/Projects/session-buddy/tests/unit/test_claude_code_transcript.py` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/tests/integration/test_claude_code_transcript.py` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/tests/conftest.py` (Commit 3)
- `/Users/les/Projects/session-buddy/tests/e2e/test_e2e_insights_capture.py` — DELETE (Commit 3)
- `/Users/les/Projects/session-buddy/commands/session-buddy-checkpoint.md` (Commit 3 reword)
- `/Users/les/Projects/session-buddy/commands/session-buddy-end.md` (Commit 3 reword)
- `/Users/les/Projects/session-buddy/docs/features/INSIGHTS_CAPTURE.md` (Commit 3 reword or delete)
- `/Users/les/.claude/skills/capture-insights/SKILL.md` — DELETE (Commit 3, user-level)
- `/Users/les/.claude/skills/search-insights/SKILL.md` — DELETE (Commit 3, user-level)
- `/Users/les/.claude/scripts/inject-insights.sh` — DELETE (Commit 3, user-level)
- `/Users/les/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-session-buddy-insights-pipeline-removed.md` — NEW (Commit 3)
- `/Users/les/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md` (add index entry)

## Memory-file update (per `feedback-memories-must-be-dual-stored` rule)

**CC memory body**: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-session-buddy-insights-pipeline-removed.md`

Content sketch (operator-facing):
- Decision: REMOVED the dead insights pipeline in commit `<hash>` on 2026-09-25.
- Why: zero production callers for `db.search_insights`, zero Akosha traces over 9+ months, no MCP tool reads insights, no auto-trigger wired the pipeline. The feature was a "ready to wire up" archival store that nobody wired up because nobody wanted the READ side either.
- What was deleted: `session_buddy/insights/` package (1,225 LOC), `_extract_and_store_insights` + call sites (97 LOC), `db.store_insight` / `db.search_insights` / `_semantic_search_insights` / `_text_search_insights` (405 LOC), 7 insight-related settings (40 LOC), 4 dead schema columns (`insight_type`, `usage_count`, `last_used_at`, `confidence_score`), mislabeled `_search_insights` tier wrapper (45 LOC). Plus orphaned `claude_code_transcript.py` ingester and its tests.
- Drive-by fix: `reflection_adapter_oneiric.py:2945` `except duckdb.Error, OSError:` Python-2 comma-form (catches only first type) → fixed during deletion.
- Companion skill retirement: `~/.claude/skills/capture-insights/` deleted (misdescribed `extract_and_store_memory_tool` as insight capture; that tool does entity extraction). `~/.claude/skills/search-insights/` deleted (queried Akosha, not Session-Buddy). `~/.claude/scripts/inject-insights.sh` deleted (built but never wired; called wrong system entirely).
- Re-introduction rule: if anyone wants insight capture back, build it fresh — don't try to revive the dead pipeline. A new feature needs: (a) a clear MCP read tool consumer, (b) the auto-trigger wired through settings.local.json, (c) the plugin distribution updated, (d) Akosha tracing hooks. All four were missing from the previous incarnation.
- See-also: Session-Buddy mirror tag `insights-pipeline-removed`.

**MEMORY.md index entry**: append to `### Active` section:
```markdown
- [feedback-session-buddy-insights-pipeline-removed.md](feedback-session-buddy-insights-pipeline-removed.md) — Session-Buddy's ★ Insight capture pipeline was removed 2026-09-25; zero callers, zero traces, 1,830 LOC of dead code deleted.
```

**Session-Buddy mirror**: `mcp__session-buddy__store_reflection(content=<body>, tags=["memory", "insights-pipeline-removed", "session-buddy"])`. The body must include a footer cross-reference back to the CC memory file. Mirror's tags include the CC filename as a tag for searchability.

## Verification (end-to-end)

After deploy:

```bash
# 1. Run the Session-Buddy test suite
cd /Users/les/Projects/session-buddy
uv run pytest tests/unit -m "not slow"   # 234 tests, ~30s
uv run pytest tests/e2e                  # 8 e2e tests, ~2 min
# Expected: zero failures. No "ImportError: No module named 'session_buddy.insights'".

# 2. Compile check (catches syntax regressions)
python -m py_compile session_buddy/mcp/tools/memory/memory_tools.py
python -m py_compile session_buddy/adapters/reflection_adapter_oneiric.py
python -m py_compile session_buddy/core/session_manager.py

# 3. Confirm dead symbols are gone
grep -rn "extract_insights_from_response\|store_insight\|search_insights\|_extract_and_store_insights" session_buddy/ tests/
# Expected: zero matches.

# 4. Confirm schema columns are gone
sqlite3 ~/.local/share/session-buddy/reflections.db ".schema reflections_v2"
# Expected: NO columns named insight_type, usage_count, last_used_at, confidence_score.

# 5. Restart the Session-Buddy MCP server
#    (server-optimized entry; restart per project-local SOP)

# 6. Bug-fix sanity (Commits 1 + 2)
mcp__session-buddy__store_reflection(
    content="sanity check", tags=["verification"], project="mahavishnu",
)
mcp__session-buddy__quick_search("sanity")
# Expected: real date in "📅 Date:" line, NOT "Unknown".
#           "📁 Project: mahavishnu" line should appear.

mcp__session-buddy__reflection_stats()
# Expected: "📁 Projects:" count ≥ 1.

# 7. Post-removal audit
python scripts/audit_orphans.py
# Expected: zero newly-orphaned symbols.

# 8. Doctor check
python -m session_buddy doctor
# Expected: HEALTHY (no `claude_hooks_config: HEALTHY` regression since we removed the wiring plan).
```

## Rollback signals

Watch for in the next session after deploy:

- `reflection_stats` still prints `📁 Projects: 0` → regression in commit 1. Revert Changes 1.4/1.5.
- `quick_search` still prints `📅 Date: Unknown` → regression in commit 2. Revert Change 2.1.
- `pytest tests/unit -m "not slow"` fails on `ImportError: No module named 'session_buddy.X'` → commit 3 deletion was incomplete. `grep -rn "<symbol>" session_buddy/ tests/` to find the straggler.
- `grep -rn "extract_insights_from_response\|store_insight\|search_insights" session_buddy/ tests/` returns matches → straggler reference in commit 3. Verify no production caller remains, then remove.
- A user complains "★ Insight blocks aren't being captured" → they were not being captured before either; nothing changed for them. Point them at the memory file documenting why.
- A user complains "my favorite capture-insights skill is gone" → that skill was pointing at the wrong tool (`extract_and_store_memory_tool`, which does entity extraction). They were never getting insight capture from it.
- `python scripts/audit_orphans.py` reports new orphans → likely a docstring comment or test fixture that referenced the deleted symbols. Run `grep` to find.

## Out of scope (flagged, deferred)

- **MCP `search_insights` tool** — never built (Phase 4 "Planned, not started"). N/A now that the pipeline is removed.
- **`plugins/session-buddy/hooks/PreCompact.md` and similar plugin-shipped hooks** — the canonical Claude-Code-plugin distribution surface. Architecture reviewer flagged this for the previous plan; now moot since we deleted the feature.
- **`ClaudeCodeTranscriptIngester`** (`session_buddy/ingesters/claude_code_transcript.py`) — INCLUDED in Commit 3 as a same-flavor orphan cleanup.
- **Backfill of `project` for the 234 existing `project=NULL` reflections** — one-shot SQL script, follow-up (already deferred from Commit 1).
- **The orphaned `search_tools.py` registration of `store_reflection` / `quick_search` / etc.** — not in the active path; can be deleted in a separate cleanup PR. Out of scope here.
- **A future re-implementation of insight capture** — if anyone wants it, build fresh with all four pieces (MCP read, auto-trigger, plugin distribution, Akosha tracing) wired from day one. The dead pipeline is the cautionary tale.

## Process-discipline notes

The plan satisfies the wire-up contract:

- ✅ Triggered from: explicit user request + 2/3 reviewer agreement
- ✅ Returns to / updates: removes orphaned WRITE half of round-trip + fixes two display bugs
- ✅ Demonstrable by: the verification section end-to-end (steps 1-8)
- ✅ Rollback signal: per-commit concrete rollback section
- ✅ Observability added: zero (removed dead code, no new observability needed)
- ✅ Feature tracking: implicit — feature state goes from `built` (wrong, never adopted) to `removed`
- ✅ `audit_orphans.py`: explicitly called in verification step 7
- ✅ Pre-merge gate: `crackerjack run` before each commit (per project convention).
