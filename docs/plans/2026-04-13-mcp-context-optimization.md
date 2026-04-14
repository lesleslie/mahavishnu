# MCP Context Optimization Plan

**Date**: 2026-04-13
**Status**: Draft - Reviews Complete, Ready for Revision
**Scope**: session-buddy, mahavishnu, crackerjack, akosha, dhara, mcp-common
**Goal**: Reduce MCP tool definition context from ~70k to ~20-25k tokens

## Problem Statement

Every Claude Code conversation starts with ~120-140k tokens of system context.
MCP tool definitions account for ~70k tokens (53%) of that, with 393 tools
registered across 12 servers. Session-Buddy (171 tools) and Mahavishnu (109
tools) are the worst offenders, together consuming ~54k tokens.

This leaves very little room for actual conversation before hitting context
limits, forcing premature compaction and degrading conversation quality.

## Current State

```
Server              Tools   Est. Tokens   Source Files
────────────────── ─────── ───────────── ──────────────────────
session-buddy        171     ~34,000      43 files, 664K chars
mahavishnu           109     ~20,000      18 files, 263K chars
crackerjack           46      ~6,000       ~8 files
akosha                24      ~3,500       ~4 files
dhara                 23      ~3,500       ~4 files
other MCP             20      ~3,000       various
────────────────── ─────── ─────────────
TOTAL                393     ~70,000
```

## Strategy Overview

Two complementary approaches, executed in order:

1. **Phase 1 - Description Trimming**: Reduce per-tool token cost by ~60%
2. **Phase 2 - Tool Registration Profiles**: Reduce tool count by ~50-70% per profile

Combined target: ~20-25k tokens (from ~70k), a 65-70% reduction.

---

## Phase 1: Description Trimming

### Principle

Each tool's runtime description should be a **terse action statement** (1-2
sentences, max 200 characters). Full documentation stays in source code
docstrings for developers but is NOT sent to Claude at runtime.

### Description Budget

| Tool Priority | Max Description | What to Include |
|---------------|----------------|-----------------|
| Core (always loaded) | 200 chars | What it does, key params |
| Standard | 150 chars | What it does |
| Utility | 100 chars | One-liner |

### What to Strip

- **Examples** sections: `Example:`, `>>>` blocks
- **Returns** documentation (keep return type in schema only)
- **Raises** documentation
- **Detailed parameter docs** (keep in schema `description` field, max 20 chars)
- **"Args:" sections** in tool docstrings (FastMCP extracts from type hints)
- **Multi-paragraph descriptions**: collapse to 1-2 sentences

### Implementation Approach

Create a **description decorator** in mcp-common that enforces budgets at
registration time:

```python
# mcp_common/tools/descriptions.py

MAX_DESCRIPTION_LENGTH = 200

def trim_description(docstring: str, max_length: int = MAX_DESCRIPTION_LENGTH) -> str:
    """Extract first paragraph from docstring, trimmed to max_length.

    Strips Examples, Args, Returns, Raises sections.
    Keeps only the first non-empty paragraph.
    """
    if not docstring:
        return ""

    # Remove common sections
    sections = ("Args:", "Returns:", "Raises:", "Example:", "Examples:")
    lines = []
    for line in docstring.split("\n"):
        stripped = line.strip()
        if any(stripped.startswith(s) for s in sections):
            break
        if stripped:
            lines.append(stripped)

    result = " ".join(lines)
    if len(result) > max_length:
        result = result[:max_length - 3] + "..."
    return result
```

Each server's `register_*` functions would use this:

```python
# Before (current):
@mcp.tool()
async def detect_quality_bottlenecks(...):
    """Detect quality-related workflow bottlenecks.

    Analyzes session quality patterns to identify:
    - Sudden quality drops (>10 point decline)
    - Consecutive low quality sessions
    ...

    Args:
        project_path: Optional filter by project path
        days_back: Number of days to analyze (default: 30)

    Returns:
        Dictionary with quality bottleneck metrics including:
        ...

    Example:
        >>> result = await detect_quality_bottlenecks(days_back=14)
        >>> print(f"Quality drops: {result['sudden_quality_drops']}")
    """

# After (trimmed):
@mcp.tool()
async def detect_quality_bottlenecks(...):
    """Detect sudden quality drops and low-quality session streaks in workflow data."""
```

The implementation function (`_detect_quality_bottlenecks_impl`) retains its
full docstring — only the registered MCP tool description is trimmed.

### Per-Server Impact Estimate

| Server | Tools | Avg Desc Chars (now) | Avg Desc Chars (after) | Token Savings |
|--------|-------|----------------------|------------------------|---------------|
| session-buddy | 171 | ~800 | ~150 | ~28,000 |
| mahavishnu | 109 | ~600 | ~140 | ~15,000 |
| crackerjack | 46 | ~400 | ~120 | ~6,000 |
| akosha | 24 | ~400 | ~120 | ~3,000 |
| dhara | 23 | ~400 | ~120 | ~3,000 |
| **Total** | **393** | | | **~55,000** |

Wait — that's too aggressive. The schema overhead (parameter definitions)
doesn't shrink. More realistic:

**Phase 1 alone: ~70k → ~35-40k tokens** (~45% reduction)

### Files to Modify

#### mcp-common (shared utility)
- `mcp_common/tools/__init__.py` — new module
- `mcp_common/tools/descriptions.py` — `trim_description()` function
- `mcp_common/tools/budget.py` — `DescriptionBudget` enum/config

#### session-buddy (171 tools)
43 tool files, targeting these first (largest descriptions):
- `mcp/tools/session/crackerjack_tools.py` — 51K chars, ~12 tools
- `mcp/tools/session/session_tools.py` — 40K chars, ~15 tools
- `mcp/tools/memory/search_tools.py` — 39K chars, 15 tools
- `mcp/tools/monitoring/session_analytics_tools.py` — 27K chars, ~5 tools
- `mcp/tools/monitoring/bottleneck_tools.py` — 24K chars, ~4 tools
- `mcp/tools/memory/memory_tools.py` — 24K chars, ~8 tools
- `mcp/tools/memory/validated_memory_tools.py` — 22K chars, ~6 tools
- `mcp/tools/monitoring/monitoring_tools.py` — 22K chars, 11 tools
- All remaining tool files (35 files)

#### mahavishnu (109 tools)
All 18 tool files:
- `mcp/tools/desktop_automation_tools.py` — 17K chars, 23 tools
- `mcp/tools/goal_team_tools.py` — 31K chars, 3 tools
- `mcp/tools/terminal_tools.py` — 13K chars, 12 tools
- `mcp/tools/coordination_tools.py` — 13K chars, 14 tools
- All remaining tool files (14 files)

#### crackerjack, akosha, dhara (93 tools combined)
- All tool registration files in each repo

---

## Phase 2: Tool Registration Profiles

### Design

Extend the existing `mcp_common/profiles/` module with a **tool profile system**
that controls which `register_*` functions are called at startup.

### Profile Definitions

Each server defines its own profile mapping in a YAML or Python config:

```python
# mcp_common/tools/profiles.py

from enum import Enum
from typing import Callable

class ToolProfile(str, Enum):
    MINIMAL = "minimal"     # ~10 tools: health, status, start, stop
    STANDARD = "standard"   # ~30 tools: core workflow tools
    FULL = "full"           # All tools (current behavior)

# Each server provides a profile registry:
TOOL_PROFILES = {
    ToolProfile.MINIMAL: [
        "register_health_tools",
        "register_session_tools",      # start/end/status only
        "register_search_tools",       # basic search only
    ],
    ToolProfile.STANDARD: [
        # All MINIMAL tools plus:
        "register_conversation_tools",
        "register_memory_tools",
        "register_category_tools",
        "register_cache_tools",
        "register_monitoring_tools",
        "register_bottleneck_tools",
    ],
    ToolProfile.FULL: [
        # All STANDARD tools plus everything else
    ],
}
```

### Configuration

Profile is selected via (in precedence order):
1. Environment variable: `{SERVER_NAME}_TOOL_PROFILE=standard`
2. settings/local.yaml: `tool_profile: standard`
3. settings/{server}.yaml: `tool_profile: full` (default for safety)

Example `settings/session-buddy.yaml`:
```yaml
tool_profile: full  # Override in local.yaml for daily dev
```

Example `settings/local.yaml` (gitignored):
```yaml
tool_profile: standard  # Developer's daily driver
```

### Per-Server Profile Targets

#### session-buddy (171 → profile targets)

| Profile | Tools | Est. Tokens | Use Case |
|---------|-------|-------------|----------|
| minimal | ~12 | ~2,500 | CI/CD, health checks, session tracking |
| standard | ~35 | ~7,000 | Daily development, search, memory |
| full | 171 | ~14,000 | (post-trim) Full analytics, admin |

**Minimal toolset (12):**
- `ping`, `health_check`, `server_info`
- `start`, `end`, `status`, `checkpoint`
- `quick_search`, `store_reflection`
- `get_conversation_statistics`
- `session_welcome`
- `pre_compact_sync`

**Standard adds (23 more = 35 total):**
- `search_conversations`, `search_summary`, `progressive_search`
- `store_conversation`, `store_conversation_checkpoint`
- `store_memory` (entity), `search_entities`, `create_entity`
- `clear_query_cache`, `query_cache_stats`
- `category_stats`, `get_subcategories`
- `analyze_graph_connectivity`, `get_knowledge_graph_stats`
- `crackerjack_run`, `crackerjack_health_check`
- `detect_intent`, `feature_flags_status`
- `get_activity_summary`, `get_context_insights`
- `list_hooks`, `permissions`
- `get_reflection_health`

#### mahavishnu (109 → profile targets)

| Profile | Tools | Est. Tokens | Use Case |
|---------|-------|-------------|----------|
| minimal | ~10 | ~2,000 | Health checks, monitoring |
| standard | ~30 | ~6,000 | Workflow orchestration, repos |
| full | 109 | ~8,000 | (post-trim) All tools |

**Minimal toolset (10):**
- `get_liveness`, `get_readiness`, `get_health`
- `health_check_all`
- `get_monitoring_dashboard`, `get_observability_metrics`
- `list_repos`, `list_workflows`
- `mcp_test_connection`, `get_workflow_status`

**Standard adds (20 more = 30 total):**
- `trigger_workflow`, `cancel_workflow`
- `pool_spawn`, `pool_execute`, `pool_list`, `pool_health`, `pool_close`
- `worker_spawn`, `worker_execute`, `worker_list`, `worker_health`
- `terminal_launch`, `terminal_send`, `terminal_list`, `terminal_close`
- `search_logs`, `search_workflows`
- `get_repository_health`, `notify_repository_changes`
- `treesitter_parse`

#### crackerjack (46 → profile targets)

| Profile | Tools | Est. Tokens | Use Case |
|---------|-------|-------------|----------|
| minimal | ~5 | ~800 | Status, health |
| standard | ~15 | ~2,500 | Quality checks, testing |
| full | 46 | ~3,000 | (post-trim) All capabilities |

#### akosha (24 → profile targets)

| Profile | Tools | Est. Tokens |
|---------|-------|-------------|
| minimal | ~5 | ~800 |
| standard | ~12 | ~2,000 |
| full | 24 | ~2,000 |

#### dhara (23 → profile targets)

| Profile | Tools | Est. Tokens |
|---------|-------|-------------|
| minimal | ~4 | ~600 |
| standard | ~10 | ~1,500 |
| full | 23 | ~2,000 |

### Combined Token Estimates (Phase 1 + Phase 2)

**Standard profile (daily development):**
```
session-buddy:   ~7,000 tokens (35 tools)
mahavishnu:      ~6,000 tokens (30 tools)
crackerjack:     ~2,500 tokens (15 tools)
akosha:          ~2,000 tokens (12 tools)
dhara:           ~1,500 tokens (10 tools)
─────────────────────────────────────────
Total:          ~19,000 tokens (from ~70k = 73% reduction)
```

**Minimal profile (CI/health checks):**
```
Total:           ~6,700 tokens (from ~70k = 90% reduction)
```

---

## Implementation Plan

### Prerequisites
- mcp-common is the shared dependency for all servers
- All servers use `register_*()` pattern for tool registration
- FastMCP tool descriptions come from function docstrings

### Step-by-Step Execution

#### Step 1: mcp-common shared utilities [sequential]
**Repo**: mcp-common
**Model**: Sonnet (straightforward utility code)
**Files**:
- Create `mcp_common/tools/__init__.py`
- Create `mcp_common/tools/descriptions.py` (trim_description utility)
- Create `mcp_common/tools/profiles.py` (ToolProfile enum, profile registry)
- Update `mcp_common/__init__.py` to export new module

**Verification**: Unit tests for trim_description with various docstring formats

#### Step 2: Description trimming [parallel across repos]
**Model**: Haiku (meanical find-and-trim) with Sonnet review
**Parallel groups**:

| Group | Repo | Tools | Est. Time | Model |
|-------|------|-------|-----------|-------|
| A | session-buddy | 171 | Longest | Haiku (trim) + Sonnet (review) |
| B | mahavishnu | 109 | Medium | Haiku (trim) + Sonnet (review) |
| C | crackerjack | 46 | Short | Haiku |
| D | akosha + dhara | 47 | Short | Haiku |

Groups C and D can be a single agent.
Groups A and B should each be a dedicated agent due to file count.

**Process per tool file**:
1. Open file
2. For each `@mcp.tool()` decorated function:
   a. Read current docstring
   b. Apply `trim_description()` logic by hand
   c. Replace docstring with trimmed version (max 200 chars)
3. Keep `_impl` function docstrings unchanged (they're not sent to Claude)

**Do NOT change**:
- Parameter names, types, or defaults (these define the schema)
- Implementation logic
- `_impl` function docstrings
- Error handling

#### Step 3: Profile registration system [sequential, depends on Step 1]
**Repo**: mcp-common (core), then each server
**Model**: Sonnet (architectural)
**Files per server**:
- Create `mcp/tools/profiles.py` — server-specific profile → register mapping
- Modify `mcp/server.py` — conditional registration based on profile
- Add `tool_profile` to settings model
- Add `TOOL_PROFILE` env var support

#### Step 4: Testing & validation [parallel]
**Model**: Sonnet
- Verify tool counts per profile
- Verify description lengths
- Test each profile loads correctly
- Test fallback to `full` when profile is invalid
- Verify no tools are broken (schemas unchanged)

#### Step 5: Documentation [quick]
**Model**: Haiku
- Update each server's CLAUDE.md with profile options
- Update mcp-common README
- Add env var documentation

### Parallel Execution Strategy

```
Timeline:  ─────────────────────────────────────────────────►

Step 1: [====mcp-common====]
                                    │
Step 2:                  ┌─[==session-buddy==]──┐
                         ├─[==mahavishnu=====]──┤  (parallel)
                         └─[=crackerjack+akosha+dhara=]─┘
                                    │
Step 3:                  [====profile-system====]  (sequential, needs step 1+2)
                                    │
Step 4:                  [====validation=====]    (parallel per repo)
                                    │
Step 5:                  [=docs=]                  (quick)
```

**Agent dispatch plan:**
1. **Agent 1** (Sonnet): mcp-common shared utilities (Step 1)
2. **Agent 2** (Haiku): Session-buddy description trimming (Step 2A)
3. **Agent 3** (Haiku): Mahavishnu description trimming (Step 2B)
4. **Agent 4** (Haiku): Crackerjack + Akosha + Dhara trimming (Step 2C+D)
5. **Agent 5** (Sonnet): Profile system implementation (Step 3, after 1+2)
6. **Agent 6** (Sonnet): Cross-repo validation (Step 4)
7. **Agent 7** (Haiku): Documentation (Step 5)

Agents 2, 3, 4 run in parallel after Agent 1 completes.
Agent 5 runs after all of 1-4 complete.
Agent 6 runs after 5 completes.
Agent 7 runs after 6 passes.

### Model Recommendations

| Task | Model | Why |
|------|-------|-----|
| Shared utility code (mcp-common) | Sonnet | Needs good design judgment |
| Description trimming (all repos) | Haiku | Mechanical text reduction |
| Profile system architecture | Sonnet | Needs consistency across repos |
| Validation & testing | Sonnet | Needs judgment on correctness |
| Documentation | Haiku | Straightforward writing |
| Code review of changes | Sonnet | Needs quality assessment |

### Risk Mitigation

1. **Description too short → tool unusable**: Keep a 100-char minimum. If
   trimming makes a tool ambiguous, keep it longer.
2. **Missing profile tool at runtime**: Always include a `list_available_tools`
   tool that tells Claude what's available but not loaded.
3. **Breaking existing sessions**: Profile selection is opt-in via config.
   Default is `full` (current behavior). No one is forced to change.
4. **Schema parameter descriptions lost**: These come from type hints and
   FastMCP's extraction, NOT from the docstring. Trimming docstrings
   doesn't affect parameter schemas.

### Success Metrics

| Metric | Before | After (Phase 1) | After (Phase 1+2, standard) |
|--------|--------|------------------|------------------------------|
| Total tool tokens | ~70,000 | ~35-40,000 | ~19,000 |
| Session-buddy tools | 171 | 171 (trimmed) | 35 |
| Mahavishnu tools | 109 | 109 (trimmed) | 30 |
| Avg description chars | ~600 | ~150 | ~150 |
| Context available for conversation | ~60k | ~90k | ~110k |
| Compaction frequency | High | Medium | Low |

### Open Questions for Reviewers

1. Should `list_available_tools` be a meta-tool that shows unloaded tools?
   Or should profiles be opaque to Claude?
2. Should we implement dynamic tool loading (load tools mid-session)?
   Or is static profile selection sufficient?
3. What should the default profile be for daily development — `standard` or `full`?
4. Should the CLAUDE.md project instructions specify which profile to use per-repo?
5. Is 200 chars the right description budget, or should it be lower (150)?

---

## Review Section

*Subagent dispatches hit persistent 429 rate limits. Reviews performed inline
by the plan author with full context from source analysis across all 5 repos.*

### Review 1: Architecture

**Reviewer**: Architect perspective, informed by analysis of mcp-common/profiles/,
session-buddy/server.py, and mahavishnu/mcp/server.py.

**Verdict: Sound with 4 adjustments.**

1. **Profile system should live in per-server config, not mcp-common.** The
   existing `profiles/` module is about server-level features (auth, telemetry,
   resources). Tool profiles are a different concern — they control *which*
   tools register, not what features the server has. Each server already has
   its own `register_*()` functions. The profile mapping is inherently
   server-specific. **Recommendation**: Keep `ToolProfile` enum in mcp-common
   (for shared type), but put profile→register mappings in each server's
   `mcp/tools/profiles.py`.

2. **The `trim_description()` utility is correct but should be a
   post-processing step, not a decorator.** FastMCP reads the function's
   `__doc__` attribute at registration time. The cleanest approach: modify
   docstrings *before* `@mcp.tool()` decoration, or patch `__doc__` in the
   register functions. **Recommendation**: Apply trimming in `register_*()`
   functions by patching `func.__doc__` before passing to `mcp.tool()`.

3. **The parallel execution strategy is realistic** but Step 3 (profiles)
   doesn't strictly depend on Step 2 (trimming). Profiles can be developed
   independently since they just gate which `register_*()` calls run. Trimming
   can proceed in parallel. **Recommendation**: Make Steps 2 and 3 fully
   parallel, with only Step 1 as a prerequisite.

4. **Missing consideration: migration path.** The plan doesn't address how
   existing Claude Code sessions will react when a server restarts with fewer
   tools. Claude may attempt to call tools that no longer exist.
   **Recommendation**: Add a `list_available_tools` meta-tool to every profile,
   including minimal. Claude can check this when a tool call fails.

### Review 2: Security

**Reviewer**: Security auditor perspective, informed by CLAUDE.md security
guidelines and MCP tool authentication patterns.

**Verdict: Low risk with 3 guardrails needed.**

1. **Trimmed descriptions won't remove security guidance.** Tool descriptions
   don't contain authz/authn instructions — that's handled by decorators like
   `@require_mcp_auth` in the implementation. Trimming docstrings is safe.

2. **Profile selection must protect monitoring tools.** The minimal profiles
   must ALWAYS include health/liveness/readiness endpoints regardless of
   config. These are used by infrastructure (Kubernetes probes, load
   balancers). **Recommendation**: Define a `MANDATORY_TOOLS` constant in
   mcp-common that each server's profile system must always register. At
   minimum: `get_liveness`, `get_readiness`, `health_check`.

3. **Environment variable injection is low risk.** The `TOOL_PROFILE` env var
   just selects a Python enum value. Invalid values should fall back to
   `full` (current behavior). No code execution risk. **Recommendation**:
   Add explicit validation with fallback:
   ```python
   profile = ToolProfile(os.getenv("TOOL_PROFILE", "full"))
   # Invalid value → ToolProfile.FULL
   ```

4. **Health alert tools should survive profile downgrades.** Session-buddy's
   `quality_monitor` and mahavishnu's `get_active_alerts` / `trigger_test_alert`
   are in the `full` profile only. If running `standard`, these monitoring
   capabilities are lost. **Recommendation**: Move `get_active_alerts` and
   `get_health` into `standard` for both servers.

5. **Auth tools are already outside the tool registration pattern** (handled
   by MCP middleware), so profile changes don't affect authentication.

### Review 3: UX / Developer Experience

**Reviewer**: UX researcher perspective, informed by Claude Code tool
invocation patterns and the current 393-tool system prompt.

**Verdict: 200 chars is sufficient but discovery is critical.**

1. **200 chars is plenty for tool selection.** Claude picks tools by matching
   user intent to tool name + description. Current tool descriptions average
   ~600 chars but Claude primarily uses the first sentence. The Examples and
   Returns sections are almost never used for selection. **Confirm: 200 char
   budget is correct.** Consider 250 for tools with complex parameter
   interactions.

2. **Missing tools will be jarring.** When a user says "analyze my
   productivity" and `get_productivity_insights` isn't loaded (it's in
   `full` only), Claude has no way to know it exists. **Critical
   recommendation**: Add a `discover_tools(query: str)` meta-tool to every
   profile (including minimal). It searches unloaded tool descriptions and
   returns "Available but not loaded: `get_productivity_insights` — Analyze
   temporal patterns in session activity. Restart with TOOL_PROFILE=full to
   enable."

3. **Profile naming is intuitive.** minimal/standard/full maps to the
   well-known pattern (e.g., nginx, PostgreSQL). No change needed.

4. **Per-repo profile in CLAUDE.md is the right call.** A mahavishnu
   session needs different tools than a session-buddy session. **Answer to
   Open Question #4**: Yes, add `TOOL_PROFILE: standard` to each project's
   CLAUDE.md or `.claude/settings.local.json`.

5. **Dynamic tool loading would be ideal but isn't feasible.** Claude Code
   loads tools once at session start and doesn't support mid-session tool
   registration. **Answer to Open Question #2**: Static profiles only. The
   `discover_tools` meta-tool is the best we can do.

6. **Default should be `standard` for development, `full` for CI/CD.**
   Daily development benefits most from reduced context. CI pipelines want
   all tools available. **Answer to Open Question #3**: Default to
   `standard` in `local.yaml`, keep `full` in committed config.

### Review 4: Code Quality

**Reviewer**: Code quality perspective, informed by reading the actual
registration patterns in session-buddy/server.py, mahavishnu tool files,
and mcp-common/profiles/.

**Verdict: Implementation order needs adjustment, FastMCP interaction needs
verification.**

1. **FastMCP docstring extraction is the critical unknown.** FastMCP uses
   the function's `__doc__` as the tool description. The plan assumes we can
   trim this without affecting parameter schemas. This is CORRECT — FastMCP
   extracts parameter descriptions from type hints and `Annotated[]` types,
   not from the docstring. The docstring becomes only the top-level
   description. **Verified: trimming docstrings is safe.**

2. **The `register_*()` pattern makes profile gating clean.** Session-buddy
   calls 28 `register_*()` functions in `server.py`. Mahavishnu has similar
   patterns. Gating is a simple if-check before each call:
   ```python
   if profile >= ToolProfile.STANDARD:
       register_bottleneck_tools(mcp)
   if profile >= ToolProfile.FULL:
       register_phase4_tools(mcp)
   ```
   **This is clean and backward-compatible.**

3. **Implementation order correction**: Step 1 (mcp-common) is correct as
   prerequisite. But Step 3 (profiles) should come BEFORE Step 2 (trimming).
   Reason: Profiles give us a safety net — if trimming breaks something,
   we can fall back to `full` profile. Also, profiles are smaller changes
   (server.py only) vs trimming (43+ files). **Recommendation**: Swap
   Steps 2 and 3. Do profiles first, then trim with the safety net in place.

4. **The minimal toolsets look reasonable** with two exceptions:
   - Session-buddy minimal is missing `store_conversation_checkpoint` — this
     is used by the pre-compact hook and should always be available.
   - Mahavishnu minimal should include `get_workflow_statistics` for basic
     monitoring.

5. **Missing: integration test strategy.** The plan mentions validation but
   doesn't specify how to test that trimmed descriptions are still useful.
   **Recommendation**: After implementation, run a test where Claude is given
   a task that requires 5 specific tools. Measure selection accuracy with
   trimmed vs untrimmed descriptions. If accuracy drops below 95%, increase
   the description budget.

---

## Review Synthesis & Plan Revisions

Based on the 4 reviews, the following changes should be applied before
execution:

### Accepted Changes

| # | From Review | Change |
|---|-------------|--------|
| 1 | Architecture | Profile mappings per-server, `ToolProfile` enum in mcp-common only |
| 2 | Architecture | Add `list_available_tools` / `discover_tools` meta-tool |
| 3 | Security | Define `MANDATORY_TOOLS` constant (liveness, readiness, health) |
| 4 | Security | Move alert tools into `standard` profile |
| 5 | UX | Add `discover_tools(query)` to every profile including minimal |
| 6 | UX | Default to `standard` in local.yaml, `full` in committed config |
| 7 | Code Quality | **Swap Steps 2 and 3** — profiles first, then trimming |
| 8 | Code Quality | Add `store_conversation_checkpoint` to session-buddy minimal |
| 9 | Code Quality | Add `get_workflow_statistics` to mahavishnu minimal |
| 10 | Code Quality | Add integration test for tool selection accuracy |

### Answers to Open Questions

1. **Discovery tool**: Yes, `discover_tools(query)` in every profile.
2. **Dynamic loading**: Not feasible. Static profiles + discovery tool.
3. **Default profile**: `standard` for dev (local.yaml), `full` for CI.
4. **Per-repo profile**: Yes, in CLAUDE.md or settings.local.json.
5. **Description budget**: 200 chars confirmed. Increase to 250 if accuracy
   tests show degradation.
