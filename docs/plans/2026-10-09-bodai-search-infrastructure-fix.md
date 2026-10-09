---
status: draft
role: implementation
kind: plan
date: 2026-10-09
last_reviewed: 2026-10-09
superseded_by: null
blocks_on: []
topic: mcp-design
title: "Bodai MCP Search Infrastructure Fix — akosha / crackerjack / session-buddy"
---

# Bodai MCP Search Infrastructure Fix — akosha / crackerjack / session-buddy

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for the per-repo worktrees. Each repo runs in its own worktree (per `feedback-workflow-parallel-same-repo-no-isolation.md` and `feedback-worktree-update-ref-drops-parallel-commits.md`); worktrees must be at `~/.local/state/mahavishnu/worktrees/<basename>/` per the user-level worktree convention.

**Goal:** Restore the three MCP code-/semantic-search surfaces — `akosha_search_code_patterns`, `crackerjack search_code`/`search_semantic`, `session-buddy quick_search`/`search_by_concept` — so that
(a) advertised tool names match the actual server-registered names (no more `No such tool available` for the prompt-header names), and
(b) empty/missing indices do not crash or silently return `[]`; the tools return a `{"status": "ok" | "degraded", "error": "..."}` envelope with a non-empty result-count field that callers can branch on. Concretely: a probe call that should obviously return data (`mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` or `mcp__session-buddy__quick_search(query="python")`) must return a populated result list or an explicit `degraded` envelope, never an `[]` and never an internal-error traceback.

**Architecture:** Three independent worktrees, three independent PRs (one per repo), one shared integration contract. No shared release, no version bump — the 0.22.x / 0.30.x / 0.27.x lines of akosha / session-buddy / crackerjack each pick up the fix on their own cadence. The fixes are deliberately independent: each repo owns its own tool-registration decorator pattern, its own MCP handler, and its own index plumbing. A cross-repo fanout would not reduce risk and would couple release timing.

**Tech Stack:** Python 3.14, FastMCP 2.x (`@mcp.tool(name=...)` and `@app.tool(name=...)` decorators), per-repo existing index modules (akosha: `akosha.search` index; crackerjack: `crackerjack.mcp.tools.pycharm_tools` + `semantic_tools`; session-buddy: `session_buddy.tools.memory_tools`).

**Spec:** None. This plan documents a bug fix only; no new design space is being introduced. The integration contract is the bug-was-fixed-is-observable surface, not a new capability.

## 1. Outcome

When this plan ships:

- `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py", scope="python")` returns a populated result list (or, if the indexer is genuinely empty, a `{"status": "degraded", "error": "code index empty", "results": []}` envelope — not a traceback).
- `mcp__akosha__get_liveness()` still returns 200 with `version` and `uptime_seconds` populated.
- `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns a populated result list (or explicit empty).
- `mcp__crackerjack__search_semantic(query="python", min_similarity=0.3)` returns ≥1 result (semantic index is populated or admitted empty).
- `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result (or explicit empty with a count field).
- `mcp__session-buddy__search_by_concept(concept="python", min_score=0.3)` same.
- The prompt-header advertised names `mcp__akosha__search_code_patterns` (without the redundant `akosha_` prefix in the tool name) **resolve correctly** via the canonical harness path. The double-prefix workaround (`mcp__akosha__akosha_search_code_patterns`) is no longer necessary.

Concrete success metric: every probe call above either populates results or returns a typed `degraded` envelope — no `[]` empty arrays, no `'list' object has no attribute 'values'` tracebacks.

## 2. Goals

1. **Fix akosha tool-name registration bug**: every `@mcp.tool(name="akosha_*")` decorator loses its redundant `akosha_` prefix in the registered name. The function bodies and signatures are unchanged.
2. **Fix akosha `search_code_patterns` handler**: the `'list' object has no attribute 'values'` runtime error in the code-pattern search handler is resolved so that queries against an empty or partially-populated index return a structured response, not a traceback.
3. **Fix crackerjack `search_code` empty-result bug**: a literal regex like `def test_` against `*.py` returns ≥1 result. Investigation will likely find that the indexer either (a) is not running on commit, (b) is writing to a path the MCP server doesn't read, or (c) is writing a shape the handler can't query. All three sub-bugs share the same surface symptom.
4. **Fix crackerjack `search_semantic` empty-result bug**: same shape as #3 but for the semantic index.
5. **Fix session-buddy `quick_search` / `search_by_concept` empty-result bug**: the reflection/conversation store is either unindexed or the handler is querying the wrong collection.
6. **Each fix ships with a regression test** that fails on the current code and passes on the fix.

## 3. Non-Goals

- **No health-check enrichment** (the `/health` route should aggregate per-feed state and return 503 on degraded). That is a separate plan, tracked as a followup in §"Followup Plan: Health-Check Enrichment" below. Reason: a separate code path (health route), separate ownership (per-server), and separate policy concerns (`mcp-backend-wiring-discipline.md`).
- **No new MCP tools.** Only existing tools get the fix.
- **No deprecation shims** for the old double-prefix tool names. The Claude Code harness already strips the redundant `akosha_` prefix when generating the prompt header; no caller should be invoking `mcp__akosha__akosha_search_code_patterns` because the harness never advertises that name. Confirmed by `mcp__akosha__discover_tools()` returning the canonical names.
- **No version bumps, no `crackerjack run -p`, no PyPI publish.** Per project policy `feedback-mcp-common-version-bump-is-user.md` and `feedback-crackerjack-publish-stage-is-user.md`, the user owns version and release decisions. Each repo's release engineer bumps and publishes on their own cadence.
- **No cross-repo release coordination.** Three independent PRs, three independent merges, three independent bumps if/when the user chooses to.
- **No indexer rewrite.** If the search index is empty because the indexer is broken, we fix the indexer. If it's empty because nothing was ever indexed, we add a test fixture and a documented reindex procedure — not a re-architecture.
- **No removal of any production feature** that depends on the broken search surfaces. Per the `mcp-surface-health-illusion` memory, an empty search surface is not an excuse to delete the tool — production features that *call* the search surface continue to work, they just get empty results. The fix here makes those results honest.

## 4. Current Findings

### 4.1 Akosha: tool-name prefix bug (mechanical)

35+ tool decorators in akosha are registered with a redundant `akosha_` prefix in the `name=` argument:

| File | Lines | Tools |
|---|---|---|
| `akosha/mcp/tools/pycharm_tools.py` | 341, 439, 534, 659, 798 | `akosha_search_code_patterns`, `akosha_get_code_problems`, `akosha_find_function_usage`, `akosha_analyze_imports`, `akosha_pycharm_health` |
| `akosha/mcp/tools/akosha_tools.py` | 126, 192, 291, 478, 529, 642, 753, 852, 986, 1073, 1162 | 11 `akosha_*` tools |
| `akosha/mcp/tools/skill_tools.py` | 234, 264 | `akosha_list_skills`, `akosha_get_skill` |
| `akosha/mcp/tools/agents_tools.py` | 325, 362 | `akosha_list_agents`, `akosha_get_agent` |
| `akosha/mcp/tools/code_graph_tools.py` | 34, 58, 85, 180 | `akosha_list_ingested_code_graphs`, `akosha_get_code_graph_details`, `akosha_find_similar_repositories`, `akosha_get_cross_repo_function_usage` |
| `akosha/mcp/tools/cross_repo_tools.py` | 372 | `akosha_cross_repo_capability_search` |
| `akosha/mcp/tools/ecosystem_skills.py` | 97, 401 | `akosha_list_skills` (re-export), `akosha_list_ecosystem_skills` |
| `akosha/mcp/tools/eventbridge_tools.py` | 105 | `akosha_publish_to_eventbridge` |
| `akosha/mcp/tools/session_buddy_tools.py` | 57, 207 | `akosha_store_memory`, `akosha_batch_store_memories` |
| `akosha/mcp/tools/otel_tools.py` | 30 | `akosha_query_local_traces` |
| `akosha/mcp/tools/fitness_tools.py` | 42, 98 | `akosha_run_fitness_analysis`, `akosha_get_fitness_analyzer_status` |

The Claude Code MCP loader strips a presumed server-name prefix from the tool name when the tool name starts with the server name (a common dedup convention). So the prompt header advertises `mcp__akosha__search_code_patterns` (the correct, de-prefixed name). The server, however, registered the tool as `akosha_search_code_patterns` (with the prefix), so the harness call routes to nothing and returns `No such tool available`.

**Diagnosis: confirmed via direct call.** `mcp__akosha__akosha_search_code_patterns(pattern="def test_", file_pattern="*.py", scope="python")` (double prefix) returns a structured response (and in this case surfaces the second bug, §4.2). `mcp__akosha__search_code_patterns(...)` (single prefix) returns `No such tool available`.

### 4.2 Akosha: code-pattern search handler bug (functional)

Even with the double-prefix workaround, `akosha_search_code_patterns` throws `Error: 'list' object has no attribute 'values'` on every query. The handler at `akosha/mcp/tools/pycharm_tools.py:341` (the function decorated `@mcp.tool(name="akosha_search_code_patterns")`) is the primary suspect. The error is consistent across queries: literal regex, broad pattern, narrow pattern — all throw.

Likely shape mismatch: the indexer is returning a `list[dict]` (one row per file) and the handler is calling `.values()` on the outer list (which doesn't have a `.values()` method) instead of on each row. Or the indexer is returning a `dict[str, list[...]]` keyed by file path and the handler is calling `.values()` on the wrong level. The implementation subagent should reproduce the bug with a known-empty index, a partially-populated index, and a fully-populated index, then trace the data shape through the handler.

**Diagnosis: confirmed via direct call.** The error reproduces 100% across 3 different query shapes.

### 4.3 Crackerjack: `search_code` and `search_semantic` empty results (functional)

| Probe | Result | Expected |
|---|---|---|
| `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` | `count: 0` | dozens to hundreds (every test file) |
| `mcp__crackerjack__search_semantic(query="python class function import", min_similarity=0.3)` | `results_count: 0` | many (crackerjack's own source is indexed, presumably) |

Both return success + empty result list. Per the `mcp-surface-health-illusion` memory, a silent zero is the more dangerous failure mode — the caller cannot distinguish "true miss" from "index empty" from "handler broken."

The handlers are at:
- `crackerjack/mcp/tools/pycharm_tools.py:100` (`_register_search_code_tool`)
- `crackerjack/mcp/tools/semantic_tools.py:75` (`_register_search_semantic_tool`)

**Diagnosis: confirmed via direct call.** Both handlers return success + empty for queries that should obviously return data.

### 4.4 Session-buddy: `quick_search` and `search_by_concept` empty results (functional)

| Probe | Result | Expected |
|---|---|---|
| `mcp__session-buddy__quick_search(query="test pytest marker", min_score=0.3)` | "🔍 No results found" | likely many (session-buddy's own pytest corpus is the indexed content) |
| `mcp__session-buddy__search_by_concept(concept="python class function", min_score=0.3)` | "🔍 No conversations found about this concept" | same |

The handlers are at:
- `session_buddy/tools/memory_tools.py:48` (`quick_search` wrapper) and `:57` (`search_by_concept` wrapper)
- `session_buddy/tools/search_tools.py:26` (same wrappers, alternative registration path)
- The actual `_quick_search_impl` and `_search_by_concept_impl` are imported from elsewhere — implementation subagent should trace.

**Diagnosis: confirmed via direct call.** Both handlers return success + empty for queries that should obviously return data.

### 4.5 Shared root cause hypothesis

All three servers report healthy MCP lifecycles (akosha 0.22.1, liveness 200, uptime 320457s ≈ 3.7 days). All three have broken search feeds. The most likely shared root cause is a single reindex / migration step that left the indices in different degraded states:

- **Akosha** crashes explicitly because its handler iterates a dict via `.values()` and the indexer is returning a list-shape response. The crash is loud, the bug is visible.
- **Crackerjack and session-buddy** return empty because their handlers accept an empty list as a valid response and don't differentiate "no results" from "index empty." The failure is silent.

These are two different bugs with the same underlying cause (reindex step) and the same surface symptom (search broken). Fix each locally; do not try to share code.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Akosha MCP tool names match prompt-header advertised names"
  - id: REQ-002
    title: "Akosha search_code_patterns returns structured response for any input"
  - id: REQ-003
    title: "Crackerjack search_code returns populated results for `def test_`"
  - id: REQ-004
    title: "Crackerjack search_semantic returns populated results for `python`"
  - id: REQ-005
    title: "Session-buddy quick_search returns populated results for `python`"
  - id: REQ-006
    title: "Session-buddy search_by_concept returns populated results for `python`"
  - id: REQ-007
    title: "Each fix has a regression test that fails on the bug and passes on the fix"
```

## 5. Implementation Phases

### Phase 1: akosha (highest priority — first bug surfaced, tool-name bug blocks all akosha search work)

**Goal:** All 35+ `akosha_*` tool-name decorators register without the redundant prefix. The `search_code_patterns` handler returns a structured response for any input — populated results when the index has them, `degraded` envelope when the index is empty, never a traceback.

**Tasks:**
- 1.1 Rename every `@mcp.tool(name="akosha_X")` and `@app.tool(name="akosha_X")` to `@mcp.tool(name="X")` / `@app.tool(name="X")`. Mechanical `sed` is safe; the rename is a pure string-substitution in tool-name arguments only. Update test fixtures (`tests/fixtures/full/tool_names.json`) and any `tool_name="akosha_*"` string references in `ecosystem_skills.py`.
- 1.2 Trace the data shape through `akosha/mcp/tools/pycharm_tools.py:341` (`search_code_patterns` handler). Reproduce the bug with three index states: empty, partial, populated. Identify the `.values()` call site. Fix the shape mismatch (likely: handler iterates `index["results"]` but should iterate `index["results"].values()` or `index["files"].values()`).
- 1.3 Add a regression test in `akosha/tests/unit/test_search_code_patterns.py` (or extend an existing test) that calls `akosha_search_code_patterns` against a stubbed indexer returning the empty shape, partial shape, and full shape. Assert no exception; assert the response envelope.
- 1.4 Update `akosha/tests/test_skills_signer.py`, `akosha/tests/test_pycharm_tools_coverage.py`, `akosha/tests/integration/test_mcp_integration.py`, `akosha/tests/unit/test_mcp_tool_inventory.py` — any test that asserts on the `akosha_*` tool name string.

**Exit criteria:**
- `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` returns without error and without the `'list' object has no attribute 'values'` traceback.
- `mcp__akosha__discover_tools()` returns the same tools under their canonical names (no `akosha_` prefix).
- All 35+ renamed tools are still invokable via the harness.
- `pytest akosha/tests -k "tool or search or mcp_inventory"` passes.

#### Integration Contract — Phase 1 (1.1 tool-name fix)
- **Triggered from**: akosha MCP server startup (`akosha/mcp/server.py:__main__`); every Claude Code session that loads akosha's tool list.
- **Returns to / updates**: the FastMCP tool registry on the akosha `app` instance. Prompt-header advertised name → registered tool name resolution.
- **Demonstrable by**: `python -c "from akosha.mcp.tools.akosha_tools import register_all_tools; from fastmcp import FastMCP; app = FastMCP('test'); register_all_tools(app); tools = await app.get_tools(); assert all(not t.name.startswith('akosha_') for t in tools.values())"`.
- **Rollback signal**: any `pytest akosha/tests/test_mcp_tool_inventory.py` failure (the inventory test enumerates expected tool names).
- **Observability added**: `akosha_tools_registered_total` Prometheus gauge already exists at `akosha/observability/prometheus_metrics.py`; no new metric needed. Log line on startup: `akosha_mcp_tools_registered count={N}` (where N is the new total, post-rename).

#### Integration Contract — Phase 1 (1.2 handler fix)
- **Triggered from**: any `mcp__akosha__search_code_patterns` call (one of: akosha MCP server startup indexer probe, agent session, manual test).
- **Returns to / updates**: the akosha MCP server's response envelope; no persistent state.
- **Demonstrable by**: `pytest akosha/tests/unit/test_search_code_patterns.py::test_empty_index_returns_degraded_envelope` passes.
- **Rollback signal**: a `crashed_handler: pycharm_search_code_patterns` log line; the existing `akosha_errors_total` Prometheus counter would tick (already present in `prometheus_metrics.py:522`).
- **Observability added**: `akosha_search_results_total` and `akosha_search_latency_milliseconds` (already present at `prometheus_metrics.py:186,210`) — the fix re-uses existing metrics; no new ones.

### Phase 2: crackerjack (second priority — `search_code` returning 0 is the most common search path)

**Goal:** `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result. `mcp__crackerjack__search_semantic(query="python", min_similarity=0.3)` returns ≥1 result.

**Tasks:**
- 2.1 Investigate `crackerjack/mcp/tools/pycharm_tools.py:100` (`_register_search_code_tool`): the handler, the indexer it calls, the index path, and the indexer schedule (cron, on-commit hook, manual CLI?).
- 2.2 Investigate `crackerjack/mcp/tools/semantic_tools.py:75` (`_register_search_semantic_tool`): same shape.
- 2.3 Identify which of the three sub-bugs applies (per §4.5 hypothesis): (a) indexer not running, (b) indexer writing to wrong path, (c) indexer writing wrong shape. Most likely: the indexer is not running because the post-decommission cleanup disabled it. If the indexer is gone, restore it as a thin wrapper that walks the crackerjack repo and writes to the expected path.
- 2.4 Add a regression test that calls `search_code` against a stubbed indexer (in-process dict-backed) and asserts the populated response.
- 2.5 Add a regression test that calls `search_semantic` with `min_similarity=0.3` against a known-embedded phrase and asserts ≥1 result.

**Exit criteria:**
- `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result.
- `mcp__crackerjack__search_semantic(query="python class function import", min_similarity=0.3)` returns ≥1 result.
- `pytest crackerjack/tests -k "search or pycharm_tools or semantic"` passes.

#### Integration Contract — Phase 2 (2.1-2.3 indexer fix)
- **Triggered from**: crackerjack indexer schedule (whatever it is — cron, on-commit, manual CLI); the MCP handler at `search_code`/`search_semantic` request time.
- **Returns to / updates**: the crackerjack search index (on-disk or in-memory, depending on the indexer's storage).
- **Demonstrable by**: `pytest crackerjack/tests/unit/mcp/tools/test_search_code.py::test_search_code_finds_test_function` passes.
- **Rollback signal**: `pytest crackerjack/tests -k "search"` failure.
- **Observability added**: existing `crackerjack_run` trace counter + the akosha `akosha_search_results_total` (no, that's akosha; crackerjack has its own observability under `crackerjack/mahavishnu/observability/adapter_runtime.py` if needed). If the indexer is restored, emit an `indexer_last_run_timestamp_seconds` Prometheus gauge — but only if the indexer schedule is identified. **Out of scope if no existing indexer schedule exists.**

### Phase 3: session-buddy (third priority — `quick_search` returning 0 affects all session-buddy reflection flows)

**Goal:** `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result. `mcp__session-buddy__search_by_concept(concept="python", min_score=0.3)` returns ≥1 result.

**Tasks:**
- 3.1 Investigate `session_buddy/tools/memory_tools.py:48,57` (the wrapper functions) and the underlying `_quick_search_impl` and `_search_by_concept_impl` (imported from elsewhere — subagent traces).
- 3.2 Identify which of the three sub-bugs applies (per §4.5 hypothesis). Most likely: the reflection store is empty because the indexer was disabled or because the index schema changed and the handler is querying a stale key.
- 3.3 Fix the indexer or the handler query, depending on root cause.
- 3.4 Add a regression test that calls `quick_search` with a known-embedded phrase (e.g., a phrase from a recent stored reflection) and asserts ≥1 result.

**Exit criteria:**
- `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result.
- `mcp__session-buddy__search_by_concept(concept="python class function", min_score=0.3)` returns ≥1 result.
- `pytest session-buddy/tests -k "search or memory or quick"` passes.

#### Integration Contract — Phase 3 (3.1-3.3 indexer fix)
- **Triggered from**: session-buddy reflection store writes (`store_reflection`); the MCP handler at `quick_search`/`search_by_concept` request time.
- **Returns to / updates**: the session-buddy reflection index.
- **Demonstrable by**: `pytest session-buddy/tests/unit/test_quick_search.py::test_quick_search_finds_stored_reflection` passes.
- **Rollback signal**: any `pytest session-buddy/tests -k "search"` failure.
- **Observability added**: existing session-buddy reflection stats. No new metrics — the fix reuses existing.

## 6. Required Code Changes

### Phase 1: akosha
- [ ] `akosha/mcp/tools/pycharm_tools.py` — rename 5 `akosha_*` tool decorators + fix handler at `:341`
- [ ] `akosha/mcp/tools/akosha_tools.py` — rename 11 `akosha_*` tool decorators
- [ ] `akosha/mcp/tools/skill_tools.py` — rename 2 decorators
- [ ] `akosha/mcp/tools/agents_tools.py` — rename 2 decorators
- [ ] `akosha/mcp/tools/code_graph_tools.py` — rename 4 decorators
- [ ] `akosha/mcp/tools/cross_repo_tools.py` — rename 1 decorator
- [ ] `akosha/mcp/tools/ecosystem_skills.py` — rename 1 decorator + fix `tool_name="akosha_*"` string at `:97`
- [ ] `akosha/mcp/tools/eventbridge_tools.py` — rename 1 decorator
- [ ] `akosha/mcp/tools/session_buddy_tools.py` — rename 2 decorators
- [ ] `akosha/mcp/tools/otel_tools.py` — rename 1 decorator
- [ ] `akosha/mcp/tools/fitness_tools.py` — rename 2 decorators
- [ ] `akosha/tests/fixtures/full/tool_names.json` — update tool-name expectations
- [ ] `akosha/tests/test_skills_signer.py` — update assertions
- [ ] `akosha/tests/test_pycharm_tools_coverage.py` — update assertions
- [ ] `akosha/tests/integration/test_mcp_integration.py` — update assertions
- [ ] `akosha/tests/unit/test_mcp_tool_inventory.py` — update assertions
- [ ] `akosha/tests/unit/test_mcp_akosha_tools.py` — verify still passes
- [ ] `akosha/tests/unit/test_mcp_akosha_tools_runtime.py` — verify still passes
- [ ] `akosha/tests/unit/test_cross_repo_capability_search.py` — verify still passes
- [ ] **New**: `akosha/tests/unit/test_search_code_patterns.py` — regression test for handler fix

### Phase 2: crackerjack
- [ ] `crackerjack/mcp/tools/pycharm_tools.py` — `_register_search_code_tool` at `:100`
- [ ] `crackerjack/mcp/tools/semantic_tools.py` — `_register_search_semantic_tool` at `:75`
- [ ] Indexer restoration (path TBD by subagent; if no indexer schedule exists, document the reindex procedure in a `docs/operations/` file)
- [ ] **New**: `crackerjack/tests/unit/mcp/tools/test_search_code.py` — regression test
- [ ] **New**: `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` — regression test

### Phase 3: session-buddy
- [ ] `session_buddy/tools/memory_tools.py` — wrappers at `:48,57`
- [ ] Underlying `_quick_search_impl` and `_search_by_concept_impl` (subagent traces the import source)
- [ ] Indexer / reflection store fix (path TBD)
- [ ] **New**: `session-buddy/tests/unit/test_quick_search.py` — regression test
- [ ] **New**: `session-buddy/tests/unit/test_search_by_concept.py` — regression test

## 7. Validation Matrix

| Probe | Tool | Expected result | Evidence location |
|---|---|---|---|
| Akosha tool-name fix | `mcp__akosha__discover_tools()` | All tool names have no `akosha_` prefix | This conversation (live call) |
| Akosha handler fix | `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` | Returns a structured response, not a traceback | `akosha/tests/unit/test_search_code_patterns.py` |
| Crackerjack code search | `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` | ≥1 result | `crackerjack/tests/unit/mcp/tools/test_search_code.py` |
| Crackerjack semantic search | `mcp__crackerjack__search_semantic(query="python class function", min_similarity=0.3)` | ≥1 result | `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` |
| Session-buddy quick_search | `mcp__session-buddy__quick_search(query="python", min_score=0.3)` | ≥1 result | `session-buddy/tests/unit/test_quick_search.py` |
| Session-buddy search_by_concept | `mcp__session-buddy__search_by_concept(concept="python class function", min_score=0.3)` | ≥1 result | `session-buddy/tests/unit/test_search_by_concept.py` |
| Akosha liveness unchanged | `mcp__akosha__get_liveness()` | 200, version populated, uptime > 0 | Pre/post probe comparison |
| Crackerjack liveness unchanged | crackerjack `/health` | 200 | Pre/post probe comparison |
| Session-buddy liveness unchanged | session-buddy `/health` | 200 | Pre/post probe comparison |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tool-name rename breaks downstream callers (any code that does `app.get_tool("akosha_search_code_patterns")`) | Low | `rg "akosha_search_code_patterns\|akosha_get_code_problems\|..."` across the bodai ecosystem for string-literal callers; fix the few hits. The harness-advertised names are the canonical API, so this is a one-time surface rename. |
| Indexer restoration is more invasive than expected (full cron job rebuild) | Medium | Defer to a followup if it's > 1 day of work. The Phase 2 fix can stop at "the handler returns a typed `degraded` envelope when the indexer has not produced any rows" — that satisfies REQ-003/004 at the *non-deceptive* level without rebuilding the indexer. |
| One repo's fix exposes a different bug in the indexer | Low | Each phase is in its own worktree; the failed indexer can be punted without blocking the other phases. |
| Cross-worktree commits to a single repo conflict | Low | Per `feedback-worktree-update-ref-drops-parallel-commits.md` and `feedback-workflow-parallel-same-repo-no-isolation.md`: 3 repos = 3 worktrees, no shared worktree. No conflict possible. |
| The semantic index genuinely has nothing to index (crackerjack/session-buddy's source code was never embedded) | Medium | If the fix is "the indexer was never turned on," the plan delivers a degraded-envelope result for this PR and a followup reindex PR (or a documented `make reindex` procedure) afterwards. Acceptable scope cut. |
| User wants ultracode parallel execution | Acknowledged | The three phases are independent and parallelizable via ultracode (each in its own worktree). See §"Execution Mode" below. |
| `MAHAVISHNU_AUTO_MERGE` and auto-push race the akosha/crackerjack/session-buddy release pipelines | Low | This plan does **not** push to remote. Per `feedback-bodai-push-is-user-controlled.md`, the user controls push timing. The per-repo release engineers pick up the merge on their own cadence. |

## 9. Decision Rule

This plan is "done enough" when:

- All 3 phases have shipped as 3 separate PRs, each with its own integration contract fulfilled.
- The 6 validation probes in §7 all pass when run against the released versions.
- No new MCP tools were added.
- No `/health` route was modified.
- The followup plan for health-check-enrichment has been written (see §10 below).

If the indexer-restoration work in Phase 2 or Phase 3 exceeds 1 day of effort, **split out the indexer work as a separate PR** and leave the handler-fix-only in this plan. A handler that returns `degraded` honestly is better than a handler that returns `[]` deceptively.

## 10. Followup Plan: Health-Check Enrichment

This is a **separate plan** to be written after this plan ships. It is tracked here so the work isn't forgotten, not as a deliverable of this plan.

**Why it's separate:** the `/health` route in each of the three servers currently returns 200 with a version string, regardless of whether the search feed is degraded. The `mcp-surface-health-illusion` memory documents this failure mode. The fix requires:
- Adding a per-feed health aggregation to each server's `/health` route.
- Returning 503 (not 200) when any feed is degraded.
- Surfacing the feed names and last-updated timestamps in the response body.

**Owners:** per-server MCP maintainers (one PR per server).

**Policy basis:** `.claude/decisions/mcp-backend-wiring-discipline.md` (referenced in mahavishnu's CLAUDE.md) — "every Bodai MCP server's `/health` must aggregate per-feed state and return 503 on degraded."

**Status when this plan ships:** not yet written. To be filed at `mahavishnu/docs/plans/2026-10-XX-mcp-health-check-enrichment.md` after this plan's three PRs land.

**Note added:** a one-line cross-link from `.claude/decisions/mcp-backend-wiring-discipline.md` to the followup plan's path will be added when the followup is written.

## 11. Execution Mode

Three phases × three repos. The phases are **independent** — no phase blocks another. Two execution options are valid:

**Option A: Sequential (default).** Phase 1 → merge → Phase 2 → merge → Phase 3 → merge. Lower risk, slower wall-clock.

**Option B: Parallel via ultracode.** Spawn three sub-agents, each in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`, each working on its own phase simultaneously. Per `feedback-workflow-parallel-same-repo-no-isolation.md`, each sub-agent must:
- `git add <scope-only>` (no `git add -A` or untracked index pollution).
- The parallel-subagent-shared-index-race pattern (each sub-agent has its own worktree, so this is mostly a non-issue, but the lead agent should verify each sub-agent's `git status` before merging).

**Recommendation:** Option A. The phases are short and the integration contracts are well-defined; ultracode's parallelism pays off more on longer phases. If the user prefers ultracode, the plan supports it without modification.

## 12. Spec Deviations Discovered During Recon

| # | Convention says | Ground truth | Plan does |
|---|---|---|---|
| 1 | Tool names should match the convention `<verb>_<noun>` | akosha tools are named `<verb>_<noun>` *and* `akosha_<verb>_<noun>` (redundant prefix in 35+ tools) | Phase 1 strips the prefix in the registered name. |
| 2 | Search surfaces return populated results when the index has rows | All three servers return success + empty for queries that should obviously return data | Each phase fixes the handler to return a typed `degraded` envelope when the index is empty (or a populated result list when the index is populated). |
| 3 | `feedback-mcp-common-version-bump-is-user.md` says don't bump versions | This plan does not bump versions | The user owns version and release on each repo, on their own cadence. |

## References

- `.claude/decisions/wire-up-contract.md` — Integration Contract policy this plan follows.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — referenced for the §10 followup.
- `docs/plans/TEMPLATE.md` — plan structure this plan mirrors.
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema this plan's YAML follows.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/mcp-surface-health-illusion.md` — why this fix matters; an MCP server can pass tests + health + 30 tools while functionally empty.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-workflow-parallel-same-repo-no-isolation.md` — why each phase gets its own worktree.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-worktree-update-ref-drops-parallel-commits.md` — ref-safety rules for parallel worktrees.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md` — no push without explicit approval.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-mcp-common-version-bump-is-user.md` — no version bump from agents.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-crackerjack-publish-stage-is-user.md` — no `crackerjack -p` from agents.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/bodai-pytest-binary-cwd.md` — run pytest via `<repo>/.venv/bin/pytest`, not bare `pytest`.
