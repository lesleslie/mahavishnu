---
status: draft
role: implementation
kind: plan
date: 2026-10-09
last_reviewed: 2026-10-09
superseded_by: null
blocks_on: []
topic: mcp-search
---

# Bodai MCP Search Infrastructure Fix — akosha / crackerjack / session-buddy

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for the per-repo worktrees. Each repo runs in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/` (where `<repo>` is `akosha`, `crackerjack`, or `session-buddy` per the user-level convention in `~/.claude/CLAUDE.md`). Per `feedback-workflow-parallel-same-repo-no-isolation.md` and `feedback-worktree-update-ref-drops-parallel-commits.md`, worktrees are independent; per-rebase → SHA-reverify → squash-merge flow runs per repo. The merge workflow's orchestrator (`mahavishnu.core.merge_to_main`) is **only on the PYTHONPATH of the mahavishnu repo's venv** — invoke from there (`python -m mahavishnu.core.merge_to_main --branch <branch>`), or route the merge through `mcp__mahavishnu__pool_route_execute` so the orchestrator process owns the import.

**Goal:** Restore the three MCP code-/semantic-search surfaces — `akosha_search_code_patterns`, `crackerjack search_code`/`search_semantic`, `session-buddy quick_search`/`search_by_concept` — so that
(a) advertised tool names match the actual server-registered names (no more `No such tool available` for the prompt-header names), and
(b) empty/missing indices do not crash or silently return `[]`; the tools return a structured `{"status": "ok" | "degraded", "results": [...]}` envelope that callers can branch on. Concretely: a probe call that should obviously return data (`mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` or `mcp__session-buddy__quick_search(query="python")`) must return a populated result list or an explicit `degraded` envelope, never an `[]` and never an internal-error traceback.

**Architecture:** Three independent merge cycles (one per repo) — the project uses ephemeral branches + squash-merge to local `main` + auto-push (per `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4), no GitHub PR step. Each phase ships in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`. Per `feedback-bodai-push-is-user-controlled.md`, `git push origin main` is governed by `.claude/decisions/2026-10-03-mainautopush.md` — that decision is **mahavishnu-scoped**; the three target repos retain user-controlled push until they adopt the same decision. No shared release, no version bump — the 0.22.x / 0.30.x / 0.27.x lines of akosha / session-buddy / crackerjack each pick up the fix on their own cadence.

**Tech Stack:** Python 3.14, FastMCP 2.x (`@mcp.tool(name=...)` and `@app.tool(name=...)` decorators), per-repo existing index modules (akosha: `akosha.search` index; crackerjack: `crackerjack.mcp.tools.pycharm_tools` + `semantic_tools`; session-buddy: `session_buddy.tools.memory_tools`).

**Spec:** None. This plan documents a bug fix only; no new design space is being introduced.

## 1. Outcome

When this plan ships:

- `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py", scope="python")` returns a structured response (populated results when the index has them, `degraded` envelope when the index is empty), never a traceback.
- `mcp__akosha__get_liveness()` still returns 200 with `version` and `uptime_seconds` populated.
- `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result.
- `mcp__crackerjack__search_semantic(query="python", min_similarity=0.3)` returns ≥1 result.
- `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result.
- `mcp__session-buddy__search_by_concept(concept="python", min_score=0.3)` returns ≥1 result.
- The Claude Code TUI `/akosha` picker still returns the akosha tool list after the prefix-rename (REQ-008).
- The prompt-header advertised names `mcp__akosha__search_code_patterns` (without the redundant `akosha_` prefix in the tool name) **resolve correctly** via the canonical harness path. The double-prefix workaround (`mcp__akosha__akosha_search_code_patterns`) is no longer necessary.

Concrete success metric: every probe call above either populates results or returns a typed `degraded` envelope — no `[]` empty arrays, no `'list' object has no attribute 'values'` tracebacks, and the `/akosha` picker still works.

## 2. Goals

1. **Fix akosha tool-name registration bug**: every `@mcp.tool(name="akosha_*")` decorator loses its redundant `akosha_` prefix in the registered name. Source-doc strings and federation call sites that carry the prefix are updated in the same PR. (REQ-001)
2. **Fix akosha picker-filter side-effect**: the Claude Code TUI `/akosha` picker implementation is updated to filter by server name (not prefix-match on registered name) so the prefix-rename doesn't break the picker. (REQ-008)
3. **Fix akosha `search_code_patterns` handler**: the `'list' object has no attribute 'values'` runtime error in the code-pattern search handler is resolved at all 5 shape sites (not just one). The handler returns a structured response (populated or `degraded`), never a traceback. (REQ-002, REQ-009)
4. **Fix crackerjack `search_code` empty-result bug**: a literal regex like `def test_` against `*.py` returns ≥1 result. (REQ-003)
5. **Fix crackerjack `search_semantic` empty-result bug**: a generic query like `python class function` at `min_similarity=0.3` returns ≥1 result. (REQ-004)
6. **Fix session-buddy `quick_search` / `search_by_concept` empty-result bug**: a generic query like `python` at `min_score=0.3` returns ≥1 result. (REQ-005, REQ-006)
7. **Wire the auto-merge SessionEnd hook** into the 3 target repos' `.claude/settings.json` so merge cycles can complete from sessions in those worktrees. (REQ-010)
8. **Each fix ships with a regression test** that fails on the current code, passes on the fix, and asserts on the wire-shape envelope (not the in-process return value). (REQ-007, REQ-012)
9. **No `.mcp.json` in any of the 4 repos references the old `akosha_*` tool names** after the rename. (REQ-011)
10. **No .mcp.json references the redundant `akosha_` prefix or any tool name from the surfaces this plan touches.**

## 3. Non-Goals

- **No health-check enrichment** (the `/health` route should aggregate per-feed state and return 503 on degraded). That is a separate plan, tracked as a followup in §"Followup Plan" below. Reason: a separate code path (health route), separate ownership (per-server), and separate policy concerns (`mcp-backend-wiring-discipline.md`).
- **No new MCP tools.** Only existing tools get the fix.
- **No deprecation shims for the old double-prefix tool names.** The Claude Code harness already strips the redundant `akosha_` prefix when generating the prompt header; no caller should be invoking `mcp__akosha__akosha_search_code_patterns` because the harness never advertises that name. Confirmed by `mcp__akosha__discover_tools()` returning the canonical names.
- **No version bumps, no `crackerjack run -p`, no PyPI publish.** Per `feedback-mcp-common-version-bump-is-user.md` and `feedback-crackerjack-publish-stage-is-user.md`, **the user** owns version and release decisions. The user controls `git push origin main` for all 5 Bodai repos per `feedback-bodai-push-is-user-controlled.md` (mahavishnu has an auto-push exception per `2026-10-03-mainautopush.md`; the 3 target repos do not).
- **No cross-repo release coordination.** Three independent merge cycles, three independent merges, three independent bumps if/when the user chooses to.
- **No indexer rewrite.** If the search index is empty because the indexer is broken, we fix the indexer. If it's empty because nothing was ever indexed, we add a test fixture and a documented reindex procedure — not a re-architecture.
- **No removal of any production feature** that depends on the broken search surfaces. Per the `mcp-surface-health-illusion` memory, an empty search surface is not an excuse to delete the tool — production features that *call* the search surface continue to work, they just get empty results. The fix here makes those results honest.

## 4. Current Findings

### 4.1 Akosha: tool-name prefix bug (mechanical)

32 `@mcp.tool(name="akosha_*")` decorator arguments across 11 files (verified count by `grep 'name="akosha_"' akosha/mcp/tools/*.py`):

| File | Decorator-count |
|---|---|
| `akosha/mcp/tools/akosha_tools.py` | 11 |
| `akosha/mcp/tools/pycharm_tools.py` | 5 |
| `akosha/mcp/tools/code_graph_tools.py` | 4 |
| `akosha/mcp/tools/skill_tools.py` | 2 |
| `akosha/mcp/tools/agents_tools.py` | 2 |
| `akosha/mcp/tools/fitness_tools.py` | 2 |
| `akosha/mcp/tools/session_buddy_tools.py` | 2 |
| `akosha/mcp/tools/cross_repo_tools.py` | 1 |
| `akosha/mcp/tools/eventbridge_tools.py` | 1 |
| `akosha/mcp/tools/otel_tools.py` | 1 |
| `akosha/mcp/tools/ecosystem_skills.py` | 1 |

The Claude Code MCP loader builds tool names as `mcp__{server-instance-name}__{tool-name}`. With `akosha` as the server name and the registered tool name `search_code_patterns` (no prefix), the harness header is `mcp__akosha__search_code_patterns` — exactly the prompt-header shape that's currently failing to resolve. The redundant `akosha_` prefix in the registered name was the bug, not a FastMCP convention. (Confirmed by akosha-specialist.)

**Downstream side-effect: Claude Code TUI picker filter.** Per the 29-day-old memory `bodai-tool-naming-gap-2026-09-09.md`, the TUI `/akosha` picker filter does prefix-match on the registered name. Stripping the prefix requires the picker implementation to switch from prefix-match to **server-name match**. This is a same-PR change in the Claude Code TUI consumer (per-memory path: `~/.claude/` or whatever consumer implements the picker), not a change to the akosha server itself. **Both findings in the multi-agent review are correct: the prefix-rename is right, AND the picker-filter implementation must be updated in the same PR.**

Additional source-doc and federation string sites that carry the prefix and must be updated in the same PR (not just decorator arguments):
- `akosha/akosha/mcp/tools/profiles.py:98-117` — string list mapping register_fn → tool names
- `akosha/akosha/mcp/client.py:80` — `"akosha_query_local_traces"` string
- `akosha/akosha/mcp/tools/agents_tools.py:174` — `"mcp__akosha__akosha_run_fitness_analysis"` in a list
- `akosha/akosha/mcp/tools/skill_tools.py:120-125` — SkillMetadata `tool_refs`
- `akosha/akosha/mcp/tools/ecosystem_skills.py:97` — `tool_name="akosha_list_skills"` inside `_FederationServer` config (cross-MCP fan-out trigger; changing this to `list_skills` keeps `mcp__akosha__list_ecosystem_skills` federation working. **Verify that the same file's lines 103/109/115 entries for `mahavishnu_list_skills` / `session_buddy_list_skills` / `crackerjack_list_skills` are NOT changed — only the akosha entry**.)
- `akosha/akosha/mcp/skills_catalog/fitness-analyzer.md` (frontmatter `allowed-tools`)
- `akosha/akosha/mcp/skills_catalog/search-insights.md:47-48` (skill catalog prose)
- `akosha/akosha/mcp/tools/agents/pattern-agent.md` (3 references in agent body)
- `akosha/akosha/mcp/tools/akosha_tools.py` module docstring + class docstrings

A pure `sed`-of-decorators pass will leak these. The sweep must be a target-file walk that classifies each hit as one of: (a) decorator argument — strip prefix, (b) registry-construction string — strip prefix, (c) federation call parameter — strip prefix (per-server), (d) tool-allowlist string in `profiles.py` — strip prefix, (e) skill-catalog frontmatter/prose — strip prefix, (f) agent body — strip prefix. Patterns (b)/(d)/(e)/(f) are NOT decorator arguments and a regex match on `name="akosha_` will miss them.

### 4.2 Akosha: code-pattern search handler bug (functional, multi-site)

The `search_code_patterns` handler at `akosha/mcp/tools/pycharm_tools.py:346-430` throws `Error: 'list' object has no attribute 'values'` on every query. The actual `.values()` call that raises is at **`akosha/mcp/tools/pycharm_tools.py:391`** (`for node in graph["graph_data"].get("nodes", {}).values():`), not `:341` (which is the `name="akosha_search_code_patterns"` argument inside a `ToolMetadata(...)` decorator). The default-`{}` makes `.values()` safe when `nodes` is absent, unsafe when `nodes` is present-as-a-list (the actual session-buddy indexer shape, per the akosha agent's recon).

The same bug pattern recurs at 4 more sites in the same file plus 1 in `code_graph_tools.py`:
- `akosha/mcp/tools/pycharm_tools.py:391` (primary)
- `akosha/mcp/tools/pycharm_tools.py:489`
- `akosha/mcp/tools/pycharm_tools.py:586`
- `akosha/mcp/tools/pycharm_tools.py:713`
- `akosha/mcp/tools/pycharm_tools.py:762`
- `akosha/mcp/tools/code_graph_tools.py:205`

The fix is not a single shape handler — it's a per-site guard that handles three indexer shapes: dict (preferred), list (legacy), missing (empty).

### 4.3 Crackerjack: `search_code` and `search_semantic` empty results (functional)

| Probe | Result | Expected |
|---|---|---|
| `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` | `count: 0` | dozens to hundreds |
| `mcp__crackerjack__search_semantic(query="python class function import", min_similarity=0.3)` | `results_count: 0` | many |

Both return success + empty result list. Per the `mcp-surface-health-illusion` memory, a silent zero is the more dangerous failure mode — the caller cannot distinguish "true miss" from "index empty" from "handler broken."

Handlers at:
- `crackerjack/mcp/tools/pycharm_tools.py:100` (`_register_search_code_tool` → wrapped function at `:103`)
- `crackerjack/mcp/tools/semantic_tools.py:75` (`_register_search_semantic_tool` → wrapped function at `:77`)

### 4.4 Session-buddy: `quick_search` and `search_by_concept` empty results (functional)

| Probe | Result | Expected |
|---|---|---|
| `mcp__session-buddy__quick_search(query="test pytest marker", min_score=0.3)` | "🔍 No results found" | likely many |
| `mcp__session-buddy__search_by_concept(concept="python class function", min_score=0.3)` | "🔍 No conversations found about this concept" | likely many |

Handlers at:
- `session_buddy/tools/memory_tools.py:48` (`quick_search` wrapper) and `:57` (`search_by_concept` wrapper)
- `session_buddy/tools/search_tools.py:26,36` (alternative registration path)

### 4.5 Requirements

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
  - id: REQ-008
    title: "Claude Code TUI `/akosha` picker uses server-name match (not prefix-match on registered name) and returns the akosha tool list after the prefix-rename"
  - id: REQ-009
    title: "Akosha handler `.values()` shape guard covers all 6 sites (pycharm_tools.py:391,489,586,713,762 + code_graph_tools.py:205)"
  - id: REQ-010
    title: "agent-merge-on-end SessionEnd hook is wired into akosha, crackerjack, and session-buddy `.claude/settings.json` so merge cycles can complete from those worktrees"
  - id: REQ-011
    title: "No .mcp.json in any of the 4 Bodai repos references the pre-rename `akosha_*` tool names"
  - id: REQ-012
    title: "Regression tests assert on the wire-shape envelope (`result.content[0].text` parsed via `_extract_tool_payload`), not the in-process return value"
  - id: REQ-013
    title: "Per-repo push governance cross-link in each target repo's CLAUDE.md (or replicated `.claude/decisions/2026-10-03-mainautopush.md` analogue)"
```

### 4.6 Recon observations

(Spec deviations discovered during recon. Folded from a separate section per the multi-agent review; these overlap with §3 Non-Goals and §4 Current Findings so they live here as a one-pass reference.)

| # | Convention says | Ground truth | Plan does |
|---|---|---|---|
| 1 | Tool names follow the convention `<verb>_<noun>` | Akosha tools are named `akosha_<verb>_<noun>` (redundant prefix in 32 decorators + 8 source-doc/federation/allowlist strings) | Phase 1 strips the prefix in the registered name and in the source-doc/federation/allowlist sites |
| 2 | Search surfaces return populated results when the index has rows | All three servers return success + empty for queries that should obviously return data | Each phase fixes the handler to return a typed `degraded` envelope when the index is empty |
| 3 | `feedback-mcp-common-version-bump-is-user.md` says don't bump versions | This plan does not bump versions | The user owns version and release on each repo, on their own cadence |
| 4 | Merge workflow lives in `mahavishnu`; invocation from non-mahavishnu worktrees is not in scope of the original spec (`docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`) | Phase 1/2/3 worktrees are in akosha/crackerjack/session-buddy | Invoke the orchestrator from the mahavishnu venv, or route the merge through `mcp__mahavishnu__pool_route_execute` |

### 4.7 Shared root cause hypothesis (one possible cause, not the only one)

One possible shared cause is a single reindex / migration step that left the three indices in different degraded states. The hypothesis is unverified; the per-phase ICs do not depend on it. Per the akosha agent's recon, akosha does not own a local code-graph indexer — it polls session-buddy's `get_code_graph` MCP tool at `poll_interval` and writes whatever session-buddy returns into `hot_store.store_code_graph`. So the `nodes`-as-list shape in the akosha handler originated in session-buddy's `get_code_graph` (or its source indexer). The Phase 1.2 fix returns a `degraded` envelope whenever the indexer shape is wrong, which is exactly the non-deceptive contract REQ-002 demands; indexer restoration (if any) is a separate PR per §10 Decision Rule.

## 5. Implementation Phases

### Phase 1: akosha (highest priority — first bug surfaced, tool-name bug blocks all akosha search work)

**Goal:** All 32 `akosha_*` tool-name registrations and ~8 source-doc/federation/allowlist strings drop the redundant prefix. The `search_code_patterns` handler returns a structured response at all 6 shape sites. The Claude Code TUI `/akosha` picker continues to work.

**Tasks:**

- **1.1 Tool-name registration sweep.** Walk the 11 files in §4.1 and strip the `akosha_` prefix from each `name="akosha_*"` decorator argument. Add explicit sub-tasks for each non-decorator pattern:
  - **1.1a Federation call** at `akosha/mcp/tools/ecosystem_skills.py:97` — change `tool_name="akosha_list_skills"` to `tool_name="list_skills"`. **Verify** that the same file's lines 103/109/115 entries for `mahavishnu_list_skills` / `session_buddy_list_skills` / `crackerjack_list_skills` are NOT changed.
  - **1.1b Tool-allowlist strings** in `akosha/akosha/mcp/tools/profiles.py:98-117` — strip the prefix in each register_fn → tool-name string.
  - **1.1c Skill catalog** in `akosha/akosha/mcp/skills_catalog/fitness-analyzer.md` (frontmatter `allowed-tools`) and `search-insights.md:47-48` — strip the prefix in each tool reference.
  - **1.1d Agent body** in `akosha/akosha/mcp/tools/agents/pattern-agent.md` — strip the prefix in each tool reference.
  - **1.1e Module/class docstrings** in `akosha/akosha/mcp/tools/akosha_tools.py` — strip the prefix in each tool reference.
- **1.2 Picker-filter consumer update.** Audit the Claude Code TUI picker-filter implementation (per `bodai-tool-naming-gap-2026-09-09.md`, the `/akosha` filter does prefix-match on the registered name). Switch the filter to **server-name match** so it continues to return the akosha tool list after the prefix-rename. The consumer is in the Claude Code TUI codebase (not in the akosha repo) — coordinate via a separate small PR there, OR file the picker as a Claude Code bug and land the akosha fix only after the consumer update is queued.
- **1.3 Handler shape fix.** At all 6 sites in §4.2, replace the unguarded `.values()` with a per-site shape guard that handles dict (preferred), list (legacy), missing (empty). For the primary site at `pycharm_tools.py:391`, the fix is `nodes = graph["graph_data"].get("nodes") or {}; for node in (nodes.values() if isinstance(nodes, dict) else nodes):` — adapted per site. Return envelope: `{"status": "ok" | "degraded", "results": [...], "error": "..."}` per `wire-up-contract.md` "Returns to / updates" — the deprecation of the old traceback is the state.
- **1.4 Regression tests.** `akosha/tests/unit/test_search_code_patterns.py` (new) — assert on the wire-shape envelope via `result.content[0].text` parsed via `_extract_tool_payload` (per memory `fastmcp-call-tool-returns-calltoolresult.md`). Stub the indexer to return dict, list, and missing shapes; assert the handler returns a structured response in all 3 cases.
- **1.5 Test-fixture update.** Update 12+ test files that hard-code `akosha_*` tool names. Enumerated by `rg "akosha_(search|get|find|analyze|publish|store|batch|list|run|cross|discover|query)_" akosha/tests/`. Full list (non-exhaustive — re-run before merge):
  - `akosha/tests/test_session_buddy_tools_coverage.py` (16 refs)
  - `akosha/tests/unit/test_mcp_otel_tools.py` (6)
  - `akosha/tests/unit/test_code_graph_tools.py` (8)
  - `akosha/tests/unit/mcp/tools/test_fitness_tools.py` (8)
  - `akosha/tests/unit/test_session_buddy_tools_integration.py` (2)
  - `akosha/tests/unit/test_session_buddy_tools_standalone.py` (2)
  - `akosha/tests/integration/test_query_local_traces_e2e.py` (1)
  - `akosha/tests/integration/test_get_agent_e2e.py` (10+)
  - `akosha/tests/integration/test_list_agents_e2e.py` (7)
  - `akosha/tests/unit/test_mcp_tools_profiles.py` (8+)
  - `akosha/tests/fixtures/full/tool_names.json` (6 names)
  - `akosha/tests/fixtures/standard/tool_names.json` (2 names)
  - Plus the files listed in §6.
- **1.6 .mcp.json impact check.** Run `rg "akosha_(search|get|find|analyze|publish|store|batch|list|run|cross|discover|query)_" --glob '*.mcp.json' ~/Projects/akosha/ ~/Projects/crackerjack/ ~/Projects/session-buddy/ ~/Projects/mahavishnu/` before declaring the rename non-breaking. Zero matches required (REQ-011).
- **1.7 SessionEnd hook wiring.** Append `agent-merge-on-end` entry to `akosha/.claude/settings.json` SessionEnd array, after the existing `worktree-session-isolation` entry. Mirrors `mahavishnu/.claude/settings.json` pattern (REQ-010).

**Exit criteria:**
- `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` returns without error and without the `'list' object has no attribute 'values'` traceback.
- `mcp__akosha__discover_tools()` returns the same tools under their canonical names (no `akosha_` prefix).
- `pytest akosha/tests -k "tool or search or mcp_inventory"` passes.
- `/akosha` TUI picker still returns the akosha tool list (REQ-008).
- Zero `.mcp.json` matches for the old tool names across all 4 Bodai repos (REQ-011).

#### Integration Contract — Phase 1.1 (tool-name + source-doc sweep)
- **Triggered from**: akosha MCP server startup (`akosha/mcp/server.py:__main__`); every Claude Code session that loads akosha's tool list; the federation server boot that reads `ecosystem_skills.py:97`.
- **Returns to / updates**: the FastMCP tool registry on the akosha `app` instance; the `_FederationServer` config at `ecosystem_skills.py:97` (deprecation of `tool_name="akosha_list_skills"` → `tool_name="list_skills"`); the tool-allowlist strings in `profiles.py:98-117`; the skill-catalog frontmatter; agent body text.
- **Demonstrable by**: `pytest akosha/tests/unit/test_mcp_tool_inventory.py::test_no_akosha_prefix_in_registered_names`
- **Rollback signal**: any `pytest akosha/tests/test_mcp_tool_inventory.py` failure; the inventory test enumerates expected tool names.
- **Observability added**: log line on startup `akosha_mcp_tools_registered count={N}` (where N is the new total, post-rename). Existing `akosha_search_results_total` (line 210) and `akosha_search_latency_milliseconds` (line 186) Prometheus metrics are reused for any search-handler invocation. **No new metrics are added** (the `akosha_tools_registered_total` claim from the prior plan revision was a phantom — verified by `rg "akosha_tools_registered" akosha/observability/prometheus_metrics.py` returning zero matches).
- **Fulfils**: REQ-001, REQ-011

#### Integration Contract — Phase 1.2 (picker-filter consumer update)
- **Triggered from**: Claude Code TUI startup; the picker filter implementation reads the registered tool name from the akosha MCP server.
- **Returns to / updates**: the Claude Code TUI picker implementation switches from prefix-match on registered name to **server-name match** (the registered server instance name is `akosha` regardless of what the tool names are).
- **Demonstrable by**: Claude Code TUI integration test asserting `/akosha` picker returns the akosha tool list post-rename. (Test lives in the Claude Code TUI codebase, not the akosha repo.)
- **Rollback signal**: any `/akosha` picker query that returns zero results when the akosha server is healthy.
- **Observability added**: TUI-level log line `picker_filter server=akosha match=server_name count={N}`.
- **Fulfils**: REQ-008

#### Integration Contract — Phase 1.3 (handler shape fix)
- **Triggered from**: any `mcp__akosha__search_code_patterns` call (one of: akosha MCP server startup indexer probe, agent session, manual test).
- **Returns to / updates**: the deprecation of the `'list' object has no attribute 'values'` traceback — the response envelope is the state. Old: `Error: 'list' object has no attribute 'values'`. New: `{"status": "ok" | "degraded", "results": [...], "error": "..."}`. This is a state change in the wire-shape contract.
- **Demonstrable by**: `pytest akosha/tests/unit/test_search_code_patterns.py::test_dict_shape_returns_results`, `::test_list_shape_returns_degraded_envelope`, `::test_missing_shape_returns_degraded_envelope` — all three pass.
- **Rollback signal**: any `crashed_handler: pycharm_search_code_patterns` log line; the existing `akosha_errors_total` Prometheus counter (line 522) would tick on the old failure mode.
- **Observability added**: existing `akosha_search_results_total` and `akosha_search_latency_milliseconds` are reused. New log line: `akosha_search_handler shape=<dict|list|missing> status=<ok|degraded>`.
- **Fulfils**: REQ-002, REQ-009

#### Integration Contract — Phase 1.4 (regression tests) and 1.5 (test-fixture update)
- **Triggered from**: `pytest akosha/tests/ -k "search or tool or mcp_inventory"`
- **Returns to / updates**: the test corpus; CI gate.
- **Demonstrable by**: `pytest akosha/tests/ -k "search_code_patterns or mcp_tool_inventory"` exits 0.
- **Rollback signal**: any test failure.
- **Observability added**: CI log line via the existing `crackerjack run -v` gate.
- **Fulfils**: REQ-007, REQ-012

#### Integration Contract — Phase 1.7 (SessionEnd hook wiring)
- **Triggered from**: Claude Code session-end event in a session operating inside `~/.local/state/mahavishnu/worktrees/akosha/`.
- **Returns to / updates**: `akosha/.claude/settings.json` SessionEnd array; the `mahavishnu.worktrees` policy governance.
- **Demonstrable by**: a Claude Code session that opens and closes inside the akosha worktree fires the `agent-merge-on-end.py` hook.
- **Rollback signal**: log line `merge-on-end not wired for repo=akosha` (new log line).
- **Observability added**: existing session-buddy reflection store captures the merge event.
- **Fulfils**: REQ-010

### Phase 2: crackerjack (second priority — `search_code` returning 0 is the most common search path)

**Goal:** `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result. `mcp__crackerjack__search_semantic(query="python", min_similarity=0.3)` returns ≥1 result.

**Tasks:**

- 2.1 Investigate the handlers at `crackerjack/mcp/tools/pycharm_tools.py:100` (`_register_search_code_tool` → wrapped function at `:103`) and `crackerjack/mcp/tools/semantic_tools.py:75` (`_register_search_semantic_tool` → wrapped function at `:77`). Identify which of the three sub-bugs applies: (a) indexer not running, (b) indexer writing to wrong path, (c) indexer writing wrong shape. Most likely the indexer schedule is gone or disabled.
- 2.2 Fix the root cause. If the indexer is gone, restore it as a thin wrapper that walks the crackerjack repo and writes to the expected index path. If the indexer is writing the wrong shape, fix the indexer. Document the reindex procedure in `crackerjack/docs/operations/` if no prior doc exists.
- 2.3 Regression tests:
  - `crackerjack/tests/unit/mcp/tools/test_search_code.py` (new) — stubbed indexer (in-process dict-backed) returns populated results for `def test_`.
  - `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` (new) — known-embedded phrase returns ≥1 result at `min_similarity=0.3`.
- 2.4 .mcp.json impact check: `rg "crackerjack_(search|semantic)_" --glob '*.mcp.json' ~/Projects/crackerjack/ ~/Projects/mahavishnu/` — zero matches required (REQ-011).
- 2.5 SessionEnd hook wiring: append `agent-merge-on-end` entry to `crackerjack/.claude/settings.json` SessionEnd array (REQ-010).
- 2.6 Per-repo push governance cross-link: add a one-liner to `crackerjack/CLAUDE.md` linking to `.claude/decisions/2026-10-03-mainautopush.md` (mahavishnu's) and stating that crackerjack retains user-controlled push until/unless the user replicates the decision doc locally (REQ-013).

**Exit criteria:**
- `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result.
- `mcp__crackerjack__search_semantic(query="python class function import", min_similarity=0.3)` returns ≥1 result.
- `pytest crackerjack/tests -k "search or pycharm_tools or semantic"` passes.
- Zero `.mcp.json` matches for old tool names (REQ-011).
- SessionEnd hook wired (REQ-010).
- Push governance cross-link in `crackerjack/CLAUDE.md` (REQ-013).

#### Integration Contract — Phase 2.1-2.2 (indexer/handler fix)
- **Triggered from**: crackerjack MCP handler at `search_code`/`search_semantic` request time.
- **Returns to / updates**: the crackerjack search index. State destination is the on-disk or in-memory index that the handler reads.
- **Demonstrable by**: `pytest crackerjack/tests/unit/mcp/tools/test_search_code.py::test_search_code_finds_test_function` passes.
- **Rollback signal**: any `pytest crackerjack/tests -k "search"` failure; the existing `crackerjack_run` trace counter.
- **Observability added**: per-request counter on the MCP handler itself: `crackerjack_search_invoked_total{tool="search_code" | "search_semantic", status="ok" | "degraded"}`. This signal works regardless of whether the indexer is restored or not — it tracks the MCP handler invocation, not the indexer. The previously-considered "indexer_last_run_timestamp_seconds" gauge was conditional on identifying an indexer schedule; defer that to the indexer-restoration PR if and when it happens.
- **Fulfils**: REQ-003, REQ-004, REQ-007, REQ-012

#### Integration Contract — Phase 2.5 (SessionEnd hook) and 2.6 (push governance)
- Same pattern as Phase 1.7 / Phase 1 cross-link.
- **Fulfils**: REQ-010, REQ-013

### Phase 3: session-buddy (third priority — `quick_search` returning 0 affects all session-buddy reflection flows)

**Goal:** `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result. `mcp__session-buddy__search_by_concept(concept="python", min_score=0.3)` returns ≥1 result.

**Tasks:**

- 3.1 Investigate the wrappers at `session_buddy/tools/memory_tools.py:48,57` and the underlying `_quick_search_impl` / `_search_by_concept_impl`. Identify which of the three sub-bugs applies (per §4.3 hypothesis).
- 3.2 Fix the root cause.
- 3.3 Regression tests:
  - `session-buddy/tests/unit/test_quick_search.py` (new) — known-embedded phrase returns ≥1 result.
  - `session-buddy/tests/unit/test_search_by_concept.py` (new) — known concept returns ≥1 result.
- 3.4 .mcp.json impact check: `rg "session_buddy_(quick|search|concept)_" --glob '*.mcp.json' ~/Projects/session-buddy/ ~/Projects/mahavishnu/` — zero matches (REQ-011).
- 3.5 SessionEnd hook wiring: append `agent-merge-on-end` entry to `session-buddy/.claude/settings.json` SessionEnd array (REQ-010).
- 3.6 Per-repo push governance cross-link: add a one-liner to `session-buddy/CLAUDE.md` (REQ-013).

**Exit criteria:**
- `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result.
- `mcp__session-buddy__search_by_concept(concept="python class function", min_score=0.3)` returns ≥1 result.
- `pytest session-buddy/tests -k "search or memory or quick"` passes.
- Zero `.mcp.json` matches for old tool names (REQ-011).
- SessionEnd hook wired (REQ-010).
- Push governance cross-link (REQ-013).

#### Integration Contract — Phase 3.1-3.2 (handler/indexer fix)
- **Triggered from**: session-buddy MCP handler at `quick_search`/`search_by_concept` request time.
- **Returns to / updates**: the session-buddy reflection index.
- **Demonstrable by**: `pytest session-buddy/tests/unit/test_quick_search.py::test_quick_search_finds_stored_reflection` passes.
- **Rollback signal**: any `pytest session-buddy/tests -k "search"` failure.
- **Observability added**: per-request counter on the MCP handler: `session_buddy_search_invoked_total{tool="quick_search" | "search_by_concept", status="ok" | "degraded"}`. This signal works regardless of the indexer state. The previously-considered "existing session-buddy reflection stats" hand-wave was too weak per the wire-up contract; this is the committed signal.
- **Fulfils**: REQ-005, REQ-006, REQ-007, REQ-012

#### Integration Contract — Phase 3.5 / 3.6
- Same pattern as Phase 1.7 / 2.5 / 2.6.
- **Fulfils**: REQ-010, REQ-013

## 6. Required Code Changes

**Worktree convention:** Each phase runs in its own worktree. **Phase 1**: `~/.local/state/mahavishnu/worktrees/akosha/`. **Phase 2**: `~/.local/state/mahavishnu/worktrees/crackerjack/`. **Phase 3**: `~/.local/state/mahavishnu/worktrees/session-buddy/`. Merge orchestration runs from the **mahavishnu venv** (where `mahavishnu.core.merge_to_main` is on `PYTHONPATH`).

### Phase 1: akosha (worktree: `~/.local/state/mahavishnu/worktrees/akosha/`)

- [ ] `akosha/mcp/tools/pycharm_tools.py` — strip 5 decorator prefixes + fix 5 shape sites (`:391, :489, :586, :713, :762`)
- [ ] `akosha/mcp/tools/akosha_tools.py` — strip 11 decorator prefixes + module/class docstring updates
- [ ] `akosha/mcp/tools/skill_tools.py` — strip 2 decorator prefixes + 1 source-doc string at `:120-125`
- [ ] `akosha/mcp/tools/agents_tools.py` — strip 2 decorator prefixes + 1 source-doc string at `:174`
- [ ] `akosha/mcp/tools/code_graph_tools.py` — strip 4 decorator prefixes + fix 1 shape site at `:205`
- [ ] `akosha/mcp/tools/cross_repo_tools.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/ecosystem_skills.py` — strip 1 decorator prefix + **federation call fix at `:97`** (verify `:103/109/115` not changed)
- [ ] `akosha/mcp/tools/eventbridge_tools.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/session_buddy_tools.py` — strip 2 decorator prefixes
- [ ] `akosha/mcp/tools/otel_tools.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/fitness_tools.py` — strip 2 decorator prefixes
- [ ] `akosha/mcp/tools/profiles.py:98-117` — strip prefix in allowlist strings
- [ ] `akosha/mcp/client.py:80` — strip prefix in client string
- [ ] `akosha/mcp/skills_catalog/fitness-analyzer.md` (frontmatter) + `search-insights.md:47-48` (prose) — strip prefix
- [ ] `akosha/mcp/tools/agents/pattern-agent.md` (3 refs) — strip prefix
- [ ] `akosha/.claude/settings.json` — append `agent-merge-on-end` to SessionEnd array (REQ-010)
- [ ] `akosha/CLAUDE.md` — push governance cross-link to `2026-10-03-mainautopush.md` (REQ-013)
- [ ] **New**: `akosha/tests/unit/test_search_code_patterns.py` — regression test for shape fix (REQ-007, REQ-012)
- [ ] **New**: `akosha/tests/unit/test_mcp_tool_inventory.py::test_no_akosha_prefix_in_registered_names` — single test asserting no decorator has the prefix
- [ ] `akosha/tests/test_session_buddy_tools_coverage.py` — update 16 references
- [ ] `akosha/tests/unit/test_mcp_otel_tools.py` — update 6 references
- [ ] `akosha/tests/unit/test_code_graph_tools.py` — update 8 references
- [ ] `akosha/tests/unit/mcp/tools/test_fitness_tools.py` — update 8 references
- [ ] `akosha/tests/unit/test_session_buddy_tools_integration.py` — update 2 references
- [ ] `akosha/tests/unit/test_session_buddy_tools_standalone.py` — update 2 references
- [ ] `akosha/tests/integration/test_query_local_traces_e2e.py` — update 1 reference
- [ ] `akosha/tests/integration/test_get_agent_e2e.py` — update 10+ references
- [ ] `akosha/tests/integration/test_list_agents_e2e.py` — update 7 references
- [ ] `akosha/tests/unit/test_mcp_tools_profiles.py` — update 8+ references
- [ ] `akosha/tests/fixtures/full/tool_names.json` — update 6 names
- [ ] `akosha/tests/fixtures/standard/tool_names.json` — update 2 names
- [ ] `akosha/tests/fixtures/minimal/tool_names.json` — verify and update
- [ ] `akosha/tests/fixtures/full/tool_names.json` — verify and update
- [ ] `akosha/tests/test_skills_signer.py` — update assertions
- [ ] `akosha/tests/test_pycharm_tools_coverage.py` — update assertions
- [ ] `akosha/tests/integration/test_mcp_integration.py` — update assertions
- [ ] `akosha/tests/unit/test_mcp_tool_inventory.py` — update assertions
- [ ] `akosha/tests/unit/test_mcp_akosha_tools.py` — verify still passes (now no prefix in registered name)
- [ ] `akosha/tests/unit/test_mcp_akosha_tools_runtime.py` — verify still passes
- [ ] `akosha/tests/unit/test_cross_repo_capability_search.py` — verify still passes
- [ ] **Picker-filter consumer update** (separate Claude Code TUI PR per Phase 1.2) — file as a followup issue against the TUI repo

### Phase 2: crackerjack (worktree: `~/.local/state/mahavishnu/worktrees/crackerjack/`)

- [ ] `crackerjack/mcp/tools/pycharm_tools.py:100` — `_register_search_code_tool` investigation + fix
- [ ] `crackerjack/mcp/tools/semantic_tools.py:75` — `_register_search_semantic_tool` investigation + fix
- [ ] Indexer restoration (path TBD by subagent; if no indexer schedule exists, document the reindex procedure in a `docs/operations/` file)
- [ ] `crackerjack/.claude/settings.json` — append `agent-merge-on-end` to SessionEnd array (REQ-010)
- [ ] `crackerjack/CLAUDE.md` — push governance cross-link (REQ-013)
- [ ] **New**: `crackerjack/tests/unit/mcp/tools/test_search_code.py` — regression test (REQ-007, REQ-012)
- [ ] **New**: `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` — regression test (REQ-007, REQ-012)

### Phase 3: session-buddy (worktree: `~/.local/state/mahavishnu/worktrees/session-buddy/`)

- [ ] `session_buddy/tools/memory_tools.py:48,57` — wrapper fixes
- [ ] Underlying `_quick_search_impl` and `_search_by_concept_impl` (subagent traces the import source)
- [ ] Indexer / reflection store fix (path TBD)
- [ ] `session-buddy/.claude/settings.json` — append `agent-merge-on-end` to SessionEnd array (REQ-010)
- [ ] `session-buddy/CLAUDE.md` — push governance cross-link (REQ-013)
- [ ] **New**: `session-buddy/tests/unit/test_quick_search.py` — regression test (REQ-007, REQ-012)
- [ ] **New**: `session-buddy/tests/unit/test_search_by_concept.py` — regression test (REQ-007, REQ-012)

## 7. Validation Matrix

| Probe | Tool | Expected result | Evidence location |
|---|---|---|---|
| Akosha tool-name fix | `pytest akosha/tests/unit/test_mcp_tool_inventory.py::test_no_akosha_prefix_in_registered_names` | exits 0 | `akosha/tests/unit/test_mcp_tool_inventory.py` |
| Akosha source-doc sweep | `rg "akosha_(search\|get\|find\|analyze\|publish\|store\|batch\|list\|run\|cross\|discover\|query)_" akosha/akosha/ akosha/tests/` | zero non-comment matches in production, only fixture/intentional refs in tests | post-rename `rg` |
| Akosha handler shape fix (all 6 sites) | `pytest akosha/tests/unit/test_search_code_patterns.py` | exits 0; all 3 shape stubs return structured response | `akosha/tests/unit/test_search_code_patterns.py` |
| Akosha wire-envelope regression | `pytest akosha/tests/unit/test_search_code_patterns.py::test_wire_envelope_via_extract_tool_payload` | exits 0 | `akosha/tests/unit/test_search_code_patterns.py` (REQ-012) |
| Akosha .mcp.json impact | `rg "akosha_(search\|get\|find\|analyze\|publish\|store\|batch\|list\|run\|cross\|discover\|query)_" --glob '*.mcp.json' ~/Projects/akosha/ ~/Projects/mahavishnu/` | zero matches | shell |
| Akosha picker (TUI consumer) | `/akosha` TUI picker | returns the akosha tool list post-rename | Claude Code TUI test |
| Crackerjack code search | `pytest crackerjack/tests/unit/mcp/tools/test_search_code.py::test_search_code_finds_test_function` | exits 0 | `crackerjack/tests/unit/mcp/tools/test_search_code.py` |
| Crackerjack semantic search | `pytest crackerjack/tests/unit/mcp/tools/test_search_semantic.py::test_search_semantic_finds_phrase` | exits 0 | `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` |
| Crackerjack .mcp.json impact | `rg "crackerjack_(search\|semantic)_" --glob '*.mcp.json' ~/Projects/crackerjack/ ~/Projects/mahavishnu/` | zero matches | shell |
| Session-buddy quick_search | `pytest session-buddy/tests/unit/test_quick_search.py::test_quick_search_finds_stored_reflection` | exits 0 | `session-buddy/tests/unit/test_quick_search.py` |
| Session-buddy search_by_concept | `pytest session-buddy/tests/unit/test_search_by_concept.py::test_search_by_concept_finds_concept` | exits 0 | `session-buddy/tests/unit/test_search_by_concept.py` |
| Session-buddy .mcp.json impact | `rg "session_buddy_(quick\|search\|concept)_" --glob '*.mcp.json' ~/Projects/session-buddy/ ~/Projects/mahavishnu/` | zero matches | shell |
| Akosha SessionEnd hook | Claude Code session-end event in akosha worktree | fires `agent-merge-on-end.py` | `akosha/.claude/settings.json` (REQ-010) |
| Akosha liveness unchanged | `mcp__akosha__get_liveness()` | 200, version populated, uptime > 0 | Pre/post probe comparison |
| Crackerjack liveness unchanged | crackerjack `/health` | 200 | Pre/post probe comparison |
| Session-buddy liveness unchanged | session-buddy `/health` | 200 | Pre/post probe comparison |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tool-name rename breaks downstream callers (any code that does `app.get_tool("akosha_search_code_patterns")` or imports from a federation config) | Medium | The `rg "akosha_*" --glob '*.py' akosha/` + `rg "akosha_*" --glob '*.mcp.json' ~/Projects/{akosha,crackerjack,session-buddy,mahavishnu}/` enumeration in §6 covers known call sites. The federation call at `ecosystem_skills.py:97` is the most consequential — handle explicitly per Phase 1.1a. |
| Picker-filter side-effect breaks `/akosha` tool list in TUI | Medium | Phase 1.2 is a required sub-task: the Claude Code TUI consumer must switch from prefix-match to server-name match in the same PR. The integration test asserts `/akosha` picker still works post-rename. |
| Indexer restoration is more invasive than expected (full cron job rebuild) | Medium | Defer to a followup if it's > 1 day of work. The Phase 2 fix can stop at "the handler returns a typed `degraded` envelope when the indexer has not produced any rows" — that satisfies REQ-003/004 at the *non-deceptive* level without rebuilding the indexer. Per §9 Decision Rule: split out the indexer work as a separate PR. |
| `result.content[0].text` envelope regression — handler test passes in-process but wire shape leaks traceback string | Low | Regression tests assert via `_extract_tool_payload` (REQ-012). |
| One repo's fix exposes a different bug in the indexer | Low | Each phase is in its own worktree; the failed indexer can be punted without blocking the other phases. |
| `mahavishnu.core.merge_to_main` not on PYTHONPATH in target repos | High (architectural) | Invoke the orchestrator from the **mahavishnu venv** (`python -m mahavishnu.core.merge_to_main --branch <branch>`), or route the merge through `mcp__mahavishnu__pool_route_execute` so the orchestrator process owns the import. Documented in the plan intro. |
| `agent-merge-on-end` SessionEnd hook not wired in target repos | High (architectural) | Per-phase SessionEnd wiring is a required sub-task (Phase 1.7, 2.5, 3.5). Without it, the auto-merge does not fire from sessions in those worktrees. |
| `git push origin main` auto-fired on the 3 target repos (mahavishnu's auto-push exception is mahavishnu-scoped) | Low | Each target repo retains user-controlled push until the user replicates `2026-10-03-mainautopush.md` locally. REQ-013 cross-link in each repo's CLAUDE.md makes this explicit. |
| The semantic index genuinely has nothing to index (crackerjack/session-buddy's source code was never embedded) | Medium | If the fix is "the indexer was never turned on," the plan delivers a degraded-envelope result for this PR and a followup reindex PR (or a documented `make reindex` procedure) afterwards. Acceptable scope cut per §9. |
| User wants parallel execution | Low | §9 Decision Rule covers this: dispatch via `mcp__mahavishnu__pool_route_execute` (ad-hoc) or `mcp__mahavishnu__trigger_workflow` (durable) with 3 sub-agents in 3 worktrees. |
| Shared root cause hypothesis is wrong (the 3 broken surfaces have different actual causes) | Medium | Hypothesis is one possible cause, not the only one. Per-phase ICs do not depend on it. Each phase is independently testable. |
| `MAHAVISHNU_AUTO_MERGE` and auto-push race the akosha/crackerjack/session-buddy release pipelines | Low | This plan does **not** push to remote. Per `feedback-bodai-push-is-user-controlled.md`, the user controls push timing. |

## 9. Decision Rule

This plan is "done enough" when:

- All 3 phases have shipped as 3 separate merge cycles, each with its own integration contracts fulfilled.
- The 16 validation probes in §7 all pass when run against the released versions.
- The picker-filter consumer update (Phase 1.2) has shipped.
- The per-repo SessionEnd hooks (Phase 1.7, 2.5, 3.5) are wired.
- The per-repo push governance cross-links (Phase 1.6, 2.6, 3.6) are in each target repo's CLAUDE.md.
- No new MCP tools were added.
- No `/health` route was modified.
- The followup plan for health-check-enrichment has been written (see §10 below).

If the indexer-restoration work in Phase 2 or Phase 3 exceeds 1 day of effort, **split out the indexer work as a separate PR** and leave the handler-fix-only in this plan. A handler that returns `degraded` honestly is better than a handler that returns `[]` deceptively. Per `feedback-mcp-common-version-bump-is-user.md`, the user owns the version bump; no version bump is in scope for this plan. Per `feedback-bodai-push-is-user-controlled.md`, the user owns the push; this plan does not push.

If parallel execution is preferred over sequential, dispatch the 3 phases as 3 sub-agents via `mcp__mahavishnu__pool_route_execute` (ad-hoc) or `mcp__mahavishnu__trigger_workflow` (durable), each in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`. Per `feedback-workflow-parallel-same-repo-no-isolation.md`, each sub-agent must use `git add <scope-only>` (no `git add -A`). The merge orchestration runs from the **mahavishnu venv** (where `mahavishnu.core.merge_to_main` is on `PYTHONPATH`); the 3 target worktrees do not have it. Per `feedback-worktree-update-ref-drops-parallel-commits.md`, the worktree-branch ref must be fast-forward of `main` before any `git update-ref`; verify per sub-agent before merge.

## 10. Followup Plan: Health-Check Enrichment

This is a **separate plan** to be written after this plan ships. It is tracked here so the work isn't forgotten, not as a deliverable of this plan.

**Why it's separate:** the `/health` route in each of the three servers currently returns 200 with a version string, regardless of whether the search feed is degraded. The `mcp-surface-health-illusion` memory documents this failure mode. The fix requires:
- Adding a per-feed health aggregation to each server's `/health` route.
- Returning 503 (not 200) when any feed is degraded.
- Surfacing the feed names and last-updated timestamps in the response body.

**Owners:** per-server MCP maintainers (one PR per server).

**Policy basis:** `.claude/decisions/mcp-backend-wiring-discipline.md` (referenced in mahavishnu's CLAUDE.md) — "every Bodai MCP server's `/health` must aggregate per-feed state and return 503 on degraded."

**Status when this plan ships:** not yet written. To be filed at `mahavishnu/docs/plans/2026-10-XX-mcp-health-check-enrichment.md` after this plan's three merge cycles land.

**Cross-link durability:** when the followup is written, add a one-line cross-link from `.claude/decisions/mcp-backend-wiring-discipline.md` to the followup plan's path. Also add forward-references in each target repo's CLAUDE.md so a future per-server `/health` audit discovers it.

## References

- `.claude/decisions/wire-up-contract.md` — Integration Contract policy this plan follows.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — referenced for §10.
- `.claude/decisions/2026-10-03-mainautopush.md` — mahavishnu-scoped auto-push governance (referenced in §8 and §13).
- `docs/plans/TEMPLATE.md` — plan structure this plan mirrors.
- `docs/plans/2026-10-03-trunk-based-agent-review.md` — merge workflow spec.
- `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` — merge workflow design.
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema this plan's YAML follows.
- `docs/schemas/topic-vocabulary-v1.md` — topic vocabulary (this plan uses `mcp-search` in warning-mode; rationale in §4.5).
- `~/.claude/CLAUDE.md` — worktree location convention (`~/.local/state/mahavishnu/worktrees/<basename>/`).
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/mcp-surface-health-illusion.md` — why this fix matters.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/bodai-tool-naming-gap-2026-09-09.md` — picker-filter prefix-match convention (resolution in Phase 1.2).
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/fastmcp-call-tool-returns-calltoolresult.md` — wire-envelope `result.content[0].text` parsing (REQ-012).
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-workflow-parallel-same-repo-no-isolation.md` — why each phase gets its own worktree.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-worktree-update-ref-drops-parallel-commits.md` — ref-safety rules for parallel worktrees.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md` — no push without explicit approval.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-mcp-common-version-bump-is-user.md` — no version bump from agents.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-crackerjack-publish-stage-is-user.md` — no `crackerjack -p` from agents.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/bodai-pytest-binary-cwd.md` — run pytest via `<repo>/.venv/bin/pytest`, not bare `pytest`.
