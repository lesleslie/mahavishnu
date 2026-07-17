---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: fastmcp-3-upgrade
---

# FastMCP 3.x Ecosystem Upgrade Plan

**Status:** Drafted 2026-06-26, post-Plan 1 Phase 0 subagent observation <!-- legacy status: Drafted — see YAML frontmatter -->
**Owner:** TBD (mcp-common first, then propagate outward)
**Trigger:** Plan 1 Phase 0 subagent surfaced two breaking-change callouts while scaffolding `mahavishnu/mcp/crow/`:

1. `lifespan=` parameter became a kwarg in FastMCP 3.x (no longer positional).
1. `_tool_manager._tools` private API moved; tooling-introspection code that poked at it will break.
1. `fastmcp~=2.5` pins referenced in Plan 1 are stale — actual installed version is 3.4.2.

The fix-the-Plan-1-task-10 approach is to bump the foundation package (mcp-common) first, then propagate the FastMCP 3.4+ floor to every consumer. akosha is the lone outlier — still pinned to `fastmcp>=2.14.0` in pyproject while every other repo already requires 3.x.

## Goal

Bring the entire FastMCP-using repo set (Bodai core + `*-mcp` standalone servers) to a single FastMCP 3.4+ baseline. All repos use the same major version, share the same `StandardServerSettings` foundation from mcp-common (where applicable), and consume the same lifespan / middleware / tool-registration APIs. Eliminate every pre-3.x holdout.

## Architecture

### Affected repos and current state

#### Bodai core (7 repos)

| Repo | pyproject pin | Installed | Risk |
|---|---|---|---|
| **mcp-common** | (no pin) | 3.4.2 | Foundation — sets the floor for everyone |
| **mahavishnu** | `fastmcp>=3.4.0` | 3.4.2 | Already on 3.x; refresh lifespan usage |
| **session-buddy** | `fastmcp>=3.3.1` | 3.4.2 | Already on 3.x |
| **akosha** | `fastmcp>=2.14.0` | 3.4.2 (transitive) | **Outlier — last 2.x pin; full migration** |
| **dhara** | `fastmcp>=3.3.1` | 3.4.2 | Already on 3.x |
| **oneiric** | (no pin) | 3.4.2 | No direct usage — inherits via mcp-common |
| **crackerjack** | `fastmcp>=3.3.1` | 3.4.2 | Already on 3.x |

#### Standalone `*-mcp` servers (15 repos) — added 2026-06-26

| Repo | pyproject pin | Import sites | Risk |
|---|---|---|---|
| **excalidraw-mcp** | `fastmcp>=3.4.2` | 5 | ✅ Already on 3.4.2 |
| **mailgun-mcp** | `fastmcp` (unpinned) | 2 | LOW — just pin it |
| **css-mcp** | `fastmcp>=0.6.0` | 2 | **CRITICAL — pre-1.0 pin, full rewrite likely** |
| **langsmith-mcp** | `fastmcp>=0.6.0` | 1 | **CRITICAL — pre-1.0 pin, full rewrite likely** |
| **graphics-mcp** | `fastmcp>=2.12.3` | 3 | HIGH — 2.x → 3.x migration |
| **neo4j-mcp** | `fastmcp>=2.12.3` | 1 | HIGH — 2.x → 3.x migration |
| **opera-cloud-mcp** | `fastmcp>=2.12.0` | **45** | **HIGH — biggest scope; 45 sites to migrate** |
| **penpot-api-mcp** | `fastmcp>=2.12.0` | 5 | HIGH — 2.x → 3.x migration |
| **porkbun-dns-mcp** | `fastmcp>=2.12.3` | 2 | HIGH — 2.x → 3.x migration |
| **porkbun-domain-mcp** | `fastmcp>=2.12.3` | 2 | HIGH — 2.x → 3.x migration |
| **raindropio-mcp** | `fastmcp>=2.12.0` | 15 | HIGH — 2.x → 3.x migration |
| **spline-mcp** | `fastmcp>=2.12.3` | 15 | HIGH — 2.x → 3.x migration |
| **synxis-crs-mcp** | `fastmcp>=2.12.3` | 2 | HIGH — 2.x → 3.x migration |
| **synxis-pms-mcp** | `fastmcp>=2.12.3` | 2 | HIGH — 2.x → 3.x migration |
| **unifi-mcp** | `fastmcp>=2.12.3` | 5 | HIGH — 2.x → 3.x migration |

**Total: 22 repos.** Bodai core = 7 (mostly 3.x). Standalone `*-mcp` = 15 (mostly 2.x or pre-1.0).

**Standalone `*-mcp` repos ARE on mcp-common** (per user directive 2026-06-26 — already true for 14/15). The audit confirms:

| Repo | mcp-common dep | Strategy |
|---|---|---|
| css-mcp | `mcp-common~=0.16.4` | Already on it; bump to `>=0.16.4,<1` once Phase 1 lands |
| excalidraw-mcp | `mcp-common>=0.16.4` | Already on it |
| graphics-mcp | `mcp-common>=0.4.8` | Already on it; needs lower-bound bump |
| langsmith-mcp | `mcp-common>=0.9.5` | Already on it; needs lower-bound bump |
| mailgun-mcp | `mcp-common>=0.4.8` | Already on it |
| neo4j-mcp | `mcp-common>=0.4.8` | Already on it |
| opera-cloud-mcp | `mcp-common>=0.4.8` | Already on it |
| penpot-api-mcp | `mcp-common>=0.15.0` | Already on it |
| porkbun-dns-mcp | `mcp-common>=0.4.8` | Already on it |
| porkbun-domain-mcp | `mcp-common>=0.4.8` | Already on it |
| raindropio-mcp | `mcp-common>=0.4.8` | Already on it |
| **spline-mcp** | **NOT_DEPENDENT** | **Action: add `mcp-common>=0.16.4` as a new direct dep** |
| synxis-crs-mcp | `mcp-common>=0.4.8` | Already on it |
| synxis-pms-mcp | `mcp-common>=0.4.8` | Already on it |
| unifi-mcp | `mcp-common>=0.4.8` | Already on it |

**mcp-common dep weight** (what adopting it costs): oneiric, pydantic, pydantic-settings, psutil, pyyaml, rich, typer, PyJWT, cryptography, websockets, pyobjc-core — ~11 transitive packages. Substantial but already accepted by 14/15 repos.

**opera-cloud-mcp has 45 import sites — the largest FastMCP surface outside Bodai core.** It likely uses many tools and possibly private APIs. May need its own sub-plan.

### Dependency ordering (critical)

mcp-common first, because every other repo depends on it. The order is:

1. **mcp-common** — set the new baseline (3.4+), refactor exports, fix internal uses
1. **akosha** — full migration off 2.x (the largest delta)
1. **mahavishnu / session-buddy / dhara / crackerjack** — bump pins to 3.4+ (already on 3.x; mostly mechanical)
1. **oneiric** — only inherits via mcp-common; confirm no direct imports

Doing mcp-common last would force every consumer to deal with two breaking-change waves. Doing it first means each consumer hits one wave.

### Known breaking changes (3.0 → 3.4) and mitigations

| Change | Mitigation |
|---|---|
| `lifespan=` is now a kwarg, not positional | Grep for `FastMCP(..., lifespan` and verify it's a kwarg. FastMCP 3 emits a deprecation warning but still accepts positional in some versions — flip to kwarg. |
| `_tool_manager._tools` private API moved | Avoid poking at private APIs. If introspection is needed, use `await server.get_tools()` (public 3.x API) or iterate over the registered tools via the MCP protocol. |
| `Server.run()` lifecycle: lifespan fires before tool registration in 3.x (was: after) | Code that depends on lifespan side effects being available during tool execution needs to move setup into a dependency-injected factory called from each tool, not into lifespan. |
| `Context` object: `request_context` is now async-only | Anywhere `request_context.lifespan_context` was read synchronously, await it. |
| Settings: `port` is now `transport_port` (or stays `port` depending on sub-API) | Verify each `server.run(host=..., port=...)` call against FastMCP 3's actual signature. |
| Middleware: `on_request` / `on_response` renamed to `on_message` / `on_response` (with stricter typing) | Audit `akosha/security.py:447` (auth middleware) against the new signature. |
| Transport: stdio vs HTTP selection now via `transport=` kwarg, not constructor | `server.run(transport="http")` vs `server.run(transport="stdio")`. |

## Phases

### Phase 0 — Inventory (1 day, single engineer)

Grep every repo (Bodai core + `*-mcp` standalone) for FastMCP usage patterns. Catalog:

- `from fastmcp import FastMCP` sites
- `FastMCP(...)` constructor calls (capture full signature usage)
- `@server.tool` / `@mcp.tool` decorators (capture param types)
- `lifespan=` usages (positional vs kwarg)
- Private-API pokes (`_tool_manager`, `_state`, `_middleware`)
- Middleware classes (inherit from `Middleware` or `BaseMiddleware`)
- `server.run(...)` calls

Output: a per-repo inventory document listing every site that needs review. (Bodai core inventory already complete at [`2026-06-26-fastmcp-3-upgrade-inventory.md`](./2026-06-26-fastmcp-3-upgrade-inventory.md). Standalone `*-mcp` inventory still needed.)

### Phase 1 — mcp-common foundation (1 day)

Goals:

- Pin `fastmcp>=3.4.0,<4` in `mcp-common/pyproject.toml`
- Re-export `FastMCP`, `Context`, `Middleware`, settings classes from a single module (`mcp_common.fastmcp`)
- Fix any internal uses of `lifespan=` positional or private APIs
- Update tests to confirm 3.x imports work
- Pin a major version range so consumers don't get surprise 4.0 breakages

**Acceptance:**

- `mcp-common/pyproject.toml` has `fastmcp>=3.4.0,<4`
- All `from fastmcp import ...` inside mcp-common still work
- mcp-common's own test suite passes under FastMCP 3.4.2

### Phase 2 — Bodai consumer bumps (1 day, mechanical)

Mechanical bumps for Bodai core repos already on 3.x:

- mahavishnu: pin → `>=3.4.0,<4`, refresh lifespan usage if any, fix `_tool_manager` private poke at `server_core.py:1194`
- session-buddy: pin → `>=3.4.0,<4`, fix `_tools = compat_tools` private poke at `session_tools.py:1168`
- dhara: pin → `>=3.4.0,<4`, add explicit `transport=` to `__main__.py:16`
- crackerjack: pin → `>=3.4.0,<4`, add explicit `transport=` to `server_core.py:400`
- oneiric: confirm no direct FastMCP usage

For each: run the repo's test suite, fix any breakage from pin tightening. Likely 0-2 fixes per repo.

**Acceptance:**

- All 5 Bodai consumer repos have `fastmcp>=3.4.0,<4`
- Each repo's test suite passes
- `_tool_manager` and `_tools` private pokes removed or replaced with public API

### Phase 3 — akosha migration (2-3 days, the biggest Bodai delta)

Specifically:

- Bump `fastmcp>=2.14.0` → `fastmcp>=3.4.0,<4` in akosha pyproject
- Audit `akosha/security.py:435-449` (auth middleware) against 3.x `Middleware` API (decide: subclass `Middleware` or keep decorator-helper pattern)
- Audit `akosha/mcp/server.py:22-158` (server creation + lifespan) against 3.x — already partly migrated
- Audit `akosha/mcp/tools/` for any 2.x-only patterns (e.g., `Context.get_context()` removed in 3.x)
- Audit `akosha/cli.py:205` (server launch) for transport= kwarg
- Run akosha test suite under 3.4.2; fix every breakage
- Add a regression test that asserts `fastmcp.__version__ >= "3.4"` at akosha server startup

**Acceptance:**

- `akosha/pyproject.toml` has `fastmcp>=3.4.0,<4`
- akosha test suite passes under 3.4.2 (target: zero new failures vs. 2.x baseline)
- Auth middleware works (manual integration test if no auto-test exists)
- Server boots and accepts at least one tool call

### Phase 4 — pre-1.0 holdouts (css-mcp, langsmith-mcp, mailgun-mcp)

The three repos pinned to FastMCP 0.x or unpinned:

- **css-mcp**: `fastmcp>=0.6.0` → migrate to 3.4.0 (likely significant rewrite — 0.x API is very different from 3.x)
- **langsmith-mcp**: `fastmcp>=0.6.0` → migrate to 3.4.0
- **mailgun-mcp**: unpinned → pin to `>=3.4.0,<4`

**Risk: HIGH.** Pre-1.0 to 3.x is a multi-major-version jump. The migration is closer to "rewrite the FastMCP integration" than "bump a pin."

**Recommendation:** Phase 4 should be a separate sub-plan per repo, not bundled into Plan 7. Open a follow-up plan for each:

- `2026-06-26-css-mcp-fastmcp-rewrite.md`
- `2026-06-26-langsmith-mcp-fastmcp-rewrite.md`
- `2026-06-26-mailgun-mcp-fastmcp-pin.md`

### Phase 5 — 2.x-to-3.x standalone `*-mcp` migrations (parallel)

10 standalone repos currently pinned to FastMCP 2.12.x:

- graphics-mcp, neo4j-mcp, opera-cloud-mcp, penpot-api-mcp, porkbun-dns-mcp, porkbun-domain-mcp, raindropio-mcp, spline-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp

**All should consume `from mcp_common.fastmcp import FastMCP, Context, Middleware`** (per user directive 2026-06-26). 14 of 15 already declare mcp-common as a dep; `spline-mcp` is the lone outlier and needs `mcp-common>=0.16.4` added. Phase 1's centralized re-export surface in mcp-common is what enables the standardized import path — Phase 5 then becomes a mostly mechanical "switch the import path, fix breakage from 2.x → 3.x."

Each is independent. Strategy:

- **opera-cloud-mcp** has 45 import sites — likely needs its own sub-plan (similar to Phases 1-3 above but per-repo)
- **Other 9 repos** have 1-15 import sites each — manageable in a single dispatch per repo, or batched

**Recommendation:** Group by complexity:

- **Easy batch** (1-5 import sites, 8 repos): graphics-mcp, neo4j-mcp, penpot-api-mcp, porkbun-dns-mcp, porkbun-domain-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp — single subagent dispatch per repo, can parallelize
- **Medium batch** (15 import sites, 2 repos): raindropio-mcp, spline-mcp — slightly more involved but still per-repo dispatch. **spline-mcp also needs mcp-common added as a new direct dep.**
- **Hard batch** (45 import sites, 1 repo): opera-cloud-mcp — dedicated sub-plan

**Per-repo deliverable for Phase 5:**

- pyproject bump (`fastmcp>=3.4.0,<4` and bump `mcp-common` lower-bound to `>=0.16.4`)
- For spline-mcp only: add `mcp-common>=0.16.4` as a new direct dep
- Import-path switch: `from fastmcp import FastMCP` → `from mcp_common.fastmcp import FastMCP` (and same for `Context`, `Middleware`)
- Fix breakage from 2.x → 3.x (private-API removals, `lifespan=` kwarg, transport= kwarg, etc.)
- Green test suite
- Optional but recommended: a regression test asserting `fastmcp.__version__ >= "3.4"`

### Phase 6 — verification + documentation (1 day)

- Add a guard test in mcp-common that fails CI if a downstream repo downgrades FastMCP below 3.4
- Update each repo's CLAUDE.md / README to note the FastMCP 3.4+ requirement
- Add a session-buddy quick_search entry: "fastmcp upgrade" → points to this plan
- Run cross-repo integration smoke test: launch mcp-common server, connect from mahavishnu, send a tool call

## Critical files

### Bodai core

**mcp-common:**

- `pyproject.toml` — bump pin
- `mcp_common/fastmcp/__init__.py` (new) — re-export surface
- `tests/unit/test_standard_server.py` — add FastMCP version assertion

**mahavishnu:**

- `pyproject.toml` — bump pin
- `mcp/server_core.py:1194` — replace `_tool_manager` private poke with public API

**session-buddy:**

- `pyproject.toml` — bump pin
- `mcp/tools/session/session_tools.py:1168` — replace `_tools = compat_tools` private poke

**akosha:**

- `pyproject.toml` — bump pin (biggest single change)
- `akosha/mcp/server.py` — server creation + lifespan
- `akosha/security.py:435-449` — auth middleware
- `akosha/cli.py:205` — server launch
- `akosha/mcp/tools/` — tool registration
- `tests/unit/mcp/test_server.py` — server lifecycle

### Standalone `*-mcp`

Per-repo `pyproject.toml` + test suite. No shared foundation (each repo is independent). The 45-import-site opera-cloud-mcp likely has its own `mcp_common`-style module that needs migration too.

## Security posture

- **No skipping the akosha migration**. Skipping akosha and only bumping consumers leaves the ecosystem on two FastMCP majors, which means two attack surfaces (3.x middleware security guarantees don't apply to 2.x akosha).
- **Pin upper bound**: `fastmcp>=3.4.0,<4` (not just `>=3.4.0`). Prevents surprise 4.0 breakage in CI.
- **Version-assertion regression test** in mcp-common to catch downgrades early.

## Out of scope

- Adopting FastMCP 3.x features that don't exist in 2.x (e.g., new `Context.streaming()` APIs). The goal is "ecosystem on a single version," not "leverage every new feature."
- The httpx2 migration (separate plan per HANDOFF.md §Audit Finding #4).
- The `OpenAPI` schema generation migration.

## Execution mode

Recommended: `superpowers:subagent-driven-development` — one subagent per phase, with review between. Phase 2 (akosha) will be the longest; consider breaking it into 2 sub-phases (audit-then-fix).

Phase 1 (mcp-common foundation) can dispatch first since it's the dependency blocker. Phases 2 and 3 can dispatch in parallel AFTER Phase 1 ships — akosha is its own subagent; consumer bumps are a single subagent for all 4 repos.

## Acceptance criteria for closing this plan

1. All 7 affected repos (mcp-common + 6 consumers) have `fastmcp>=3.4.0,<4` in pyproject
1. mcp-common test suite passes under 3.4.2
1. akosha test suite passes under 3.4.2 with zero regressions vs. 2.x baseline
1. Each consumer's test suite passes after the pin bump
1. No `fastmcp~=2` or `fastmcp>=2` anywhere in Bodai pyproject.toml files
1. CI guard test in mcp-common catches a downgrade attempt

## Open questions

1. **Pin upper bound**: should it be `<4` (semver-major-bound) or `<3.5` (next-minor-bound)? `<4` is the conservative answer for ecosystem stability. Document the decision.
1. **akosha middleware**: does FastMCP 3 require a specific middleware class shape, or is `BaseMiddleware` still the parent? Verify against FastMCP 3.4 changelog before Phase 2 dispatch.
1. **mcp-common re-export**: do consumers prefer `from mcp_common.fastmcp import FastMCP` (centralized) or do they want to keep `from fastmcp import FastMCP` (direct)? Centralized = single place to swap versions. Direct = less indirection. Decide before Phase 1 ships.
