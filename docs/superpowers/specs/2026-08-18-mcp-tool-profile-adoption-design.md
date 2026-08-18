---
status: active
role: canonical
date: 2026-08-18
last_reviewed: 2026-08-18
topic: mcp-tool-profile-adoption
title: MCP Tool Profile Adoption Across Bodai Ecosystem
---

# MCP Tool Profile Adoption Across Bodai Ecosystem — Design Spec

**Date:** 2026-08-18
**Status:** Active — sections 1–3 reviewed 2026-08-18; revised 2026-08-18 to address findings from 4-agent spec review (architecture, MCP integration, Bodai conventions, adversarial).
**Source:** Brainstorm session between Les and Claude on whether dynamic tool loading in `-mcp` repos would save considerable context. Concluded YES with tiered adoption.

## Background

Bodai core components (Mahavishnu, Session-Buddy, Akosha, Dhara) ship an MCP **Tool Profile System** to gate tool registration at startup, reducing context-window overhead for Claude sessions. The shared primitive lives in `mcp-common` (`mcp_common/tools/profiles.py`: `ToolProfile` enum + `MANDATORY_TOOLS` set). Of the 5 core Bodai components, **4 of 5 already use the pattern** (Crackerjack is the lone exception, with a self-rolled but non-standard `discover_tools.py` and no `CRACKERJACK_TOOL_PROFILE` env var).

**18 Bodai-ecosystem MCP servers do NOT use the pattern** (audit 2026-08-18):

| Tier | Tool count | Repos |
|------|------------|-------|
| Core Bodai, missing pattern | (5 groups) | **crackerjack** |
| Other MCP servers (non-`-mcp` suffix) | 8–10 | fastblocks, splashstand |
| `-mcp` suffix, Trivial (≤10 tools) | 0–10 | css-mcp (9), excalidraw-mcp (5), neo4j-mcp (9), penpot-api-mcp (6), porkbun-dns-mcp (5), porkbun-domain-mcp (5), raindropio-mcp (0), synxis-pms-mcp (10) |
| `-mcp` suffix, Small (11–15 tools) | 11–15 | graphics-mcp (11), synxis-crs-mcp (12), unifi-mcp (13), langsmith-mcp (15) |
| `-mcp` suffix, Large (25+ tools) | 25–56 | spline-mcp (25), mailgun-mcp (31), opera-cloud-mcp (56) |

The existing 4 core components each define their own `PROFILE_REGISTRATIONS` locally, importing only the shared `ToolProfile` enum + `MANDATORY_TOOLS` set. This duplication (4 copies of "read env var → gate `register_*()` calls → register `discover_tools()`") is the maintenance burden we eliminate by extracting a shared helper.

## Goal

Adopt the `ToolProfile` mechanism across **all 18 Bodai-ecosystem MCP servers** (15 `-mcp` repos + Crackerjack + fastblocks + splashstand), using a **single shared helper** in `mcp-common`. Standardize the implementation shape so every server's diff is the same: one import, one `PROFILE_REGISTRATIONS` data structure, one helper call, one test file.

## Scope

**In scope:**
- New `mcp_common/tools/dispatch.py` with `apply_tool_profile()` helper
- Backfill of mahavishnu/session-buddy/akosha/dhara to use the helper (W1, "eat our own dog food")
- Adoption in 13 remaining repos in tiered waves (W2a–W4)
- Crackerjack: delete legacy `discover_tools.py` + `TOOL_REGISTRY`; add `CRACKERJACK_TOOL_PROFILE`

**Out of scope (this spec):**
- Adding NEW tools to any server (this is wiring existing tools)
- Changing the `ToolProfile` enum itself or `MANDATORY_TOOLS` set
- Introducing a new profile level (e.g., DEBUG) — `MINIMAL`/`STANDARD`/`FULL` stay
- Per-tool permissions or RBAC — profile gating is environment-based, not identity-based
- Conformance tests for the profile pattern (deferred to a follow-up spec)
- CLI helper for ops debugging (deferred to follow-up spec — Open Question #1)
- Query-time filtering in `discover_tools()` (deferred to follow-up spec — Open Question #2; the helper signature will provision for it as an additive change)

## Constraints

- **Pre-1.0 merge policy:** direct to main via branch + ff-merge; no PRs, no review gates
- **No backwards compatibility / legacy support.** Per Bodai pre-1.0 standardization policy, Crackerjack's existing `TOOL_REGISTRY` is **deleted**, not wrapped
- **No new PyPI packages.** Helper lives in `mcp-common` (already published)
- **Crackerjack ecosystem-agnostic.** This work is configuration/profile *mechanism* (already in `mcp-common`). Crackerjack already depends on `mcp-common` (verified 2026-08-18 via `grep 'mcp-common' crackerjack/pyproject.toml` — no new dependency added). Crackerjack's own conformance checker is not in scope.
- **Cross-component wiring goes over MCP** (per the 2026-08-12 ruling). The helper is a shared library (`mcp-common`), not a cross-component call.
- **Per-repo `PROFILE_REGISTRATIONS` stays local.** The `ToolProfile` enum is shared; the tool-group taxonomy is domain knowledge that belongs with the server.
- **Pin `mcp<2` in `mcp-common/pyproject.toml`.** The MCP SDK v2 renamed `FastMCP` to `MCPServer`; pinning avoids breaking the helper across 18 repos (memory: `minimax-coding-plan-mcp-v2-conflict.md`).
- **W0 has a soft review gate.** The helper PR is reviewed by 1–2 implementers of the W1 backfill before W1 starts, to validate the API covers all 4 existing patterns. This is consistent with the spec's W1-as-dogfood reasoning and pre-1.0 merge policy is otherwise unaffected.

## Architecture

Two-layer split:

**Framework layer (`mcp-common`):** `apply_tool_profile()` reads `{SERVER}_TOOL_PROFILE` from env (with optional yaml fallback), dispatches to the right `register_*()` calls, ensures `MANDATORY_TOOLS` always register, auto-registers a default `discover_tools()` meta-tool that introspects the FastMCP server. Per-server "policy" is passed in as data.

**Policy layer (per repo):** Each server declares its `PROFILE_REGISTRATIONS` mapping local tool groups to profile levels. This is domain knowledge (which tools are daily-driver vs advanced) that belongs with the server.

```python
# Framework import (same in all 18 repos)
from mcp_common.tools import ToolProfile, MANDATORY_TOOLS, apply_tool_profile, ALL_TOOLS

# Policy data (differs per repo)
PROFILE_REGISTRATIONS: dict[ToolProfile, list[str | Callable] | type[ALL_TOOLS]] = {
    ToolProfile.MINIMAL:  list(MANDATORY_TOOLS),
    ToolProfile.STANDARD: ["tool_group_1", "tool_group_2", ...],
    ToolProfile.FULL:     ALL_TOOLS,  # typed sentinel: register every group
}

# Wiring call (same in all 18 repos)
apply_tool_profile(
    server,
    profile_env_var="{SERVER}_TOOL_PROFILE",
    registrations=PROFILE_REGISTRATIONS,
    registration_map={
        "tool_group_1": register_tool_group_1,
        # ... per-repo mapping of group name → register callable
    },
    register_all_fn=register_all_tool_groups,  # required when FULL == ALL_TOOLS
    mandatory_tools=MANDATORY_TOOLS,  # or per-repo subset
)
```

**Why "framework + policy" rather than "all framework":** Each server has a different tool taxonomy. Mailgun-mcp's `webhook_management` doesn't translate to opera-cloud-mcp's `reservation_operations`. Trying to centralize the mapping would either fail (impedance mismatch) or succeed (lose flexibility). Local `PROFILE_REGISTRATIONS` keeps the domain knowledge where it belongs.

## Components

### 1. `mcp_common/tools/dispatch.py` (new, ~120 lines)

```python
class ALL_TOOLS:  # typed sentinel — string "all_tools" collides with valid group names
    """Sentinel marking `ToolProfile.FULL` to register every tool group."""
    pass


def apply_tool_profile(
    server: FastMCP,
    *,
    profile_env_var: str,
    registrations: dict[ToolProfile, list[str | Callable] | type[ALL_TOOLS]],
    registration_map: dict[str, Callable[[FastMCP], Awaitable[None] | None]],
    register_all_fn: Callable[[FastMCP], Awaitable[None] | None],
    mandatory_tools: set[str] = MANDATORY_TOOLS,
    discovery_fn: Callable[[FastMCP, str | None], Awaitable[list[dict]]] | None = None,
    yaml_loader: Callable[[], dict | None] | None = None,
) -> None:
    """Apply the tool profile to the server at startup.

    - Reads {profile_env_var} from env, optionally falls back to `yaml_loader()`,
      defaults to FULL.  Empty/whitespace/unknown values raise InvalidProfileError.
    - Always registers `mandatory_tools` regardless of profile. Per-repo override
      via the `mandatory_tools` parameter (some leaf repos don't have all 4 health tools).
    - Dispatches to per-group `registration_map[name](server)` calls; calls return
      `None | Awaitable[None]` — helper awaits if coroutine, else calls sync.
    - At FULL with `ALL_TOOLS` sentinel, calls `register_all_fn(server)` once.
    - Auto-registers `discover_tools()` via `discovery_fn` (default: FastMCP public
      `await server.list_tools()`). Existing `discover_tools` is replaced idempotently.
    - Logs profile applied + count of registered tools at startup (Oneiric logger,
      not stdlib).

    Raises:
        InvalidProfileError: env var value is empty, whitespace, or not a valid enum.
        ToolNameCollisionError: MANDATORY_TOOLS registration fails (already-registered
          name with conflicting signature).
        ValueError: `ALL_TOOLS` sentinel used but `register_all_fn` is None.
    """
```

#### Behavior matrix (4 cases, made explicit)

| Case | `registrations[STANDARD]` | `registrations[FULL]` | Behavior at STANDARD | Behavior at FULL |
|------|---------------------------|------------------------|----------------------|------------------|
| **A** callable-only (Tier-A typical) | list of group names | `ALL_TOOLS` | dispatch `registration_map[name](server)` for each | call `register_all_fn(server)` once |
| **B** decorator-mode (Tier-A edge) | list of group names | list of group names | dispatch per-group (groups registered via `@app.tool` already at import — must be loaded conditionally, see W4 implementation notes) | dispatch every group in `FULL` list |
| **C** method-mode (mahavishnu, where `_register_<group>()` exists on server class) | list of group names | `ALL_TOOLS` | call `server._register_<group>()` via `registration_map` lambda | call `register_all_fn(server)` once |
| **D** single-group (Tier-B simple case) | list with one entry | `ALL_TOOLS` | dispatch that one group | call `register_all_fn(server)` |

#### Enum dispatch decision table

For each profile level, the helper:
1. Resolves the effective profile from env var (validates non-empty, strips whitespace, uppercase, raises `InvalidProfileError` on unknown).
2. Optionally falls back to `yaml_loader()` result if env var unset.
3. Iterates `registrations[profile]`:
   - If a string: look up `registration_map[string]` and call with `server`.
   - If a `Callable`: call directly.
   - If `ALL_TOOLS`: call `register_all_fn(server)` and break.
4. Registers `mandatory_tools` last with idempotency check (skip if name already registered).
5. Registers `discover_tools()` via `discovery_fn` (default introspection).

#### YAML precedence (W1 mahavishnu compatibility)

Mahavishnu currently uses env var → `settings/local.yaml` → default precedence (`mahavishnu/mcp/tools/profiles.py:15-18`). The helper accepts an optional `yaml_loader: Callable[[], dict | None] | None` parameter. W1 mahavishnu passes `lambda: settings.tool_profile`. Other repos pass `None` (env-only). The YAML value must be normalized through `str()` to avoid YAML 1.1 truthy-literal coercion (e.g., `yes` → `True`).

#### `discover_tools()` introspection

Default uses FastMCP's **public** `await server.list_tools()` method. Pinning `mcp<2` in pyproject avoids the `FastMCP` → `MCPServer` rename breakage. The returned `Tool` objects are serialized to `[{name, description, inputSchema, group: null}]` (group defaults to `None` — only set when the repo's `registration_map` keys match tool names; decorator-mode tools have `group=null`).

Override `discovery_fn` is reserved for repos with custom semantics (Crackerjack's `query`-based filter; future virtual tools). Crackerjack's W2a implementation **must** provide `discovery_fn` to preserve its existing query-filter behavior (deleted `TOOL_REGISTRY` had 178 lines of metadata).

### 2. Backfill of 4 existing core components (W1)

Replace explicit wiring with `apply_tool_profile()` call. `PROFILE_REGISTRATIONS` shape and tool-group taxonomy **unchanged** in semantics (mahavishnu's `_register_<group>()` methods preserved as `registration_map` lambdas). Behavior at each profile level verified identical via golden-test fixture.

**Verification:** Snapshot test asserting `set(registered_tool_names) == fixture.load(profile)` for each profile level. Fixtures captured *before* the W1 change as ground truth.

**W1 is a refactor, not a wire-format-preserving cleanup.** Each backfill PR includes (a) the `apply_tool_profile()` adoption, (b) a `registration_map` lambda binding existing `_register_<group>()` methods, (c) golden-test capture if not already done.

### 3. Crackerjack retrofit (W2a)

**Delete:** `crackerjack/mcp/tools/discover_tools.py` (containing `TOOL_REGISTRY` + `DEFERRED_TOOLS` + `register_discover_tools` + `discover_tools()` with query filter). Delete any test that imports `TOOL_REGISTRY`.

**Pre-deletion grep:** `git grep -l TOOL_REGISTRY` across `crackerjack/` AND every Bodai consumer (scripts, examples, docs) before W2a. List every site that must be updated.

**Add:** `crackerjack/mcp/tools/profiles.py` with `PROFILE_REGISTRATIONS`:
```python
PROFILE_REGISTRATIONS = {
    ToolProfile.MINIMAL:  list(MANDATORY_TOOLS),
    ToolProfile.STANDARD: ["core_tools", "execution_tools", "utility_tools", "doc_tools"],
    ToolProfile.FULL:     ALL_TOOLS,  # includes eventbridge_tools, progress_tools
}
```

**Wire:** `apply_tool_profile()` call in `crackerjack/mcp/server_core.py` reading `CRACKERJACK_TOOL_PROFILE`. **Provide `discovery_fn` override** that preserves the existing `query` parameter behavior (deferred `TOOL_REGISTRY` had custom filtering).

**Update docs:** Annotate `crackerjack/docs/architecture/MEMORY_ARCHITECTURE.md` with the literal text: "**Resolved 2026-08-18:** `CRACKERJACK_TOOL_PROFILE` is now implemented in `crackerjack/mcp/tools/profiles.py`. See `2026-08-18-mcp-tool-profile-adoption-design` for context."

**AST-based removal of `TOOL_REGISTRY`** (not `str.replace` — memory: `ast-block-removal-vs-str-replace`). Extract the dict's `lineno`/`end_lineno`, delete by line span, validate with `ast.parse()` post-removal.

### 4. Tier-C adoption (mailgun-mcp, opera-cloud-mcp, spline-mcp, W2b)

Each repo:
- Imports `apply_tool_profile`, `ALL_TOOLS`, `ToolProfile`, `MANDATORY_TOOLS` from `mcp_common.tools`
- Defines `PROFILE_REGISTRATIONS` with 3 meaningful buckets (real design work — implementer must audit existing tools)
- Defines `registration_map: dict[str, Callable]` mapping each group name to its register function
- Calls `apply_tool_profile()` in main entrypoint
- Adds `.claude/decisions/tool-profile-rationale.md` (per existing `.claude/decisions/` topic-as-filename convention; e.g., `removed-scripts.md`, `bodai-observability-pattern.md`) documenting the bucket rationale
- Adds `tests/unit/test_tool_profile.py` + `tests/integration/test_profile_gating.py`

**Per-repo mapping rationale (sketch — finalized in implementation):**
- **mailgun-mcp (31):** STANDARD = `send_messages`, `get_stats`, `validate_address`, `list_domains`. FULL adds `webhook_management`, `suppression_lists`, etc.
- **opera-cloud-mcp (56):** STANDARD = reservation search + guest lookup. FULL = everything (incl. write-side ops).
- **spline-mcp (25):** STANDARD = scene CRUD + import/export. FULL = animation + physics + advanced effects.

### 5. Tier-B adoption (graphics-mcp, langsmith-mcp, synxis-crs-mcp, unifi-mcp, W3)

Same shape as W2b but smaller mapping (1–2 buckets). Each repo adds `.claude/decisions/tool-profile-rationale.md` if the bucket split is non-trivial (4 of 4 Tier-B repos qualify per audit).

### 6. Tier-A adoption (10 repos in W4)

Trivial `PROFILE_REGISTRATIONS`: MINIMAL = `MANDATORY_TOOLS`, STANDARD/FULL = `ALL_TOOLS`. Helper handles the rest via `register_all_fn`. Test asserts:
- MINIMAL → only `MANDATORY_TOOLS` registered (set match) + `discover_tools`
- STANDARD/FULL → full set registered
- **`MANDATORY_TOOLS ⊆ registered` at ALL THREE profile levels** (W4 test must assert this — prevents regression where MANDATORY drops at STANDARD)

**Decorator-mode Tier-A edge case:** If a repo registers tools via `@app.tool` decorators at module load (not via callable registration), the W4 implementer must refactor the registration into a `register_all_fn` callable before adoption. The W4 brief identifies which Tier-A repos use decorator-mode (audit before dispatch).

## Wave Plan

| Wave | Repos | Per-repo work | Risk | Blocked by |
|------|-------|---------------|------|------------|
| **W0** | `mcp-common` | Add `apply_tool_profile()` helper + `ALL_TOOLS` sentinel + tests; pin `mcp<2` | Helper API design (soft review gate) | — |
| **W1** | mahavishnu, session-buddy, akosha, dhara | Replace explicit wiring with helper call + `registration_map` lambdas | Helper can't reproduce existing behavior | W0 |
| **W2a** | **crackerjack** | Helper + retrofit + `discovery_fn` override + AST-based `TOOL_REGISTRY` deletion | Crackerjack deletion risks (178 lines, custom shape) | W1 |
| **W2b** | mailgun-mcp, opera-cloud-mcp, spline-mcp | Helper + 3-tier mapping + `tool-profile-rationale.md` + tests | Real design work (mapping) | W2a |
| **W3** | graphics-mcp, langsmith-mcp, synxis-crs-mcp, unifi-mcp | Helper + 2-tier mapping + `tool-profile-rationale.md` + tests | Mild | W2b |
| **W4** | css-mcp, excalidraw-mcp, neo4j-mcp, penpot-api-mcp, porkbun-dns-mcp, porkbun-domain-mcp, raindropio-mcp, synxis-pms-mcp, fastblocks, splashstand | Helper only (decorator-mode refactor first if applicable) | Trivial | W2b |

**W1 as dog food:** If `apply_tool_profile()` can't reproduce any of the 4 existing patterns, the helper is wrong. W1 is the discovery phase. **W2a/W2b start only after W1 lands** — the helper must be proven.

**W2a/W2b split rationale:** Crackerjack's deletion is a 178-line risky refactor; Tier-C repos are greenfield adoption with bucket-design work. Different risk profiles → separate waves with separate rollback semantics.

## Integration Contracts (per CLAUDE.md wire-up rule)

### W0 — `mcp_common/tools/dispatch.py` (helper)

- **Triggered from:** Server startup in `mcp/server_core.py`. Reads `{SERVER}_TOOL_PROFILE` env var; optional `yaml_loader()` fallback.
- **Returns to / updates:** FastMCP server's tool registry. At MINIMAL: only `mandatory_tools` + `discover_tools()`. At STANDARD+: groups per `registrations[STANDARD]`. At FULL: every group or `register_all_fn(server)`.
- **Demonstrable by:** `tests/unit/test_apply_tool_profile.py` — env var parsing (incl. `InvalidProfileError` for empty/whitespace/case/unknown), profile ordering, `mandatory_tools` invariant at all levels (assertion: `MANDATORY ⊆ registered` at MINIMAL/STANDARD/FULL), registration-call counts per case A/B/C/D, idempotent `discover_tools` registration. Plus a 4-case matrix test invoking each dispatch branch.
- **Rollback signal:** Servers using this helper fall back to FULL when unset; the helper itself ships unconditionally. Revert = `git revert` of W0 commit; downstream W1+ commits must revert in order.
- **Observability added:** Helper emits `Applied {env_var}={profile} → {N} tools registered` at INFO via `oneiric.logging.get_logger` (NOT stdlib, NOT `print()`). Per-group register at DEBUG.

### W1 — Backfill 4 core components

- **Triggered from:** `{SERVER}_TOOL_PROFILE` env var (unchanged behavior; helper preserves env var semantics).
- **Returns to / updates:** Identical tool set at each profile level. Verified by golden-test fixture.
- **Demonstrable by:** Snapshot test `assert set(registered_tool_names) == fixture.load(profile)` for `mahavishnu`, `session-buddy`, `akosha`, `dhara` at each profile. Plus YAML precedence test for mahavishnu specifically (`settings/local.yaml: tool_profile: standard` overrides unset env var).
- **Rollback signal:** `git revert` of W1 commit; revert is safe because behavior is unchanged.
- **Observability added:** Same logging shape across all 4 repos (helper handles it).

### W2a — Crackerjack retrofit

- **Triggered from:** `CRACKERJACK_TOOL_PROFILE` env var (new).
- **Returns to / updates:** Tool registration set per profile. Golden fixtures + per-tier integration test.
- **Demonstrable by:** AST-based deletion validated via `python -c "import ast; ast.parse(open('crackerjack/mcp/tools/discover_tools.py').read())"` (file must NOT exist after W2a). Then `pytest crackerjack/tests/test_mcp_server.py -k profile` passes for all 3 profile levels.
- **Rollback signal:** Unset env var → FULL profile (default). `.claude/decisions/tool-profile-rationale.md` documents rationale so a future maintainer knows what to undo.
- **Observability added:** Crackerjack CLAUDE.md updated with profile env var + discovery pattern. `MEMORY_ARCHITECTURE.md` annotated with the literal text: "**Resolved 2026-08-18:** `CRACKERJACK_TOOL_PROFILE` is now implemented in `crackerjack/mcp/tools/profiles.py`. See `2026-08-18-mcp-tool-profile-adoption-design` for context."
- **Pre-deletion grep:** `git grep -l TOOL_REGISTRY` must return empty (excluding the spec file) before merge.

### W2b — Tier-C adoption

- **Triggered from:** `{SERVER}_TOOL_PROFILE` env var. Document in each repo's `CLAUDE.md` "Tool Profile System" subsection.
- **Returns to / updates:** Tool registration set per profile. Golden fixtures + per-tier integration test.
- **Demonstrable by:** `pytest tests/integration/test_profile_gating.py -k minimal` passes (asserts `MANDATORY_TOOLS ⊆ registered` + only MANDATORY non-`discover_tools` present), `-k standard` passes (asserts expected STANDARD set), `-k full` passes (asserts FULL set covers everything).
- **Rollback signal:** Unset env var → FULL profile (default). `tool-profile-rationale.md` documents bucket rationale.
- **Observability added:** Each repo's CLAUDE.md updated with profile env var + discovery pattern. `.claude/decisions/tool-profile-rationale.md` per repo.

### W3 — Tier-B adoption

- **Triggered from:** `{SERVER}_TOOL_PROFILE` env var. Document in each repo's `CLAUDE.md`.
- **Returns to / updates:** Tool registration set per profile.
- **Demonstrable by:** Same pytest matrix as W2b, smaller expected sets.
- **Rollback signal:** Unset env var → FULL profile.
- **Observability added:** CLAUDE.md update + `.claude/decisions/tool-profile-rationale.md` per repo.

### W4 — Tier-A adoption

- **Triggered from:** `{SERVER}_TOOL_PROFILE` env var.
- **Returns to / updates:** Tool registration set per profile.
- **Demonstrable by:** `pytest tests/unit/test_tool_profile.py` with the assertion `MANDATORY_TOOLS ⊆ registered` at all 3 profile levels (NOT just tool counts). Decorator-mode refactor validated by `register_all_fn` callable existing and tested.
- **Rollback signal:** Unset env var → FULL profile.
- **Observability added:** CLAUDE.md update only (no `tool-profile-rationale.md` — trivial mapping).

## Cross-Cutting Concerns

### Test strategy (uniform across all 18)
- `tests/unit/test_tool_profile.py` — env var parsing, profile ordering, `mandatory_tools` invariant, idempotent register
- `tests/integration/test_profile_gating.py` — registered tool count per profile level
- Mirrors session-buddy's `tests/unit/test_profiles.py` + `tests/unit/test_profiles_coverage.py`

### Documentation (uniform)
- Each repo's `CLAUDE.md` adds "Tool Profile System" subsection: env var name, profile levels, default, discovery pattern
- Each Tier-B/C repo adds `.claude/decisions/tool-profile-rationale.md` documenting MINIMAL/STANDARD/FULL rationale (matches existing `.claude/decisions/` topic-as-filename convention; NOT a `WHY_*.md` prefix deviation)
- One ecosystem-level `docs/ecosystem/MCP_TOOL_PROFILES.md` explaining the cross-cutting pattern + linking each repo's profile config. **Generated from `mcp.list_tools()` programmatically** (memory: `docs-audit-mcp-tool-hallucination`) rather than hand-maintained.

### Observability (uniform)
- Each repo emits one log line at startup: `Applied {SERVER}_TOOL_PROFILE={profile} → {N} tools registered` via `oneiric.logging.get_logger` (per CLAUDE.md "Use the Oneiric logger" rule)
- `discover_tools()` returns: `{tools: [{name, description, inputSchema, group: null}], count: N, profile: "{level}", env_var: "{SERVER}_TOOL_PROFILE", hint: "Set {SERVER}_TOOL_PROFILE=full to enable all tools."}` — matches session-buddy's shape, with `group: null` for decorator-registered tools

### Audit orphan-detection (post-W2a)
- `python mahavishnu/scripts/audit_orphans.py --days 7 --root /Users/les/Projects/<repo>` confirms `apply_tool_profile()` is called in each repo's main entrypoint (cross-repo `--root` flag from `docs/plans/drafts/2026-07-11-ultracode-integration/workflow-implement-phase-6a.js`)
- **Augmented check:** the audit must verify `apply_tool_profile()` is invoked unconditionally, not behind a feature flag or try/except that swallows failure (memory: `docs-audit-documented-but-not-wired`)

### CI guard per repo
- `tests/unit/test_wiring.py::test_apply_tool_profile_called` asserts the main entrypoint imports and calls `apply_tool_profile()`. Catches drift where a future maintainer bypasses the helper in some entrypoint without detection.
- Mermaid diagrams in `docs/ecosystem/MCP_TOOL_PROFILES.md` validated per `Mermaid v11 parser pitfalls` (memory).

### Migration safety (uniform across all waves)
- Each wave is a series of small PRs (1 per repo)
- Each PR is independently revertable via `git revert` (per pre-1.0 merge policy)
- Each PR's test suite must pass before merge (`crackerjack run` for the relevant repo)
- **User bumps `mcp-common` version manually before W1 starts** (memory: `crackerjack-version-bumping-manual`); implementers do NOT bump mcp-common themselves
- W2+ implementer briefs include explicit "verify against external CLI/library" step (memory: `brief-verification-step-invocation-typos`): the implementer must run the server with each profile env var and observe the expected tool registration counts
- W4 brief pins `cd /Users/les/Projects/<exact-repo>` and verifies `pyproject` name matches before claiming done (memory: `wave-5-reviewer-caveats-2026-08-13`)
- Per-wave briefs must reference `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md` for relevant patterns: AST block removal (W2a), ruff autofix noise (W2b+), venv rebuild (post-import-change per repo), uv cross-repo VIRTUAL_ENV/UV_ACTIVE stripping, `uv sync --upgrade-package mcp-common` (NOT `--upgrade`), test-dir-shadows-site-package pre-check, drift-bundling recovery (W4 parallel dispatch), session-buddy auto-checkpoint bundling, Bodai pre-1.0 merge policy (branch + ff-merge, no PRs), Doc-audit patterns (post-wave grep for documented-but-not-wired, removed-but-referenced, MCP tool hallucination)

## Expected Outcomes

**Context savings per session (rough estimate, ~500 tokens per tool description):**

| Server | FULL tokens loaded | STANDARD tokens loaded | Saved per session |
|--------|--------------------|-----------------------|-------------------|
| mailgun-mcp (31 tools) | ~15k | ~5k | **~10k** |
| opera-cloud-mcp (56 tools) | ~28k | ~8k | **~20k** |
| spline-mcp (25 tools) | ~12k | ~5k | **~7k** |
| crackerjack (5 groups) | ~10k | ~6k | **~4k** |
| Tier-B (4 repos × ~7k avg) | ~7k | ~5k | ~2k each |
| Tier-A (10 repos) | 0–6k | 0–6k | 0 at MINIMAL (consistency only) |
| **Total** | | | **~30–40k tokens saved per session** when STANDARD profile is used across all 18 |

*Estimates assume ~500 tokens per tool description (rule of thumb); actual savings depend on MCP client's tool-call overhead and schema size. Validate post-W2b against a sample MCP client session.*

**Consistency:** Every Bodai MCP server behaves identically w.r.t. profile gating. Claude learns the pattern once.

**Maintainability:** Future profile-level additions (e.g., DEBUG) ship in `mcp-common`, all 18 benefit. Bug fix in the gating logic = 1 place.

## Open Questions (deferred to follow-up specs)

1. Should `mcp-common` also provide a `cli_helper.py` that prints "currently applied profile + registered tools" for ops debugging? (Defer to a follow-up spec; not blocking W0.)
2. Should `discover_tools()` support query-time filtering (only return tools matching `query`)? Session-buddy has this; others don't. **The helper's `discovery_fn` signature accepts an optional `filter_query: str | None = None` parameter now** so the follow-up spec is a pure additive change in repos that opt in. Default discovery_fn ignores the parameter.

## References

- `mcp_common/tools/profiles.py` — existing `ToolProfile` enum + `MANDATORY_TOOLS`
- `mahavishnu/mcp/tools/profiles.py:39-63` — mahavishnu's method-name `PROFILE_REGISTRATIONS` (W1 backfill target; helper preserves via `registration_map` lambdas)
- `mahavishnu/mcp/tools/profiles.py:15-18` — mahavishnu's YAML precedence pattern (preserved by helper's `yaml_loader` parameter)
- `session_buddy/mcp/tools/profiles.py` — current Session-Buddy profile wiring (W1 backfill target)
- `akosha/mcp/tools/profiles.py` — current Akosha profile wiring (W1 backfill target)
- `dhara/mcp/profiles.py` — current Dhara profile wiring (W1 backfill target)
- `crackerjack/mcp/tools/discover_tools.py:189-229` — Crackerjack's `discover_tools(query)` implementation (W2a `discovery_fn` override must preserve this shape)
- `crackerjack/mcp/tools/discover_tools.py` — TO-BE-DELETED in W2a (178 lines incl. `TOOL_REGISTRY` + `DEFERRED_TOOLS` + `register_discover_tools`)
- `crackerjack/docs/architecture/MEMORY_ARCHITECTURE.md` — annotated as resolved in W2a with the literal text provided above
- `docs/superpowers/specs/2026-08-12-bodai-ecosystem-consistency-design.md` — sibling spec
- `.claude/decisions/removed-scripts.md`, `bodai-observability-pattern.md` — pattern for `tool-profile-rationale.md` per-repo decision files
- `mcp-common` `pyproject.toml` — pin `mcp<2` per `minimax-coding-plan-mcp-v2-conflict` memory