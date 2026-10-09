---
status: draft
role: implementation
kind: plan
date: 2026-10-09
last_reviewed: 2026-10-09
superseded_by: null
blocks_on: []
topic: mcp-design
---

# Bodai MCP Search Infrastructure Fix — akosha / crackerjack / session-buddy

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for the per-repo worktrees. Each repo runs in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/` (where `<repo>` is `akosha`, `crackerjack`, or `session-buddy` per the user-level convention in `~/.claude/CLAUDE.md`). Per `feedback-workflow-parallel-same-repo-no-isolation.md` and `feedback-worktree-update-ref-drops-parallel-commits.md`, worktrees are independent; per-rebase → SHA-reverify → squash-merge flow runs per repo. The merge workflow's orchestrator (`mahavishnu.core.merge_to_main`) is **only on the PYTHONPATH of the mahavishnu repo's venv** — invoke from there (`python -m mahavishnu.core.merge_to_main --branch <branch>`), or route the merge through `mcp__mahavishnu__pool_route_execute` so the orchestrator process owns the import.

**Goal:** Restore the three MCP code-/semantic-search surfaces — `akosha_search_code_patterns`, `crackerjack search_code`/`search_semantic`, `session-buddy quick_search`/`search_by_concept` — so that
(a) advertised tool names match the actual server-registered names (no more `No such tool available` for the prompt-header names), and
(b) empty/missing indices do not crash or silently return `[]`; the tools return a structured `{"status": "ok" | "degraded", "results": [...]}` envelope that callers can branch on. Concretely: a probe call that should obviously return data (`mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` or `mcp__session-buddy__quick_search(query="python")`) must return a populated result list or an explicit `degraded` envelope, never an `[]` and never an internal-error traceback.

**Architecture:** Three independent merge cycles (one per repo) — the project uses ephemeral branches + squash-merge to local `main` + auto-push (per `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4), no GitHub PR step. Each phase ships in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`. Per `feedback-bodai-push-is-user-controlled.md`, `git push origin main` is governed by `.claude/decisions/2026-10-03-mainautopush.md` — that decision is **mahavishnu-scoped**; the three target repos retain user-controlled push until they adopt the same decision. No shared release, no version bump — the 0.22.x / 0.30.x / 0.27.x lines of akosha / session-buddy / crackerjack each pick up the fix on their own cadence.

**Tech Stack:** Python 3.14, FastMCP 2.x (`@mcp.tool(name=...)` and `@app.tool(name=...)` decorators), per-repo existing index modules:
- **Akosha** — `akosha.search` index (semantic + code-graph); handlers in `akosha/mcp/tools/{pycharm_tools,code_graph_tools,akosha_tools,...}.py`.
- **Crackerjack** — `crackerjack.mcp.tools.pycharm_tools` (code search) + `crackerjack.mcp.tools.semantic_tools` (semantic search).
- **Session-buddy** — `session_buddy.tools.memory_tools` (reflection/conversation store).

**Spec:** None. This plan documents a bug fix only; no new design space is being introduced.

## 1. Outcome

When this plan ships:

- `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py", scope="python")` returns a structured response (populated results when the index has them, `degraded` envelope when the index is empty), never a traceback.
- `mcp__akosha__get_liveness()` still returns 200 with `version` and `uptime_seconds` populated.
- `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result.
- `mcp__crackerjack__search_semantic(query="python", min_similarity=0.3)` returns ≥1 result.
- `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result.
- `mcp__session-buddy__search_by_concept(concept="python", min_score=0.3)` returns ≥1 result.
- The Claude Code TUI `/akosha` picker still returns the akosha tool list after the prefix-rename (REQ-008). Sequencing: akosha rename lands first; the Claude Code picker consumer update lands in a separate Claude Code PR (the TUI lives in Anthropic's Claude Code, not in any Bodai repo — see §4.1).
- The prompt-header advertised names `mcp__akosha__search_code_patterns` (without the redundant `akosha_` prefix in the tool name) **resolve correctly** via the canonical harness path. The double-prefix workaround (`mcp__akosha__akosha_search_code_patterns`) is no longer necessary.

Concrete success metric: every probe call above either populates results or returns a typed `degraded` envelope — no `[]` empty arrays, no `'list' object has no attribute 'values'` tracebacks, and the `/akosha` picker still works (post Claude Code TUI consumer update).

## 2. Goals

1. **Fix akosha tool-name registration bug**: every `@mcp.tool(name="akosha_*")` decorator loses its redundant `akosha_` prefix in the registered name. Source-doc strings, federation call sites, allowlist strings, and class docstrings that carry the prefix are updated in the same PR. (REQ-001, REQ-011)
2. **Fix akosha picker-filter side-effect**: the Claude Code TUI `/akosha` picker implementation is updated to filter by server name (not prefix-match on registered name) so the prefix-rename doesn't break the picker. Lands in a separate Claude Code TUI PR, sequenced after the akosha rename. (REQ-008)
3. **Fix akosha `search_code_patterns` handler**: the `'list' object has no attribute 'values'` runtime error in the code-pattern search handler is resolved at all 6 shape sites (not just one). The handler returns a structured response (populated or `degraded`), never a traceback. (REQ-002, REQ-009)
4. **Fix crackerjack `search_code` empty-result bug**: a literal regex like `def test_` against `*.py` returns ≥1 result. (REQ-003)
5. **Fix crackerjack `search_semantic` empty-result bug**: a generic query like `python class function` at `min_similarity=0.3` returns ≥1 result. (REQ-004)
6. **Fix session-buddy `quick_search` / `search_by_concept` empty-result bug**: a generic query like `python` at `min_score=0.3` returns ≥1 result. (REQ-005, REQ-006)
7. **Wire the auto-merge SessionEnd hook** into the 3 target repos' `.claude/settings.json` so merge cycles can complete from sessions in those worktrees. Includes copying the hook scripts from `mahavishnu/.claude/hooks/` to each target repo's `.claude/hooks/`. (REQ-010)
8. **Each fix ships with a regression test** that fails on the current code, passes on the fix, and asserts on the wire-shape envelope (not the in-process return value). (REQ-007, REQ-012)
9. **No `.mcp.json` in any of the 4 Bodai repos references the pre-rename `akosha_*` tool names** after the rename. (REQ-011)
10. **Per-repo push governance cross-link in each target repo's `CLAUDE.md`** — each repo's CLAUDE.md points to `mahavishnu/.claude/decisions/2026-10-03-mainautopush.md` and states the repo retains user-controlled push until the user replicates the decision locally. (REQ-013)

## 3. Non-Goals

- **No health-check enrichment** (the `/health` route should aggregate per-feed state and return 503 on degraded). That is a separate plan, tracked as a followup in §"Followup Plan" below. Reason: a separate code path (health route), separate ownership (per-server), and separate policy concerns (`mcp-backend-wiring-discipline.md`).
- **No new MCP tools.** Only existing tools get the fix.
- **No deprecation shims for the old double-prefix tool names.** The Claude Code harness already strips the redundant `akosha_` prefix when generating the prompt header; no caller should be invoking `mcp__akosha__akosha_search_code_patterns` because the harness never advertises that name. Confirmed by `mcp__akosha__discover_tools()` returning the canonical names.
- **No version bumps, no `crackerjack run -p`, no PyPI publish.** Per `feedback-mcp-common-version-bump-is-user.md` and `feedback-crackerjack-publish-stage-is-user.md`, **the user** owns version and release decisions. The user controls `git push origin main` for all 5 Bodai repos per `feedback-bodai-push-is-user-controlled.md` (mahavishnu has an auto-push exception per `2026-10-03-mainautopush.md`; the 3 target repos do not).
- **No cross-repo release coordination.** Three independent merge cycles, three independent merges, three independent bumps if/when the user chooses to.
- **No Prometheus metric name renames.** `akosha_search_latency_milliseconds` and other `akosha_*` strings in `akosha/observability/prometheus_metrics.py` and `akosha/monitoring/metrics.py` are **metric identifiers**, not FastMCP tool names. Operators query them as `akosha_*` in Grafana. The plan's `akosha_`-prefix strip applies to FastMCP tool registrations, federation call parameters, and allowlist strings only — NOT to Prometheus metric names. (REQ-001 scope clarification.)
- **No indexer rewrite.** If the search index is empty because the indexer is broken, we fix the indexer. If it's empty because nothing was ever indexed, we add a test fixture and a documented reindex procedure — not a re-architecture.
- **No removal of any production feature** that depends on the broken search surfaces. Per the `mcp-surface-health-illusion` memory, an empty search surface is not an excuse to delete the tool — production features that *call* the search surface continue to work, they just get empty results. The fix here makes those results honest.

## 4. Current Findings

> **Path convention used in this section:** All file paths are **worktree-relative** (i.e., relative to `~/.local/state/mahavishnu/worktrees/<repo>/`). Resolved absolute paths would be `<worktree>/akosha/mcp/tools/pycharm_tools.py` etc. This convention matches §6 and is what the implementer reads from inside the worktree.

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

**Downstream side-effect: Claude Code TUI picker filter (REQ-008).** Per the 29-day-old memory `bodai-tool-naming-gap-2026-09-09.md`, the TUI `/akosha` picker filter does prefix-match on the registered name. Stripping the prefix requires the picker implementation to switch from prefix-match to **server-name match**. **The Claude Code TUI lives in Anthropic's Claude Code, not in any Bodai repo — the picker consumer update must land in a separate Claude Code PR (or a Claude Code bug report), sequenced after the akosha rename.** The akosha rename can ship without the picker update if a Claude Code bug is filed in parallel; the picker update is sequenced and not in scope for this plan's three merge cycles. **Both findings from the multi-agent review are correct: the prefix-rename is right, AND the picker-filter implementation must be updated — but not in the "same PR."**

**Additional source-doc / federation / allowlist / docstring string sites that carry the prefix and must be updated in the same PR (not just decorator arguments):**

- `akosha/mcp/tools/profiles.py:95-117` — string list mapping register_fn → tool names (allowlist)
- `akosha/mcp/client.py:79-80` — federation-style direct MCP call to `"akosha_query_local_traces"`
- `akosha/mcp/tools/agents_tools.py:174` — `"mcp__akosha__akosha_run_fitness_analysis"` in a list
- `akosha/mcp/tools/skill_tools.py:120-125` — SkillMetadata `tool_refs`
- `akosha/mcp/tools/akosha_tools.py:857-858` — class docstring referencing `akosha_analyze_trends` and `akosha_get_system_metrics`
- `akosha/mcp/tools/ecosystem_skills.py:97` — `tool_name="akosha_list_skills"` inside `_FederationServer` config (cross-MCP fan-out trigger; changing this to `list_skills` keeps `mcp__akosha__list_ecosystem_skills` federation working. **Verify that the same file's lines 103/109/115 entries for `mahavishnu_list_skills` / `session_buddy_list_skills` / `crackerjack_list_skills` are NOT changed — only the akosha entry.**)
- `akosha/security.py` — 10+ allowlist lines (exact line range to be enumerated during the Phase 1.1 sweep)
- `akosha/mcp/server.py` — 4 references (allowlist/string refs)
- `akosha/mcp/tools/ecosystem_skills_cache.py` — 1 docstring reference
- `akosha/mcp/tools/group_registers.py` — 2 docstring references
- `akosha/mcp/skills_catalog/fitness-analyzer.md` (frontmatter `allowed-tools`)
- `akosha/mcp/skills_catalog/search-insights.md:46-48` (skill catalog prose)
- `akosha/mcp/tools/agents/pattern-agent.md` — **14 references** in frontmatter and six bullet sections (verified by `rg -c 'mcp__akosha__akosha_' akosha/mcp/tools/agents/pattern-agent.md`)

A pure `sed`-of-decorators pass will leak these. The sweep must be a target-file walk that classifies each hit as one of: (a) decorator argument — strip prefix, (b) registry-construction string — strip prefix, (c) federation call parameter — strip prefix (per-server), (d) tool-allowlist string in `profiles.py` or `security.py` — strip prefix, (e) skill-catalog frontmatter/prose — strip prefix, (f) agent body — strip prefix (e.g., 14 hits in `pattern-agent.md`), (g) module/class docstring — strip prefix. Patterns (b)/(d)/(e)/(f)/(g) are NOT decorator arguments and a regex match on `name="akosha_` will miss them.

### 4.2 Akosha: code-pattern search handler bug (functional, multi-site)

The `search_code_patterns` handler at `akosha/mcp/tools/pycharm_tools.py:346-430` throws `Error: 'list' object has no attribute 'values'` on every query. The actual `.values()` call that raises is at **`akosha/mcp/tools/pycharm_tools.py:391`** (`for node in graph["graph_data"].get("nodes", {}).values():`), not `:341` (which is the `name="akosha_search_code_patterns"` argument inside a `ToolMetadata(...)` decorator). The default-`{}` makes `.values()` safe when `nodes` is absent, unsafe when `nodes` is present-as-a-list (the actual session-buddy indexer shape, per the akosha agent's recon).

The same bug pattern recurs at 4 more sites in the same file plus 1 in `code_graph_tools.py`:
- `akosha/mcp/tools/pycharm_tools.py:391` (primary)
- `akosha/mcp/tools/pycharm_tools.py:489`
- `akosha/mcp/tools/pycharm_tools.py:586`
- `akosha/mcp/tools/pycharm_tools.py:713`
- `akosha/mcp/tools/pycharm_tools.py:762`
- `akosha/mcp/tools/code_graph_tools.py:205`

The fix is not a single shape handler — it's a per-site guard that handles three indexer shapes: dict (preferred), list (legacy), missing (empty). Per-site is acceptable (the 6 sites are structurally similar but have different surrounding types); a shared `_nodes_iter(graph_data)` helper is an option if implementer prefers DRY.

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
    title: "Akosha FastMCP tool names match prompt-header advertised names (decorator arg + source-doc + federation + allowlist + docstring sweep, NOT Prometheus metric names)"
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
    title: "Claude Code TUI `/akosha` picker uses server-name match (not prefix-match on registered name) and returns the akosha tool list after the prefix-rename. Lands in a separate Claude Code TUI PR sequenced after the akosha rename"
  - id: REQ-009
    title: "Akosha handler `.values()` shape guard covers all 6 sites (pycharm_tools.py:391,489,586,713,762 + code_graph_tools.py:205)"
  - id: REQ-010
    title: "agent-merge-on-end SessionEnd hook is wired into akosha, crackerjack, and session-buddy `.claude/settings.json` (including copying the hook scripts to each target repo's `.claude/hooks/` and configuring the venv path) so merge cycles can complete from those worktrees"
  - id: REQ-011
    title: "No .mcp.json in any of the 4 Bodai repos references the pre-rename `akosha_*` tool names (verified by `rg` sweep across `~/Projects/{akosha,crackerjack,session-buddy,mahavishnu}/` for `*.mcp.json` matches)"
  - id: REQ-012
    title: "Regression tests assert on the wire-shape envelope via FastMCP `Client` with `InMemoryTransport`, parsing `result.content[0].text` via a local helper, and checking `assert not result.isError` separately — not the in-process return value"
  - id: REQ-013
    title: "Per-repo push governance cross-link in each target repo's CLAUDE.md, pointing to `mahavishnu/.claude/decisions/2026-10-03-mainautopush.md` and stating the repo retains user-controlled push until the user replicates the decision locally"
```

### 4.6 Recon observations

(Spec deviations discovered during recon; the plan's per-repo `rg`-sweep during Phase 1.1 / 2.x / 3.x will surface the exact line counts.)

| # | Convention says | Ground truth | Plan does |
|---|---|---|---|
| 1 | Tool names follow `<verb>_<noun>`; `<server>_<verb>_<noun>` is a redundant prefix | Akosha tools are named `akosha_<verb>_<noun>` in 32 decorator args + 14 source-doc sites | Strip the prefix in registered names AND in the 14 source-doc sites (8 in `.claude/`, 4 in `akosha/mcp/`, plus 2 docstrings). Prometheus metric names in `akosha/observability/` and `akosha/monitoring/` are NOT tool names and stay as-is. |

### 4.7 Shared root cause hypothesis (one possible cause, not the only one)

One possible shared cause is a single reindex / migration step that left the three indices in different degraded states. The hypothesis is unverified; the per-phase ICs do not depend on it. Per the akosha agent's recon, akosha does not own a local code-graph indexer — it polls session-buddy's `get_code_graph` MCP tool at `poll_interval` and writes whatever session-buddy returns into `hot_store.store_code_graph`. So the `nodes`-as-list shape in the akosha handler originated in session-buddy's `get_code_graph` (or its source indexer). The Phase 1.2 fix returns a `degraded` envelope whenever the indexer shape is wrong, which is exactly the non-deceptive contract REQ-002 demands; indexer restoration (if any) is a separate PR per §9 Decision Rule.

## 5. Implementation Phases

> **PR sequencing note:** Phase 1's full 40-edit sweep (32 decorators + 14 source-doc sites) is large for a single review/merge cycle. Recommend splitting into **PR-1a** (decorators only, mechanical — 32 edits) and **PR-1b** (source-doc / federation / allowlist / docstring sweep — ~14 edits) with same-day dependency: PR-1b ships in the same calendar day as PR-1a to preserve the invariant that the prefix-rename ships as a unit. Both land in the akosha worktree; both get reviewed by the ensemble. Per `feedback-workflow-parallel-same-repo-no-isolation.md`, both PRs run serially in the same worktree.

### Phase 1: akosha (highest priority — first bug surfaced, tool-name bug blocks all akosha search work)

**Goal:** All 32 `akosha_*` tool-name registrations and ~14 source-doc/federation/allowlist/docstring strings drop the redundant prefix. The `search_code_patterns` handler returns a structured response at all 6 shape sites. The Claude Code TUI `/akosha` picker continues to work (via the sequenced Claude Code TUI PR — REQ-008).

**Tasks:**

#### PR-1a (decorators, mechanical, ships first)

- **1.1a Tool-name registration sweep.** Walk the 11 files in §4.1 and strip the `akosha_` prefix from each `name="akosha_*"` decorator argument. 32 edits total, all mechanical. The rg pattern for verification:

  ```bash
  rg 'name="akosha_[a-z]+_"' akosha/mcp/tools/ -l
  # Expected post-rename: zero matches
  ```

#### PR-1b (source-doc / federation / allowlist / docstring sweep, ships same day)

- **1.1b Federation call** at `akosha/mcp/tools/ecosystem_skills.py:97` — change `tool_name="akosha_list_skills"` to `tool_name="list_skills"`. **Verify** that the same file's lines 103/109/115 entries for `mahavishnu_list_skills` / `session_buddy_list_skills` / `crackerjack_list_skills` are NOT changed. Note: `akosha_list_ecosystem_skills` (decorator at line 401) is a different tool from `akosha_list_skills` (decorator at `skill_tools.py:234`); the federation at line 97 calls the latter.
- **1.1c Tool-allowlist strings** in `akosha/mcp/tools/profiles.py:95-117` and `akosha/security.py` (10+ lines) — strip the prefix in each allowlist line.
- **1.1d Skill catalog** in `akosha/mcp/skills_catalog/fitness-analyzer.md` (frontmatter `allowed-tools`) and `search-insights.md:46-48` (prose) — strip the prefix in each tool reference.
- **1.1e Agent body** in `akosha/mcp/tools/agents/pattern-agent.md` — strip the prefix in each of the **14 references** (verified by `rg -c 'mcp__akosha__akosha_' akosha/mcp/tools/agents/pattern-agent.md`).
- **1.1f Module/class docstrings** — `akosha/mcp/tools/akosha_tools.py:857-858` (class docstring referencing `akosha_analyze_trends` and `akosha_get_system_metrics`), `akosha/mcp/tools/ecosystem_skills_cache.py:1` (docstring), `akosha/mcp/tools/group_registers.py` (2 docstring refs).
- **1.1g Client/server string references** in `akosha/mcp/client.py:79-80` (`"akosha_query_local_traces"`) and `akosha/mcp/server.py` (4 references) — strip the prefix.

#### PR-1c (handler fix + regression test, ships in same merge cycle as PR-1a/b)

- **1.2 Picker-filter consumer update** (REQ-008, separate Claude Code TUI PR — **not in this plan's three merge cycles**). File a Claude Code bug report for the `/akosha` picker prefix-match → server-name match change. Sequence: akosha rename lands first; the Claude Code PR lands after (same-day or next-day, depending on Anthropic's review cadence). The akosha rename is safe to ship without the picker update because the prefix-rename makes the registered name `search_code_patterns` which the picker will simply not show — operations continue via direct tool calls, just no picker entry. The picker fix restores UX parity.
- **1.3 Handler shape fix.** At all 6 sites in §4.2, replace the unguarded `.values()` with a per-site shape guard that handles dict (preferred), list (legacy), missing (empty). For the primary site at `pycharm_tools.py:391`, the fix is `nodes = graph["graph_data"].get("nodes") or {}; for node in (nodes.values() if isinstance(nodes, dict) else nodes):` — adapted per site. Return envelope: `{"status": "ok" | "degraded", "results": [...], "error": "..."}` per `wire-up-contract.md` "Returns to / updates" — the deprecation of the old traceback is the state.
- **1.4 Regression tests (REQ-007, REQ-012).** `akosha/tests/unit/test_search_code_patterns.py` (new) — assert on the wire-shape envelope via FastMCP `Client` with `InMemoryTransport`, parsing `result.content[0].text` via a local helper, and checking `assert not result.isError` separately. The test must not depend on `mahavishnu.core.worktree_providers` (wrong layering); copy/inline the helper into `akosha/tests/_support/extract_tool_payload.py`. Stub the indexer to return dict, list, and missing shapes; assert the handler returns a structured response in all 3 cases.
- **1.5 Test-fixture update.** Update 55+ test files that hard-code `akosha_*` tool names. Use the broader rg pattern (no `^name="` prefix anchor) to enumerate:

  ```bash
  rg -l 'akosha_(search|get|find|analyze|publish|store|batch|list|run|cross|discover|query|generate|correlate|detect|add|pycharm)_' akosha/tests/
  # Expected post-rename: zero matches
  ```

  (The full enumeration is provided as a code block in the plan body for cold-readers, per the random generalist's finding #18.)
- **1.6 `.mcp.json` impact check (REQ-011).** Run from the worktree:

  ```bash
  rg 'akosha_(search|get|find|analyze|publish|store|batch|list|run|cross|discover|query|generate|correlate|detect|add|pycharm)_' --glob '*.mcp.json' \
     ~/.local/state/mahavishnu/worktrees/akosha/ \
     ~/.local/state/mahavishnu/worktrees/crackerjack/ \
     ~/.local/state/mahavishnu/worktrees/session-buddy/ \
     ~/.local/state/mahavishnu/worktrees/mahavishnu/
  # Expected: zero matches
  ```

  (Note: `.mcp.json` files contain only server URLs, not tool names — verified `mahavishnu/.mcp.json`; the sweep is defensive.)
- **1.7 SessionEnd hook wiring (REQ-010).** Required sub-task. The target repos have **no `.claude/hooks/` directory**; `agent-merge-on-end.py` lives at `mahavishnu/.claude/hooks/agent-merge-on-end.py` and imports `mahavishnu.core.merge_to_main`. Wiring the SessionEnd entry without copying the script silently fails. Per-phase sub-tasks:
  - **1.7a Copy hook scripts.** `cp mahavishnu/.claude/hooks/agent-merge-on-end.py akosha/.claude/hooks/` and `cp mahavishnu/.claude/hooks/worktree-session-isolation.py akosha/.claude/hooks/` and `cp mahavishnu/.claude/hooks/_hook_io.py akosha/.claude/hooks/` (if `_hook_io.py` exists as a shared helper). Verify the scripts run from the mahavishnu venv (the `python3` path in the script must point to `mahavishnu/.venv/bin/python3`, since `mahavishnu.core.merge_to_main` is only on the mahavishnu venv's PYTHONPATH).
  - **1.7b Configure the venv path.** Edit the `python3` invocation in each copied script (e.g., `#!/usr/bin/env python3` → `#!/usr/bin/env <absolute-path-to-mahavishnu-venv-bin-python3>`) OR add the mahavishnu venv's site-packages to `PYTHONPATH` in the script's shebang line. Document the choice in a code comment.
  - **1.7c Wire the SessionEnd array.** Add both `worktree-session-isolation` and `agent-merge-on-end` entries to `akosha/.claude/settings.json` SessionEnd array, mirroring the order at `mahavishnu/.claude/settings.json:18-37`.
- **1.8 Push governance cross-link (REQ-013).** Add a one-liner to `akosha/CLAUDE.md` linking to `mahavishnu/.claude/decisions/2026-10-03-mainautopush.md` and stating that akosha retains user-controlled push until the user replicates the decision doc locally.

**Exit criteria:**
- `mcp__akosha__search_code_patterns(pattern="def test_", file_pattern="*.py")` returns without error and without the `'list' object has no attribute 'values'` traceback.
- `mcp__akosha__discover_tools()` returns the same tools under their canonical names (no `akosha_` prefix).
- `pytest akosha/tests -k "tool or search or mcp_inventory"` passes.
- `/akosha` TUI picker still returns the akosha tool list after the sequenced Claude Code TUI PR (REQ-008).
- Zero `.mcp.json` matches for the old tool names across all 4 Bodai repos (REQ-011).
- `akosha/.claude/hooks/agent-merge-on-end.py` exists and is executable.

#### Integration Contract — Phase 1.1 (tool-name + source-doc sweep, REQ-001 + REQ-011)
- **Triggered from**: akosha MCP server startup (`akosha/mcp/server.py:__main__`); every Claude Code session that loads akosha's tool list; the federation server boot that reads `ecosystem_skills.py:97`.
- **Returns to / updates**: the FastMCP tool registry on the akosha `app` instance; the `_FederationServer` config at `ecosystem_skills.py:97`; the tool-allowlist strings in `profiles.py:95-117` and `security.py`; the skill-catalog frontmatter; agent body text; class docstrings.
- **Demonstrable by**: `pytest akosha/tests/unit/test_mcp_tool_inventory.py::test_no_akosha_prefix_in_registered_names` (new test, see §6).
- **Rollback signal**: any `pytest akosha/tests/test_mcp_tool_inventory.py` failure; the inventory test enumerates expected tool names.
- **Observability added**: log line on startup `akosha_mcp_tools_registered count={N}` (where N is the new total, post-rename). Existing `akosha_search_results_total` (line 210) and `akosha_search_latency_milliseconds` (line 186) Prometheus metrics are reused for any search-handler invocation. **No new metrics are added** (the `akosha_tools_registered_total` claim from the prior plan revision was a phantom — verified by `rg "akosha_tools_registered" akosha/observability/prometheus_metrics.py` returning zero matches).
- **Fulfils**: REQ-001, REQ-011

#### Integration Contract — Phase 1.2 (picker-filter consumer update, REQ-008)
- **Triggered from**: Claude Code TUI startup; the picker filter implementation reads the registered tool name from the akosha MCP server.
- **Returns to / updates**: the Claude Code TUI picker implementation switches from prefix-match on registered name to **server-name match** (the registered server instance name is `akosha` regardless of what the tool names are).
- **Demonstrable by**: Claude Code TUI integration test asserting `/akosha` picker returns the akosha tool list post-rename. (Test lives in the Claude Code TUI codebase, not the akosha repo.)
- **Rollback signal**: any `/akosha` picker query that returns zero results when the akosha server is healthy.
- **Observability added**: TUI-level log line `picker_filter server=akosha match=server_name count={N}`.
- **Fulfils**: REQ-008

#### Integration Contract — Phase 1.3 (handler shape fix, REQ-002 + REQ-009)
- **Triggered from**: any `mcp__akosha__search_code_patterns` call (one of: akosha MCP server startup indexer probe, agent session, manual test).
- **Returns to / updates**: the deprecation of the `'list' object has no attribute 'values'` traceback — the response envelope is the state. Old: `Error: 'list' object has no attribute 'values'`. New: `{"status": "ok" | "degraded", "results": [...], "error": "..."}`. This is a state change in the wire-shape contract.
- **Demonstrable by**: `pytest akosha/tests/unit/test_search_code_patterns.py::test_dict_shape_returns_results`, `::test_list_shape_returns_degraded_envelope`, `::test_missing_shape_returns_degraded_envelope` — all three pass.
- **Rollback signal**: any `crashed_handler: pycharm_search_code_patterns` log line; the existing `akosha_errors_total` Prometheus counter (line 522) would tick on the old failure mode.
- **Observability added**: existing `akosha_search_results_total` and `akosha_search_latency_milliseconds` are reused. New log line: `akosha_search_handler shape=<dict|list|missing> status=<ok|degraded>`.
- **Fulfils**: REQ-002, REQ-009

#### Integration Contract — Phase 1.4 (regression tests, REQ-007 + REQ-012) and 1.5 (test-fixture update)
- **Triggered from**: `pytest akosha/tests/ -k "search or tool or mcp_inventory"`
- **Returns to / updates**: the test corpus; CI gate.
- **Demonstrable by**: `pytest akosha/tests/ -k "search_code_patterns or mcp_tool_inventory"` exits 0.
- **Rollback signal**: any test failure.
- **Observability added**: CI log line via the existing `crackerjack run -v` gate.
- **Fulfils**: REQ-007, REQ-012

#### Integration Contract — Phase 1.7 (SessionEnd hook wiring, REQ-010)
- **Triggered from**: Claude Code session-end event in a session operating inside `~/.local/state/mahavishnu/worktrees/akosha/`.
- **Returns to / updates**: `akosha/.claude/hooks/agent-merge-on-end.py` (new file, copied from mahavishnu); `akosha/.claude/hooks/worktree-session-isolation.py` (new file, copied from mahavishnu); `akosha/.claude/hooks/_hook_io.py` (new file if shared helper exists); `akosha/.claude/settings.json` SessionEnd array (new entries).
- **Demonstrable by**: a Claude Code session that opens and closes inside the akosha worktree fires the `agent-merge-on-end.py` hook (visible in `~/.mahavishnu/logs/mcp.log` or the new log line below).
- **Rollback signal**: log line `merge-on-end not wired for repo=akosha` (new log line).
- **Observability added**: existing session-buddy reflection store captures the merge event.
- **Fulfils**: REQ-010

#### Integration Contract — Phase 1.8 (push governance cross-link, REQ-013)
- **Triggered from**: a user reading `akosha/CLAUDE.md` (governance documentation).
- **Returns to / updates**: `akosha/CLAUDE.md` gains a one-line cross-link to `mahavishnu/.claude/decisions/2026-10-03-mainautopush.md` and a statement that akosha retains user-controlled push.
- **Demonstrable by**: `grep '2026-10-03-mainautopush' akosha/CLAUDE.md` returns ≥1 hit.
- **Rollback signal**: grep returns 0 (cross-link removed).
- **Observability added**: none (documentation-only).
- **Fulfils**: REQ-013

### Phase 2: crackerjack (second priority — `search_code` returning 0 is the most common search path)

**Goal:** `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result. `mcp__crackerjack__search_semantic(query="python", min_similarity=0.3)` returns ≥1 result.

**Tasks:**

- 2.1 Investigate the handlers at `crackerjack/mcp/tools/pycharm_tools.py:100` (`_register_search_code_tool` → wrapped function at `:103`) and `crackerjack/mcp/tools/semantic_tools.py:75` (`_register_search_semantic_tool` → wrapped function at `:77`). Identify which of the three sub-bugs applies: (a) indexer not running, (b) indexer writing to wrong path, (c) indexer writing wrong shape. Most likely the indexer schedule is gone or disabled.
- 2.2 Fix the root cause. If the indexer is gone, restore it as a thin wrapper that walks the crackerjack repo and writes to the expected index path. **If no indexer schedule exists** (the subagent's investigation concludes there's nothing to restore), add `crackerjack/docs/operations/reindex.md` with the exact reindex procedure (or a "no indexer to reindex — handler returns `degraded` envelope per §3 Non-Goals" note, whichever is accurate). This pins a concrete deliverable per the random generalist's finding #11.
- 2.3 Regression tests:
  - `crackerjack/tests/unit/mcp/tools/test_search_code.py` (new) — stubbed indexer (in-process dict-backed) returns populated results for `def test_`.
  - `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` (new) — known-embedded phrase returns ≥1 result at `min_similarity=0.3`.
- 2.4 `.mcp.json` impact check (REQ-011). Run from the worktree:

  ```bash
  rg 'crackerjack_(search|semantic)_' --glob '*.mcp.json' \
     ~/.local/state/mahavishnu/worktrees/crackerjack/ \
     ~/.local/state/mahavishnu/worktrees/mahavishnu/
  # Expected: zero matches
  ```
- 2.5 SessionEnd hook wiring (REQ-010). Same pattern as Phase 1.7: copy the hook scripts from `mahavishnu/.claude/hooks/` to `crackerjack/.claude/hooks/`, configure the venv path, wire both `worktree-session-isolation` and `agent-merge-on-end` entries to `crackerjack/.claude/settings.json` SessionEnd array.
- 2.6 Push governance cross-link (REQ-013). Add a one-liner to `crackerjack/CLAUDE.md`.

**Exit criteria:**
- `mcp__crackerjack__search_code(pattern="def test_", file_pattern="*.py")` returns ≥1 result.
- `mcp__crackerjack__search_semantic(query="python class function import", min_similarity=0.3)` returns ≥1 result.
- `pytest crackerjack/tests -k "search or pycharm_tools or semantic"` passes.
- Zero `.mcp.json` matches for old tool names (REQ-011).
- `crackerjack/.claude/hooks/agent-merge-on-end.py` exists and is executable.
- `crackerjack/docs/operations/reindex.md` exists (or the "no indexer" note is documented).
- Push governance cross-link in `crackerjack/CLAUDE.md` (REQ-013).

#### Integration Contract — Phase 2.1-2.2 (indexer/handler fix, REQ-003 + REQ-004 + REQ-007 + REQ-012)
- **Triggered from**: crackerjack MCP handler at `search_code`/`search_semantic` request time.
- **Returns to / updates**: the crackerjack search index. State destination is the on-disk or in-memory index that the handler reads.
- **Demonstrable by**: `pytest crackerjack/tests/unit/mcp/tools/test_search_code.py::test_search_code_finds_test_function` passes.
- **Rollback signal**: any `pytest crackerjack/tests -k "search"` failure; the existing `crackerjack_run` trace counter.
- **Observability added**: per-request counter on the MCP handler itself: `crackerjack_search_invoked_total{tool="search_code" | "search_semantic", status="ok" | "degraded"}`. This signal works regardless of whether the indexer is restored or not — it tracks the MCP handler invocation, not the indexer.
- **Fulfils**: REQ-003, REQ-004, REQ-007, REQ-012

#### Integration Contract — Phase 2.5 (SessionEnd hook, REQ-010) and 2.6 (push governance, REQ-013)
- Same pattern as Phase 1.7 / 1.8.
- **Fulfils**: REQ-010, REQ-013

### Phase 3: session-buddy (third priority — `quick_search` returning 0 affects all session-buddy reflection flows)

**Goal:** `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result. `mcp__session-buddy__search_by_concept(concept="python", min_score=0.3)` returns ≥1 result.

**Tasks:**

- 3.1 Investigate the wrappers at `session_buddy/tools/memory_tools.py:48,57` and the underlying `_quick_search_impl` / `_search_by_concept_impl`. Identify which of the three sub-bugs applies (per §4.3 hypothesis).
- 3.2 Fix the root cause.
- 3.3 Regression tests:
  - `session-buddy/tests/unit/test_quick_search.py` (new) — known-embedded phrase returns ≥1 result.
  - `session-buddy/tests/unit/test_search_by_concept.py` (new) — known concept returns ≥1 result.
- 3.4 `.mcp.json` impact check (REQ-011). Run from the worktree:

  ```bash
  rg 'session_buddy_(quick|search|concept)_' --glob '*.mcp.json' \
     ~/.local/state/mahavishnu/worktrees/session-buddy/ \
     ~/.local/state/mahavishnu/worktrees/mahavishnu/
  # Expected: zero matches
  ```
- 3.5 SessionEnd hook wiring (REQ-010). Same pattern as Phase 1.7: copy the hook scripts from `mahavishnu/.claude/hooks/` to `session-buddy/.claude/hooks/`, configure the venv path, wire both `worktree-session-isolation` and `agent-merge-on-end` entries to `session-buddy/.claude/settings.json` SessionEnd array.
- 3.6 Push governance cross-link (REQ-013). Add a one-liner to `session-buddy/CLAUDE.md`.

**Exit criteria:**
- `mcp__session-buddy__quick_search(query="python", min_score=0.3)` returns ≥1 result.
- `mcp__session-buddy__search_by_concept(concept="python class function", min_score=0.3)` returns ≥1 result.
- `pytest session-buddy/tests -k "search or memory or quick"` passes.
- Zero `.mcp.json` matches for old tool names (REQ-011).
- `session-buddy/.claude/hooks/agent-merge-on-end.py` exists and is executable.
- Push governance cross-link (REQ-013).

#### Integration Contract — Phase 3.1-3.2 (handler/indexer fix, REQ-005 + REQ-006 + REQ-007 + REQ-012)
- **Triggered from**: session-buddy MCP handler at `quick_search`/`search_by_concept` request time.
- **Returns to / updates**: the session-buddy reflection index.
- **Demonstrable by**: `pytest session-buddy/tests/unit/test_quick_search.py::test_quick_search_finds_stored_reflection` passes.
- **Rollback signal**: any `pytest session-buddy/tests -k "search"` failure.
- **Observability added**: per-request counter on the MCP handler: `session_buddy_search_invoked_total{tool="quick_search" | "search_by_concept", status="ok" | "degraded"}`. This signal works regardless of the indexer state.
- **Fulfils**: REQ-005, REQ-006, REQ-007, REQ-012

#### Integration Contract — Phase 3.5 / 3.6 (REQ-010, REQ-013)
- Same pattern as Phase 1.7 / 1.8.
- **Fulfils**: REQ-010, REQ-013

## 6. Required Code Changes

**Worktree convention:** Each phase runs in its own worktree. **Phase 1**: `~/.local/state/mahavishnu/worktrees/akosha/`. **Phase 2**: `~/.local/state/mahavishnu/worktrees/crackerjack/`. **Phase 3**: `~/.local/state/mahavishnu/worktrees/session-buddy/`. Merge orchestration runs from the **mahavishnu venv** (where `mahavishnu.core.merge_to_main` is on `PYTHONPATH`).

> **PR sequencing:** Phase 1 ships as three PRs in the akosha worktree (PR-1a decorators, PR-1b source-doc sweep, PR-1c handler fix + tests) — same calendar day, sequenced serially. Phase 2 and Phase 3 each ship as a single PR.

### Phase 1: akosha (worktree: `~/.local/state/mahavishnu/worktrees/akosha/`)

#### PR-1a (decorators, mechanical)
- [ ] `akosha/mcp/tools/pycharm_tools.py` — strip 5 decorator prefixes
- [ ] `akosha/mcp/tools/akosha_tools.py` — strip 11 decorator prefixes
- [ ] `akosha/mcp/tools/skill_tools.py` — strip 2 decorator prefixes
- [ ] `akosha/mcp/tools/agents_tools.py` — strip 2 decorator prefixes
- [ ] `akosha/mcp/tools/code_graph_tools.py` — strip 4 decorator prefixes
- [ ] `akosha/mcp/tools/cross_repo_tools.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/ecosystem_skills.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/eventbridge_tools.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/session_buddy_tools.py` — strip 2 decorator prefixes
- [ ] `akosha/mcp/tools/otel_tools.py` — strip 1 decorator prefix
- [ ] `akosha/mcp/tools/fitness_tools.py` — strip 2 decorator prefixes

#### PR-1b (source-doc sweep)
- [ ] `akosha/mcp/tools/ecosystem_skills.py:97` — federation call fix
- [ ] `akosha/mcp/tools/profiles.py:95-117` — allowlist strings
- [ ] `akosha/security.py` — 10+ allowlist lines (exact line range enumerated during sweep)
- [ ] `akosha/mcp/client.py:79-80` — client string
- [ ] `akosha/mcp/server.py` — 4 references (allowlist/string refs)
- [ ] `akosha/mcp/tools/agents_tools.py:174` — `mcp__akosha__akosha_run_fitness_analysis` reference
- [ ] `akosha/mcp/tools/skill_tools.py:120-125` — SkillMetadata `tool_refs`
- [ ] `akosha/mcp/tools/akosha_tools.py:857-858` — class docstring
- [ ] `akosha/mcp/tools/ecosystem_skills_cache.py` — docstring
- [ ] `akosha/mcp/tools/group_registers.py` — 2 docstring refs
- [ ] `akosha/mcp/skills_catalog/fitness-analyzer.md` (frontmatter)
- [ ] `akosha/mcp/skills_catalog/search-insights.md:46-48` (prose)
- [ ] `akosha/mcp/tools/agents/pattern-agent.md` — **14 references**

#### PR-1c (handler fix + tests + hooks + cross-link)
- [ ] `akosha/mcp/tools/pycharm_tools.py:391,489,586,713,762` — 5 shape guards
- [ ] `akosha/mcp/tools/code_graph_tools.py:205` — 1 shape guard
- [ ] `akosha/mcp/tools/akosha_tools.py:857-858` — class docstring (if not in PR-1b)
- [ ] `akosha/.claude/hooks/agent-merge-on-end.py` — copy from mahavishnu + configure venv path
- [ ] `akosha/.claude/hooks/worktree-session-isolation.py` — copy from mahavishnu
- [ ] `akosha/.claude/hooks/_hook_io.py` — copy from mahavishnu (if shared helper exists)
- [ ] `akosha/.claude/settings.json` — add SessionEnd array entries (mirroring `mahavishnu/.claude/settings.json:18-37`)
- [ ] `akosha/CLAUDE.md` — push governance cross-link (REQ-013)
- [ ] **New**: `akosha/tests/unit/test_search_code_patterns.py` — 3 shape-stubs + wire-envelope assertion (REQ-007, REQ-012)
- [ ] **New**: `akosha/tests/_support/extract_tool_payload.py` — local helper (copy of `mahavishnu.core.worktree_providers.session_buddy._extract_tool_payload` or similar)
- [ ] **New**: `akosha/tests/unit/test_mcp_tool_inventory.py` — `test_no_akosha_prefix_in_registered_names` (REQ-001 demonstrable)

#### PR-1b test-fixture update (rolled into PR-1b)
- [ ] 55+ test files updated via the broader rg pattern in §5.1.5. Enumerated by `rg -l 'akosha_(search|get|find|analyze|publish|store|batch|list|run|cross|discover|query|generate|correlate|detect|add|pycharm)_' akosha/tests/`. High-count files:
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
  - `akosha/tests/test_skills_signer.py`
  - `akosha/tests/test_pycharm_tools_coverage.py`
  - `akosha/tests/integration/test_mcp_integration.py`
  - `akosha/tests/unit/test_mcp_tool_inventory.py`
  - `akosha/tests/unit/test_mcp_akosha_tools.py`
  - `akosha/tests/unit/test_mcp_akosha_tools_runtime.py`
  - `akosha/tests/unit/test_cross_repo_capability_search.py`
  - Plus any others surfaced by the broader rg pattern
- [ ] `akosha/tests/fixtures/full/tool_names.json` — 6 names
- [ ] `akosha/tests/fixtures/standard/tool_names.json` — 2 names
- [ ] `akosha/tests/fixtures/minimal/tool_names.json` — verify and update

### Phase 2: crackerjack (worktree: `~/.local/state/mahavishnu/worktrees/crackerjack/`)

- [ ] `crackerjack/mcp/tools/pycharm_tools.py:100` — `_register_search_code_tool` investigation + fix
- [ ] `crackerjack/mcp/tools/semantic_tools.py:75` — `_register_search_semantic_tool` investigation + fix
- [ ] Indexer restoration (or `crackerjack/docs/operations/reindex.md` per §5.2)
- [ ] `crackerjack/.claude/hooks/agent-merge-on-end.py` — copy from mahavishnu + configure venv path
- [ ] `crackerjack/.claude/hooks/worktree-session-isolation.py` — copy from mahavishnu
- [ ] `crackerjack/.claude/hooks/_hook_io.py` — copy from mahavishnu (if shared helper exists)
- [ ] `crackerjack/.claude/settings.json` — add SessionEnd array entries (crackerjack has no `settings.json` yet; create one)
- [ ] `crackerjack/CLAUDE.md` — push governance cross-link (REQ-013)
- [ ] **New**: `crackerjack/docs/operations/reindex.md` — reindex procedure (or "no indexer" note)
- [ ] **New**: `crackerjack/tests/unit/mcp/tools/test_search_code.py` — regression test (REQ-007, REQ-012)
- [ ] **New**: `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` — regression test (REQ-007, REQ-012)

### Phase 3: session-buddy (worktree: `~/.local/state/mahavishnu/worktrees/session-buddy/`)

- [ ] `session_buddy/tools/memory_tools.py:48,57` — wrapper fixes
- [ ] Underlying `_quick_search_impl` and `_search_by_concept_impl` (subagent traces the import source)
- [ ] Indexer / reflection store fix (path TBD)
- [ ] `session-buddy/.claude/hooks/agent-merge-on-end.py` — copy from mahavishnu + configure venv path
- [ ] `session-buddy/.claude/hooks/worktree-session-isolation.py` — copy from mahavishnu
- [ ] `session-buddy/.claude/hooks/_hook_io.py` — copy from mahavishnu (if shared helper exists)
- [ ] `session-buddy/.claude/settings.json` — add SessionEnd array entries (session-buddy has no SessionEnd array yet; create the array)
- [ ] `session-buddy/CLAUDE.md` — push governance cross-link (REQ-013)
- [ ] **New**: `session-buddy/tests/unit/test_quick_search.py` — regression test (REQ-007, REQ-012)
- [ ] **New**: `session-buddy/tests/unit/test_search_by_concept.py` — regression test (REQ-007, REQ-012)

## 7. Validation Matrix

| Probe | Tool | Expected result | Evidence location |
|---|---|---|---|
| Akosha tool-name fix | `pytest akosha/tests/unit/test_mcp_tool_inventory.py::test_no_akosha_prefix_in_registered_names` | exits 0 | `akosha/tests/unit/test_mcp_tool_inventory.py` (REQ-001) |
| Akosha source-doc sweep | `rg 'akosha_[a-z]+_' akosha/akosha/ akosha/tests/` | zero non-comment matches in production, only fixture/intentional refs in tests | shell |
| Akosha handler shape fix (all 6 sites) | `pytest akosha/tests/unit/test_search_code_patterns.py` | exits 0; all 3 shape stubs return structured response | `akosha/tests/unit/test_search_code_patterns.py` (REQ-002, REQ-009) |
| Akosha wire-envelope regression | `pytest akosha/tests/unit/test_search_code_patterns.py::test_wire_envelope_via_extract_tool_payload` (asserts `assert not result.isError` AND parses `result.content[0].text`) | exits 0 | `akosha/tests/unit/test_search_code_patterns.py` (REQ-012) |
| Akosha .mcp.json impact | `rg 'akosha_(search\|get\|find\|analyze\|publish\|store\|batch\|list\|run\|cross\|discover\|query\|generate\|correlate\|detect\|add\|pycharm)_' --glob '*.mcp.json' ~/.local/state/mahavishnu/worktrees/{akosha,crackerjack,session-buddy,mahavishnu}/` | zero matches | shell (REQ-011) |
| Akosha picker (TUI consumer) | `/akosha` TUI picker | returns the akosha tool list post-rename (after sequenced Claude Code TUI PR) | Claude Code TUI test (REQ-008) |
| Crackerjack code search | `pytest crackerjack/tests/unit/mcp/tools/test_search_code.py::test_search_code_finds_test_function` | exits 0 | `crackerjack/tests/unit/mcp/tools/test_search_code.py` (REQ-003) |
| Crackerjack semantic search | `pytest crackerjack/tests/unit/mcp/tools/test_search_semantic.py::test_search_semantic_finds_phrase` | exits 0 | `crackerjack/tests/unit/mcp/tools/test_search_semantic.py` (REQ-004) |
| Crackerjack .mcp.json impact | `rg 'crackerjack_(search\|semantic)_' --glob '*.mcp.json' ~/.local/state/mahavishnu/worktrees/{crackerjack,mahavishnu}/` | zero matches | shell (REQ-011) |
| Session-buddy quick_search | `pytest session-buddy/tests/unit/test_quick_search.py::test_quick_search_finds_stored_reflection` | exits 0 | `session-buddy/tests/unit/test_quick_search.py` (REQ-005) |
| Session-buddy search_by_concept | `pytest session-buddy/tests/unit/test_search_by_concept.py::test_search_by_concept_finds_concept` | exits 0 | `session-buddy/tests/unit/test_search_by_concept.py` (REQ-006) |
| Session-buddy .mcp.json impact | `rg 'session_buddy_(quick\|search\|concept)_' --glob '*.mcp.json' ~/.local/state/mahavishnu/worktrees/{session-buddy,mahavishnu}/` | zero matches | shell (REQ-011) |
| Akosha push governance cross-link | `rg '2026-10-03-mainautopush' akosha/CLAUDE.md` | ≥1 hit | shell (REQ-013) |
| Crackerjack push governance cross-link | `rg '2026-10-03-mainautopush' crackerjack/CLAUDE.md` | ≥1 hit | shell (REQ-013) |
| Session-buddy push governance cross-link | `rg '2026-10-03-mainautopush' session-buddy/CLAUDE.md` | ≥1 hit | shell (REQ-013) |
| Akosha SessionEnd hook | Claude Code session-end event in akosha worktree | fires `agent-merge-on-end.py` | `akosha/.claude/settings.json` + `akosha/.claude/hooks/` (REQ-010) |
| Liveness unchanged | `mcp__akosha__get_liveness()`; crackerjack `/health`; session-buddy `/health` | all 200 | pre/post probe comparison |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tool-name rename breaks downstream callers (any code that does `app.get_tool("akosha_search_code_patterns")` or imports from a federation config) | Medium | The `rg` sweeps in §5.1.5 / §5.2.4 / §5.3.4 cover known call sites. The federation call at `ecosystem_skills.py:97` is the most consequential — handled explicitly per Phase 1.1b. |
| Picker-filter side-effect breaks `/akosha` tool list in TUI | Medium | REQ-008 sequenced Claude Code TUI PR. The akosha rename can ship without the picker update; operations continue via direct tool calls. Claude Code bug filed in parallel. |
| Indexer restoration is more invasive than expected (full cron job rebuild) | Medium | Defer to a followup if it's > 1 day of work. The Phase 2 fix can stop at "the handler returns a typed `degraded` envelope when the indexer has not produced any rows" — that satisfies REQ-003/004 at the *non-deceptive* level without rebuilding the indexer. Per §9 Decision Rule: split out the indexer work as a separate PR. |
| `result.content[0].text` envelope regression — handler test passes in-process but wire shape leaks traceback string | Low | Regression tests assert via `_extract_tool_payload` and `assert not result.isError` (REQ-012). |
| One repo's fix exposes a different bug in the indexer | Low | Each phase is in its own worktree; the failed indexer can be punted without blocking the other phases. |
| `mahavishnu.core.merge_to_main` not on PYTHONPATH in target repos | High (architectural) | Invoke the orchestrator from the **mahavishnu venv** (`python -m mahavishnu.core.merge_to_main --branch <branch>`), or route the merge through `mcp__mahavishnu__pool_route_execute` so the orchestrator process owns the import. Documented in the plan intro. |
| `agent-merge-on-end` SessionEnd hook not wired in target repos (hook-script copy + venv path) | High (architectural) | Per-phase SessionEnd wiring is a required sub-task (Phase 1.7, 2.5, 3.5) with the hook-script copy step. Without it, the auto-merge does not fire from sessions in those worktrees. |
| `git push origin main` auto-fired on the 3 target repos (mahavishnu's auto-push exception is mahavishnu-scoped) | Low | Each target repo retains user-controlled push until the user replicates `2026-10-03-mainautopush.md` locally. REQ-013 cross-link in each repo's CLAUDE.md makes this explicit. |
| The semantic index genuinely has nothing to index (crackerjack/session-buddy's source code was never embedded) | Medium | If the fix is "the indexer was never turned on," the plan delivers a degraded-envelope result for this PR and a followup reindex PR (or a documented `crackerjack/docs/operations/reindex.md` procedure) afterwards. Acceptable scope cut per §9. |
| Shared root cause hypothesis is wrong (the 3 broken surfaces have different actual causes) | Medium | Hypothesis is one possible cause, not the only one. Per-phase ICs do not depend on it. Each phase is independently testable. |

## 9. Decision Rule

This plan is "done enough" when:

- All 3 phases have shipped as 3 separate merge cycles, each with its own integration contracts fulfilled.
- The 16 validation probes in §7 all pass when run against the released versions.
- The picker-filter consumer update (REQ-008) has shipped in the sequenced Claude Code TUI PR.
- The per-repo SessionEnd hooks (Phase 1.7, 2.5, 3.5) are wired AND the hook scripts are copied to each target repo's `.claude/hooks/`.
- The per-repo push governance cross-links (Phase 1.8, 2.6, 3.6) are in each target repo's CLAUDE.md.
- No new MCP tools were added.
- No `/health` route was modified.
- The followup plan for health-check-enrichment has been written (see §10 below).

**Order of operations (mandatory per phase, to be documented in the worker's brief):**

1. Create worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`
2. Wire the SessionEnd hooks (Phase 1.7 / 2.5 / 3.5) — copy scripts, configure venv path, add SessionEnd array entries
3. Run the fix
4. Run the regression tests
5. Run the validation probes (especially `.mcp.json` impact check, REQ-011)
6. Squash-merge to local `main` from the **mahavishnu venv** (where `mahavishnu.core.merge_to_main` is on `PYTHONPATH`)
7. Hand the push back to the user (per `feedback-bodai-push-is-user-controlled.md`)

**If the indexer-restoration work in Phase 2 or Phase 3 exceeds 1 day of effort, split out the indexer work as a separate PR** and leave the handler-fix-only in this plan. A handler that returns `degraded` honestly is better than a handler that returns `[]` deceptively. Per `feedback-mcp-common-version-bump-is-user.md`, the user owns the version bump; no version bump is in scope for this plan.

**If parallel execution is preferred over sequential,** dispatch the 3 phases as 3 sub-agents via `mcp__mahavishnu__pool_route_execute` (ad-hoc) or `mcp__mahavishnu__trigger_workflow` (durable), each in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`. Per `feedback-workflow-parallel-same-repo-no-isolation.md`, each sub-agent must use `git add <scope-only>` (no `git add -A`). The merge orchestration runs from the **mahavishnu venv**; the 3 target worktrees do not have it. Per `feedback-worktree-update-ref-drops-parallel-commits.md`, the worktree-branch ref must be fast-forward of `main` before any `git update-ref`; verify per sub-agent before merge.

**Phase 1 PR sequencing:** Ship as PR-1a (decorators, mechanical — 32 edits) + PR-1b (source-doc sweep, ~14 edits) + PR-1c (handler fix + tests + hooks + cross-link) on the same calendar day, serially in the same worktree. PR-1a and PR-1b must land together so the prefix-rename ships as a unit; PR-1c is independent.

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
- `docs/schemas/topic-vocabulary-v1.md` — topic vocabulary.
- `~/.claude/CLAUDE.md` — worktree location convention (`~/.local/state/mahavishnu/worktrees/<basename>/`).
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/mcp-surface-health-illusion.md` — why this fix matters.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/bodai-tool-naming-gap-2026-09-09.md` — picker-filter prefix-match convention (resolution: REQ-008, sequenced Claude Code TUI PR).
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/fastmcp-call-tool-returns-calltoolresult.md` — wire-envelope `result.content[0].text` parsing (REQ-012).
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-workflow-parallel-same-repo-no-isolation.md` — why each phase gets its own worktree.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-worktree-update-ref-drops-parallel-commits.md` — ref-safety rules for parallel worktrees.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md` — no push without explicit approval.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-mcp-common-version-bump-is-user.md` — no version bump from agents.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-crackerjack-publish-stage-is-user.md` — no `crackerjack -p` from agents.
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/bodai-pytest-binary-cwd.md` — run pytest via `<repo>/.venv/bin/pytest`, not bare `pytest`.
