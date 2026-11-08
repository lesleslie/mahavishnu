---
status: active
role: implementation
kind: plan
date: 2026-11-07
last_reviewed: 2026-11-07
superseded_by: null
topic: mcp-tool-disambiguation
title: "MCP Tool Disambiguation — unique, self-describing tool names across the Bodai core fleet"
requirements:
- id: REQ-MCPTD-001
  title: Every Bodai core MCP tool carries a non-empty, rubric-compliant description
  description: The four duplicated tools whose descriptions are empty (crackerjack search_code, pycharm_health, query_local_traces; session-buddy search_code) are given descriptions satisfying the 6-criterion rubric in docs/decisions/tool-description-rubric.md.
  implementation_repo: crackerjack
- id: REQ-MCPTD-002
  title: Same-named tools expose an identical parameter contract across servers
  description: The channel-session tools expose no parameter that the underlying store cannot filter by; the user_id fiction on both mahavishnu proxies is removed and the vestigial token parameter on session-buddy is removed.
  implementation_repo: session-buddy
- id: REQ-MCPTD-003
  title: query_local_traces exposes one parameter contract across the fleet
  description: akosha, crackerjack and mahavishnu expose query_local_traces with the same parameter names, requiredness and defaults.
  implementation_repo: akosha
- id: REQ-MCPTD-004
  title: mcp-common exposes each health and baseline tool name exactly once
  description: mcp_common/baseline_tools.py and mcp_common/health/__init__.py overlap on get_liveness, get_readiness and health_check_all; the overlap is collapsed so no server can double-register a name.
  implementation_repo: mcp-common
- id: REQ-MCPTD-005
  title: Mahavishnu sources its health tools from mcp-common instead of a vendored fork
  description: mahavishnu/mcp/tools/health_tools.py is a 1256-line divergence from mcp_common/health/__init__.py; the fork is retired and the shared implementation is mounted, with the deprecation shim parameterized rather than dropped.
  implementation_repo: mahavishnu
- id: REQ-MCPTD-006
  title: Tools whose names collide across components carry a component-scoped name
  description: detect_anomalies, find_path and search_code are renamed to component-scoped names following the fleet's existing <component>_<tool> convention.
  implementation_repo: akosha
- id: REQ-MCPTD-007
  title: A fleet-wide guard rejects duplicate names, empty descriptions and stale validator entries
  description: A script probes every live Bodai core server and fails when a bare tool name appears on two servers, a description is empty, or KNOWN_TOOLS names a tool no server serves.
---

# MCP Tool Disambiguation — unique, self-describing tool names across the Bodai core fleet

## 1. Outcome

Every MCP tool exposed by a Bodai core server is distinguishable from its
same-named peers by **name alone**, carries a **description a model can route
on**, and shares **one parameter contract** with every server that exposes
the same name.

**Success signal:** the fleet-wide guard (`scripts/check_mcp_tool_surface.py`)
reports zero duplicate bare names, zero empty descriptions, and zero stale
`KNOWN_TOOLS` entries across the five live servers — and it fails when any
one of those regresses.

## 2. Goals

1. Make each duplicated tool name unique across the fleet, without breaking
   the `mcp__<server>__<tool>` config-entry namespace that Claude Code
   depends on.
1. Give every duplicated tool a description a language model can route on,
   satisfying the canonical 6-criterion rubric.
1. Make same-named tools accept the same parameters, so a caller that learned
   one server's shape is not broken by the other.
1. Collapse the *implementation* duplication behind the duplicated names —
   one library, one registration, no vendored fork.
1. Install a guard so the next duplicate fails the build instead of waiting
   to be noticed.

## 3. Non-Goals

1. **Not** prefixing all 496 fleet tools with their component name. The
   `mcp__<server>__` prefix already namespaces the tool registry; a blanket
   prefix would yield `mcp__akosha__akosha_search_code_patterns`, touch
   103 `KNOWN_TOOLS` entries + 268 executable/config references + 525 doc
   mentions + 23 model-visible agent-frontmatter hints, and buy nothing.
1. **Not** renaming the 7 shared health/baseline names. They are one library
   correctly fanned out — see §4.2.
1. **Not** renaming `get_health`. Same-name-per-service self-health is a
   deliberate pattern; each server answers for itself.
1. **Not** introducing an MCP aggregator, proxy or gateway. Any single-endpoint
   gateway renames every tool (see the `mcp-tool-namespace-is-config-entry`
   memory) and adds a hop without reducing the tool count.
1. **Not** adding backwards-compatible aliases for renamed tools — see
   §2 Policy below.

## 2. Policy: No backwards compatibility / legacy support

Bodai is pre-1.0. Renames are **forward-only and clean**:

- A renamed tool keeps **no** deprecated alias, no dual registration, no
  deprecation window, no "old name" fallback branch.
- A removed parameter keeps **no** shadow parameter that silently no-ops.
- Callers — validators, agent frontmatter, skills, docs, tests — are updated
  in the same change that renames the tool.
- If a rename breaks a caller that cannot be updated in the same change, the
  rename is not ready to land; it does not get a compatibility shim.

## 4. Current Findings

All findings below were measured against the **live** servers on 2026-11-07
(`/tmp/mcp_tool_dupes/probe_tools.py` — a real MCP `initialize` +
`tools/list` handshake against each of the five running servers). The live
surface is the ground truth: several of these facts are invisible to a source
scan because the tools are registered dynamically.

### 4.1 The fleet surface

| Server | Port | Tools | Unique | Shared |
|---|---|---|---|---|
| session-buddy | 8678 | 225 | 212 | 13 |
| mahavishnu | 8680 | 161 | 149 | 12 |
| crackerjack | 8676 | 53 | 43 | 10 |
| akosha | 8682 | 39 | 27 | 12 |
| oneiric | 8681 | 18 | 18 | 0 |
| **Total** | | **496** | **464** | **15 duplicate names** |

### 4.2 The names are already unique where uniqueness matters

The `mcp__<server>__<tool>` prefix is Claude Code's **config-entry
namespace** — derived from the MCP entry name, not from the tool name. So the
15 duplicated names are already 47 distinct registry entries. Verified on
four surfaces:

| Surface | Namespacing | Result |
|---|---|---|
| Claude Code tool registry | `mcp__<config-entry>__<tool>` | 47 distinct entries |
| `mahavishnu/core/skill_mcp_validator.py::KNOWN_TOOLS` | 103 entries, **103 namespaced, 0 bare** | no ambiguity |
| `.claude/agents/*.md` + `.claude/skills/*/SKILL.md` `Ecosystem:` frontmatter | 23 refs, **all namespaced** | no ambiguity |
| Live surface **within** each server | 0 duplicate registrations | no last-wins shadowing |

**There is no collision to fix.** The 15 names decompose into four classes
with very different costs, and only two of them are genuine defects.

### 4.3 Class A — one library, fanned out correctly (7 names × 4 servers)

`discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`,
`health_check_service`, `wait_for_dependency`, `wait_for_all_dependencies`.

Akosha, Crackerjack and Session-Buddy mount mcp-common's health toolkit;
their descriptions and schemas are byte-identical. **The duplicate name is
the correct outcome of a shared library** — each server should answer "how
am I?" with an identically-shaped tool. Renaming these would break the
consistency that makes the toolkit reusable.

### 4.4 Class B — same-name-per-service self-health (2 names)

`get_health` (akosha, mahavishnu, session-buddy) and `pycharm_health`
(akosha, crackerjack, mahavishnu). Each returns **its own** server's
snapshot; `get_health` deliberately routes through the same builder as the
HTTP `GET /health` route, per `docs/decisions/mcp-backend-wiring-discipline.md`.
Correct by design.

### 4.5 Class C — genuine cross-server redundancy (3 names)

- `track_channel_session`, `get_channel_sessions` — mahavishnu's description
  reads *"Delegates to Session-Buddy's track_channel_session MCP tool."*
- `query_local_traces` — crackerjack and mahavishnu are contract-identical;
  akosha's is a divergent superset.

### 4.6 Class D — coincidental collisions, different functions (3 names)

| Name | Server A | Server B |
|---|---|---|
| `detect_anomalies` | akosha: system-metric z-scores (`metric_name` required) | session-buddy: skill-usage performance (`threshold`, `time_window_hours`) |
| `find_path` | akosha: KG shortest path (`source_id`/`target_id`/`max_hops`) | session-buddy: DuckPGQ SQL/PGQ (`from_entity`/`to_entity`/`max_depth`) |
| `search_code` | crackerjack: regex (`pattern`/`file_pattern`) | session-buddy: semantic (`query`/`project`/`limit`) |

These are the only three where the same name genuinely means two different
things.

### 4.7 The real defect: descriptions that are empty

Four duplicated tools expose **no description at all**:

| Server | Tool | Source |
|---|---|---|
| crackerjack | `search_code` | `crackerjack/mcp/tools/pycharm_tools.py:227` |
| crackerjack | `pycharm_health` | `crackerjack/mcp/tools/pycharm_tools.py:345` |
| crackerjack | `query_local_traces` | `crackerjack/mcp/tools/otel_tools.py:65` |
| session-buddy | `search_code` | `session_buddy/mcp/tools/memory/search_tools.py:1630` |

This is the one place where a duplicate name defeats routing outright: the
model has an empty string to disambiguate with, and crackerjack's `search_code`
(regex) is indistinguishable from session-buddy's `search_code` (semantic).

Note also that session-buddy has a **second** `search_code` definition at
`session_buddy/tools/search_tools.py:46` that is **not** the registered copy
— `session_buddy/mcp/tools/__init__.py:72` imports `register_search_tools`
from `.memory.search_tools`. This is the dual-track registration hazard; the
live copy is the one in `mcp/tools/memory/search_tools.py`.

### 4.8 The root cause behind the Class-A block: mcp-common double-registers

`mcp_common/baseline_tools.py` registers `discover_tools`, `get_liveness`,
`get_readiness`, `health_check_all`.
`mcp_common/health/__init__.py` registers `health_check_service`,
`health_check_all`, `wait_for_dependency`, `wait_for_all_dependencies`,
`get_liveness`, `get_readiness`.

**The two modules overlap on `get_liveness`, `get_readiness` and
`health_check_all`.** `baseline_tools.py:500` acknowledges it: *"the same
shape `mcp_common.health.register_health_tools` uses."*

Crackerjack mounts **only** health, deliberately — `crackerjack/mcp/server_core.py:381`:

> `bootstrap_baseline_tools(mcp)` is intentionally NOT called here: adding it
> would either double-register get_liveness/get_readiness/health_check_all
> (shadowing the more comprehensive health tools also registered by
> register_health_tools) or replace the custom crackerjack_discovery-backed
> discover_tools …

**Session-Buddy mounts both.** `session_buddy/mcp/tools/profiles.py` registers
`register_baseline_tools` (line 254) *and* `register_health_tools_sb`
(line 257). The live `tools/list` shows one copy of each name — the health
implementation wins, confirmed by the served description matching
`health/__init__.py` rather than `baseline_tools.py` — but the baseline
copies are registered and shadowed on every session-buddy start.

### 4.9 Mahavishnu's vendored fork

`mahavishnu/mcp/tools/health_tools.py` diverges from
`mcp_common/health/__init__.py` by **1256 diff lines**. It registers the 6
shared health tools **plus** 3 Mahavishnu-specific ones (`mcp_list_tools`,
`mcp_test_connection`, `mcp_get_metrics`).

It also drifts on the parameter contract: mahavishnu's `health_check_service`
takes **`service_name`**, while mcp-common's takes **`service_name_arg`**.

That odd name exists for a closure-shadowing reason, not a collision reason —
`mcp_common/health/__init__.py:552` declares
`register_health_tools(mcp, service_name="mcp-server", …)`, so the enclosing
`service_name` shadows the tool's own parameter and forces the rename. The
leak into a public tool schema is avoidable by renaming the outer parameter.

Mahavishnu's fork additionally carries a **deprecation shim** that
mcp-common's does not: `_warn_deprecated_tool("health_check_service",
"health_check_all")`, resolved through `mahavishnu/mcp/tool_versions.py`,
per the deprecation plan in the fork's own module docstring (`health_check_service`,
`get_liveness` and `get_readiness` are slated for replacement by
`ecosystem_status`). **A de-vendor must carry this forward, not drop it.**

### 4.10 Two contract defects found in Class C

**`user_id` is fiction.** Mahavishnu's `track_channel_session`
(`mahavishnu/mcp/tools/session_buddy_tools.py:273`) and
`get_channel_sessions` (same file, line 345) both accept a `user_id`
parameter — and **never forward it**. The payload builder omits it entirely.

Nothing downstream has a `user_id`: session-buddy's `ChannelSessionEvent`
(`session_buddy/mcp/event_models.py:686`) carries `sender_id`, and
`_store.query()` filters on `channel_type`, `channel_id`, `sender_id`,
`session_scope` and `limit` only. So `user_id` is a filter that silently
returns unfiltered results.

**`token` is vestigial.** Session-Buddy's `get_channel_sessions`
(`session_buddy/mcp/tools/session/channel_tracking_tools.py:265`) accepts
`token` and never uses it — the function body ignores it and the decorator is
`@require_auth()`, which resolves identity from request context, not from a
parameter.

### 4.11 Stale references found en route (adjacent, not naming)

Eleven `KNOWN_TOOLS` entries and four agent-frontmatter references name tools
no live server serves:

| Stale reference | Live equivalent |
|---|---|
| `mcp__crackerjack__crackerjack_run` | `mcp__crackerjack__crackerjack_run_stage` |
| `mcp__mahavishnu__pool_execute` | `mcp__mahavishnu__pool_route_execute` |
| `mcp__mahavishnu__plan_list` | *no such tool* (`plan_capability` exists) |
| `mcp__mermaid__generate_mermaid_diagram` | *server not configured* |

*Caveat: crackerjack may run a narrower tool profile in some deployments, so
`crackerjack_run` may be profile-gated rather than removed. REQ-MCPTD-007's
guard must distinguish "profile-gated" from "gone" before anything is
renamed — the first is expected, the second is a stale reference.*

## 5. Requirements

See the frontmatter `requirements:` block. Summary:

| ID | Title | Primary repo |
|---|---|---|
| REQ-MCPTD-001 | Every Bodai core MCP tool carries a non-empty, rubric-compliant description | crackerjack |
| REQ-MCPTD-002 | Same-named tools expose an identical parameter contract across servers | session-buddy |
| REQ-MCPTD-003 | `query_local_traces` exposes one parameter contract across the fleet | akosha |
| REQ-MCPTD-004 | mcp-common exposes each health and baseline tool name exactly once | mcp-common |
| REQ-MCPTD-005 | Mahavishnu sources its health tools from mcp-common instead of a vendored fork | mahavishnu |
| REQ-MCPTD-006 | Tools whose names collide across components carry a component-scoped name | akosha |
| REQ-MCPTD-007 | A fleet-wide guard rejects duplicate names, empty descriptions and stale validator entries | mahavishnu |

## 6. Implementation Phases

Phases are ordered by value-per-line and by dependency: P0 and P1 are
independent and land first; P2 is the architectural change; P3 is the
user-visible rename and lands last, once the contracts behind it are stable;
P4 is the guard that keeps all four from regressing.

### Phase 0: Descriptions on the four blind-spot tools

**Goal:** every duplicated tool carries a description a model can route on.

**Tasks:**

1. Rewrite the descriptions of `crackerjack/mcp/tools/pycharm_tools.py:227`
   (`search_code`), `:345` (`pycharm_health`) and
   `crackerjack/mcp/tools/otel_tools.py:65` (`query_local_traces`) against the
   6-criterion rubric in `docs/decisions/tool-description-rubric.md`.
1. Rewrite the description of
   `session_buddy/mcp/tools/memory/search_tools.py:1630` (`search_code`).
1. Each description must state the **negative case** — for crackerjack's
   `search_code`, explicitly say semantic search lives on session-buddy; for
   session-buddy's, say regex search lives on crackerjack.
1. Confirm the *registered* session-buddy copy is
   `mcp/tools/memory/search_tools.py` and that
   `session_buddy/tools/search_tools.py:46` is not registered. If the second
   copy is reachable, delete it — it is a shadow, and per the dual-track
   memory its unit test proves nothing about the served surface.
1. Apply the same rubric to the four thin mahavishnu descriptions
   (`get_liveness`, `get_readiness`, `health_check_service`, `health_check_all`)
   while that file is open for Phase 2.

#### Integration Contract

- **Triggered from**: `mahavishnu mcp start` / `crackerjack mcp start` /
  session-buddy's `server_optimized.build_live_server()` — each server's
  tool-registration path; the descriptions reach the model through the
  `tools/list` `description` field.
- **Returns to / updates**: the `tools/list` payload served on ports
  8676 / 8678 / 8680. No persisted state.
- **Demonstrable by**: `scripts/check_mcp_tool_surface.py --describe` shows
  a non-empty description for all four tools; a `tools/list` probe against
  8676 returns a non-empty `description` for `search_code`.
- **Rollback signal**: the guard reports a description *length* drop below
  the floor for any tool whose description was non-empty before this phase.
- **Observability added**: the guard's `empty_descriptions` count is emitted
  as a CI-visible non-zero exit; per-tool description length is printed in
  `--describe` mode.

### Phase 1: Unify the parameter contracts

**Goal:** the same tool name accepts the same parameters on every server that
exposes it.

**Tasks:**

1. **Remove the `user_id` fiction** from mahavishnu's `track_channel_session`
   and `get_channel_sessions`
   (`mahavishnu/mcp/tools/session_buddy_tools.py:273` and `:345`). Per §2
   Policy, delete the parameter — do not map it, and do not keep a no-op
   shadow. `sender_id` is the identity filter session-buddy actually supports.
1. **Remove the vestigial `token` parameter** from session-buddy's
   `get_channel_sessions`
   (`session_buddy/mcp/tools/session/channel_tracking_tools.py:265`).
   `@require_auth()` resolves identity from request context.
1. **Unify `query_local_traces`.** Crackerjack and mahavishnu already agree
   (`task_class` required, `system_id`, `time_range_minutes`, `limit`).
   Akosha's variant (`start_time`/`end_time`/`dry_run`) is the richer one —
   align crackerjack and mahavishnu **up** to it, so the fleet-wide contract
   is the superset rather than the weaker pair. Update
   `akosha/mcp/tools/otel_tools.py:31`, `crackerjack/mcp/tools/otel_tools.py:65`
   and `mahavishnu/mcp/tools/otel_tools.py:257` together.
1. Confirm the alignment direction with the Akosha fitness analyzer, which
   polls mahavishnu's endpoint (`mahavishnu/mcp/tools/otel_tools.py:275`):
   the analyzer's poll must keep working after the contract change.

#### Integration Contract

- **Triggered from**: `mcp__mahavishnu__track_channel_session` /
  `mcp__mahavishnu__get_channel_sessions` (called by mahavishnu's
  `BodaiComponentMCPClient.call_tool` against session-buddy at
  `mahavishnu/mcp/bodai_component_client.py:99`);
  `mcp__akosha__query_local_traces` / `mcp__crackerjack__query_local_traces` /
  `mcp__mahavishnu__query_local_traces` (polled by Akosha's fitness analyzer).
- **Returns to / updates**: the channel-session store behind session-buddy's
  `_ChannelSessionStore`, and each server's OTel trace store. The mahavishnu
  proxy payload assembled at `session_buddy_tools.py:299-330`.
- **Demonstrable by**: `pytest tests/integration/mcp/test_channel_tracking.py`
  in session-buddy passes with `token` removed; a mahavishnu
  `get_channel_sessions` call with a `sender_id` returns only that sender's
  sessions; the fleet guard reports one `query_local_traces` schema across
  three servers.
- **Rollback signal**: the Akosha fitness analyzer's poll to mahavishnu's
  `query_local_traces` returns zero traces where it previously returned
  non-zero — that is a contract break in the superset direction.
- **Observability added**: the guard records a per-tool parameter signature
  hash; a change to a shared tool's signature is visible in the guard's diff
  output rather than in a production trace-count change.

### Phase 2: One registration per name, one implementation behind it

**Goal:** mcp-common exposes each health/baseline tool name exactly once, and
mahavishnu stops carrying a fork.

**Tasks:**

1. **Collapse the mcp-common overlap.** `mcp_common/baseline_tools.py` drops
   `get_liveness`, `get_readiness` and `health_check_all` — `health/__init__.py`
   owns them, and crackerjack's own comment establishes the health versions
   as the more comprehensive ones. `baseline_tools.py` keeps `discover_tools`,
   which is the part that carries per-tool `group` metadata.
   *Alternative (reject):* drop them from `health/` instead — rejected because
   three of four servers already mount `health/` for `health_check_service`,
   `wait_for_dependency` and `wait_for_all_dependencies`, so that path would
   have to grow.
1. **Un-shadow the `service_name` parameter.** Rename the outer parameter of
   `mcp_common/health/__init__.py:552`'s `register_health_tools` from
   `service_name` to `server_name`, so the tool's own parameter becomes
   `service_name` and the public schema stops leaking `service_name_arg`.
   Update the three callers: `akosha/mcp/tools/__init__.py`,
   `crackerjack/mcp/tools/health_tools_wrapper.py:60`, and session-buddy's
   health registration.
1. **Parameterize the deprecation shim.** Add an optional
   `deprecated_tools: Mapping[str, str] | None = None` argument to
   `register_health_tools`, mapping tool name → replacement name. Mahavishnu
   passes its `health_check_service` → `health_check_all` map. The warning is
   emitted only for names present in the map, so the other three servers stay
   warning-free.
1. **De-vendor mahavishnu.** Replace `mahavishnu/mcp/tools/health_tools.py`
   with a thin module that mounts `mcp_common.health.register_health_tools`
   with mahavishnu's dependency map and deprecation map, and keeps the three
   Mahavishnu-specific tools (`mcp_list_tools`, `mcp_test_connection`,
   `mcp_get_metrics`) — either in the same file or split into
   `mahavishnu/mcp/tools/connection_tools.py`. Register the new module in
   **all four** tables mahavishnu requires
   (`REGISTRATION_MAP`, `MAHAVISHNU_MANDATORY_GROUPS`, `PROFILE_REGISTRATIONS`,
   `_OPTIONAL_TOOL_BLOCKS`) — per the four-table drift memory, missing the
   fourth changes nothing on the live server.
1. **Stop session-buddy double-registering.** With baseline dropping the
   health trio, session-buddy's `register_baseline_tools` mount no longer
   overlaps `register_health_tools_sb`. Verify the served `get_liveness`
   description still comes from `health/__init__.py`.
1. **Reconcile `discover_tools`.** Mahavishnu's own `discover_tools`
   (`mahavishnu/mcp/server_core.py:1496`, params `capability` + `query`)
   differs from mcp-common's baseline `discover_tools` (param `query`). Keep
   mahavishnu's — it is the richer contract and is referenced by agent
   frontmatter. Do not fold it into the baseline.

#### Integration Contract

- **Triggered from**: each server's `build_live_server()` / tool-registration
  path — `mcp_common.server.launch` calls the `build_server` hook that
  session-buddy's `server_optimized.py` implements; mahavishnu's path is
  `lifecycle.py` → `register_profile_tools` → `_register_optional_tools` →
  `_OPTIONAL_TOOL_BLOCKS`.
- **Returns to / updates**: the registered tool surface on ports
  8676 / 8678 / 8680 / 8682. Specifically, `health_check_service`'s published
  input schema changes from `service_name_arg` to `service_name` on akosha,
  crackerjack and session-buddy.
- **Demonstrable by**: `mahavishnu mcp start --background && mahavishnu mcp call
  discover_tools '{}' | jq '.loaded_tools | length'` shows the expected count
  change (mahavishnu loses no tool — the fork and the shared implementation
  register the same 6 names); the fleet guard reports **one** implementation
  per health tool name and zero cross-module overlap.
- **Rollback signal**: any server's `tools/list` count drops by more than
  the expected delta, or `health_check_service` fails with "missing required
  parameter `service_name_arg`" — the latter means a caller was not updated
  in the same change.
- **Observability added**: the fleet guard reports, per shared tool name, the
  set of servers exposing it and the count of distinct implementations
  behind it. A count above 1 is a regression.

### Phase 3: Rename the three coincidental collisions

**Goal:** the three names that mean two different things become
component-scoped.

**Renames** (following the fleet's existing `<component>_<tool>` convention —
mahavishnu already ships `mahavishnu_get_agent`, `mahavishnu_kv_get`,
`mahavishnu_list_events`; session-buddy ships `session_buddy_get_skill`,
`session_buddy_list_agents`; crackerjack ships `crackerjack_analyze`,
`crackerjack_run_stage`):

| Current | Renamed to |
|---|---|
| `mcp__akosha__detect_anomalies` | `mcp__akosha__akosha_detect_anomalies` |
| `mcp__session-buddy__detect_anomalies` | `mcp__session-buddy__session_buddy_detect_anomalies` |
| `mcp__akosha__find_path` | `mcp__akosha__akosha_find_path` |
| `mcp__session-buddy__find_path` | `mcp__session-buddy__session_buddy_find_path` |
| `mcp__crackerjack__search_code` | `mcp__crackerjack__crackerjack_search_code` |
| `mcp__session-buddy__search_code` | `mcp__session-buddy__session_buddy_search_code` |

**Tasks:**

1. Rename in each repo's registration site and its function definition.
1. Update every caller in the same change:
   - `KNOWN_TOOLS` in `mahavishnu/core/skill_mcp_validator.py`
     (`mcp__akosha__detect_anomalies`, `mcp__akosha__find_path` and
     `mcp__crackerjack__search_code` are present; the three session-buddy
     names are not — add them while renaming so the validator covers the
     whole fleet).
   - Agent frontmatter `Ecosystem:` lines — `mcp__akosha__detect_anomalies`
     appears in 2 files; `find_path` and `search_code` appear in none, but
     re-grep after the rename rather than trusting this count.
   - All `docs/` references and the skill catalog.
1. Grep the whole ecosystem for the bare names, not just the namespaced
   form — a bare `search_code` in a doc or an agent body is now ambiguous.
1. Add the renamed session-buddy tools to `KNOWN_TOOLS` (they are absent
   today — see §4.11).

**Why the component prefix and not a semantic rename:** a semantic rename
(`find_graph_path` vs `find_entity_path`) is arguably more descriptive, but
it would not satisfy the Claude Code TUI picker, which prefix-matches on the
tool's registered name — the gap the `akosha-tool-naming-gap` memory records.
The component prefix is the convention three of four components already
follow, so it adds no new vocabulary. The semantic distinction (system
metrics vs skill usage; KG vs DuckPGQ; regex vs semantic) belongs in the
**description**, which Phase 0 already writes.

*Open question for review:* akosha does not prefix its other tools, so
`akosha_find_path` sits alongside bare `search_code_patterns` and
`analyze_trends`. Full akosha prefixing is a separate sweep (per the
`akosha-tool-naming-gap` memory) and is out of scope here. If the reviewer
prefers internal consistency within akosha over the picker benefit, the
alternative is a semantic rename — see §9 Decision Rule.

#### Integration Contract

- **Triggered from**: model tool selection — the renamed names appear in the
  `tools/list` payload on ports 8676 / 8678 / 8682.
- **Returns to / updates**: `KNOWN_TOOLS` (103 → 106 entries), agent
  frontmatter, the skill catalog, and every doc reference.
- **Demonstrable by**: the fleet guard reports zero duplicate bare names
  across the five servers; `mcp__akosha__akosha_find_path` and
  `mcp__session-buddy__session_buddy_find_path` both appear in their
  servers' `tools/list` and the old names appear in neither.
- **Rollback signal**: the guard reports a *new* duplicate, or an agent
  frontmatter reference resolves to a tool absent from `tools/list` — the
  latter means a model-visible routing hint was left dangling, which breaks
  agent selection rather than a build.
- **Observability added**: the guard's `duplicate_names` list is empty and is
  asserted in CI.

### Phase 4: The fleet-wide guard

**Goal:** the next duplicate fails the build instead of waiting to be found.

**Tasks:**

1. Add `scripts/check_mcp_tool_surface.py` to mahavishnu. It performs the
   same MCP `initialize` + `tools/list` handshake used to produce §4.1
   against every server listed in `settings/repos.yaml` (falling back to
   `settings/ecosystem.yaml`), and asserts:
   1. **no duplicate bare name** across servers, except the documented
      shared-library set (§4.3), which is asserted as an explicit allowlist;
   1. **no empty description** on any tool;
   1. **every `KNOWN_TOOLS` entry is served** by some live server, with
      profile-gated tools reported separately from genuinely stale ones
      (§4.11 caveat);
   1. **every same-named tool shares one parameter signature**, with an
      allowlist for the intentional per-service `get_health` / `pycharm_health`
      differences.
1. Add a test that runs the guard's pure analysis (no network) over a
   checked-in fixture of the five `tools/list` responses, so CI catches a
   duplicate even when the servers are down.
1. Wire the guard into Crackerjack's quality hooks
   (`crackerjack run -v -f`) as a fast check, and into the pre-push
   consolidation gate as a blocking stage.

#### Integration Contract

- **Triggered from**: `crackerjack run -v -f` (fast hooks) and the
  pre-push consolidation gate stage 4.5.
- **Returns to / updates**: a non-zero exit and a per-violation report on
  stdout; CI status.
- **Demonstrable by**: `python scripts/check_mcp_tool_surface.py` exits 0 on
  the current fleet; introducing a deliberately duplicated tool name in the
  fixture makes it exit 1 with the offending name listed.
- **Rollback signal**: the guard fails on a **live** fleet whose servers are
  simply down — the fixture-backed test is the authority in that case, and
  the live mode should skip (not fail) when a server is unreachable.
- **Observability added**: guard violations are logged with a
  `mcp_tool_surface_violations` counter, so a rise is visible without
  reading CI output.

## 7. Required Code Changes

```
mcp-common/
  mcp_common/health/__init__.py          # rename outer service_name → server_name; add deprecated_tools arg
  mcp_common/baseline_tools.py           # drop get_liveness, get_readiness, health_check_all

crackerjack/
  crackerjack/mcp/tools/pycharm_tools.py   # descriptions for search_code, pycharm_health
  crackerjack/mcp/tools/otel_tools.py      # description for query_local_traces; unify query_local_traces contract
  crackerjack/mcp/tools/health_tools_wrapper.py  # update for renamed register_health_tools signature

akosha/
  akosha/mcp/tools/otel_tools.py          # unify query_local_traces contract
  akosha/mcp/tools/akosha_tools.py         # rename detect_anomalies, find_path
  akosha/mcp/tools/__init__.py             # update register_health_tools call
  akosha/mcp/tools/pycharm_tools.py        # description for pycharm_health

session-buddy/
  session_buddy/mcp/tools/memory/search_tools.py       # description + rename search_code
  session_buddy/mcp/tools/session/channel_tracking_tools.py  # drop token; rename detect_anomalies, find_path
  session_buddy/mcp/tools/skills/phase4_tools.py        # rename detect_anomalies
  session_buddy/mcp/tools/collaboration/knowledge_graph_tools.py  # rename find_path
  session_buddy/mcp/tools/monitoring/health_tools.py     # update register_health_tools call
  session_buddy/mcp/tools/ide.py                         # update pycharm_health description if registered

mahavishnu/
  mahavishnu/mcp/tools/health_tools.py      # retire fork; mount mcp_common.health; keep 3 MV tools
  mahavishnu/mcp/tools/session_buddy_tools.py  # drop user_id; align channel-session contract
  mahavishnu/mcp/tools/otel_tools.py         # align query_local_traces contract
  mahavishnu/core/skill_mcp_validator.py     # update KNOWN_TOOLS for renames; add the 3 SB names
  scripts/check_mcp_tool_surface.py           # new — the fleet guard
  tests/fixtures/mcp_tool_surface/*.json      # new — checked-in tools/list responses
```

## 8. Validation Matrix

| Check | Expected outcome | Evidence location |
|---|---|---|
| Fleet guard, live mode | exit 0; 0 duplicate names, 0 empty descriptions | `python scripts/check_mcp_tool_surface.py` |
| Fleet guard, fixture mode | exit 0 against the checked-in fixture | `pytest tests/unit/mcp/test_mcp_tool_surface.py` |
| Guard catches a seeded duplicate | exit 1, names the offending tool | seeded fixture case |
| Mahavishnu tool count | unchanged from 161 (fork → shared impl, same 6 names) | `mahavishnu mcp call discover_tools '{}'` |
| Crackerjack tool count | unchanged from 53 | `tools/list` probe on 8676 |
| Session-Buddy tool count | unchanged from 225 | `tools/list` probe on 8678 |
| `health_check_service` schema | param is `service_name` on all four servers | `tools/list` probe, 8676/8678/8680/8682 |
| Channel-session contract | no `user_id` on MV; no `token` on SB | `tools/list` probe + `pytest tests/integration/mcp/test_channel_tracking.py` |
| `query_local_traces` contract | one schema across akosha, crackerjack, mahavishnu | `tools/list` probe, 8676/8680/8682 |
| Renamed tools | old names absent, new names present | `tools/list` probe, 8676/8678/8682 |
| Agent frontmatter | every `mcp__*` ref resolves to a served tool | guard, frontmatter section |
| Quality gate | `crackerjack run -v -f` passes on all touched repos | per-repo gate run |
| Requirements audit | no phantom requirement IDs | `python scripts/audit_requirements.py` |
| Orphan audit | no newly-added symbol without a caller | `python scripts/audit_orphans.py` |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A rename silently breaks agent selection — `.claude/agents/*.md` `Ecosystem:` lines are model-visible routing hints, so a dangling ref degrades routing without failing a build | High | Phase 4's guard resolves every frontmatter ref against the live surface and fails on a miss; Phase 3 re-greps after renaming rather than trusting the pre-rename count |
| Renaming `health_check_service`'s parameter breaks a caller that was not updated in the same change | Medium | The contract change is a breaking change per §2 Policy — no alias. The guard's parameter-signature check and the per-server `tools/list` probe catch the mismatch |
| De-vendoring mahavishnu's health fork loses the deprecation warnings | Medium | `deprecated_tools` is parameterized in the same change; a test asserts mahavishnu still warns on `health_check_service` |
| Session-Buddy's `discover_tools` changes shape when baseline stops registering the health trio | Low | Baseline never registered `discover_tools` differently — verify by probe before and after Phase 2 |
| The live `tools/list` is stale relative to the running server's code | Low | The probe performs a full `initialize` handshake; the guard distinguishes unreachable servers (skip) from served surfaces (assert) |
| A narrower tool profile in another deployment makes the guard's stale-reference check fire spuriously | Medium | The guard separates "profile-gated" from "gone" before reporting; §4.11's `crackerjack_run` is the worked example |
| The rename scope creeps to all 496 tools | Low | §3 Non-Goals names the sweep explicitly; the guard's allowlist is the only place a shared name is permitted |

## 10. Decision Rule

This plan is done when **all** of the following hold:

1. The fleet guard reports zero duplicate bare names, zero empty descriptions
   and zero stale `KNOWN_TOOLS` entries.
1. `mcp_common` exposes each health/baseline name exactly once, and
   mahavishnu's health tools come from it.
1. Every same-named tool shares one parameter contract, except the
   documented per-service exceptions.

**If scope pressure forces a cut**, cut in this order:

- **Cut P3 first** (the renames). They are the most user-visible and the
  highest blast radius; the fleet is unambiguous without them because the
  config-entry namespace already disambiguates. The *descriptions* (P0) carry
  most of the routing benefit at a fraction of the cost.
- **Then cut P4's live mode** and keep the fixture-backed test. The guard is
  what stops the next regression, but a fixture-only guard still catches
  duplicates introduced in a pull request.
- **Never cut P1's `user_id` removal.** It is a live correctness defect: a
  caller filtering by `user_id` silently receives unfiltered results. It is
  small, and it is wrong today.
- **Never cut P2's deprecation-shim parameterization.** Dropping it silently
  changes mahavishnu's operator-visible warnings.

**If the reviewer prefers akosha-internal consistency over the TUI picker
benefit** (the §6 Phase 3 open question), switch the three renames to a
semantic scheme — `detect_metric_anomalies` / `detect_skill_anomalies`,
`find_graph_path` / `find_entity_path`, `search_code_regex` /
`search_code_semantic` — and update the guard's allowlist accordingly. The
guard's invariant ("no bare name appears on two servers") holds under either
scheme; only the naming form changes.

## 11. Follow-ups explicitly out of scope

1. **Akosha's full component-prefix sweep** — akosha's other 37 tools remain
   bare. Tracked by the `akosha-tool-naming-gap` memory; a separate plan.
1. **The stale `KNOWN_TOOLS` / frontmatter references** in §4.11 — the guard
   (§6 Phase 4) *reports* them; the cleanup is a separate change once
   profile-gating is confirmed.
1. **The `mcp__<server>__` namespace itself** — protected by the
   `mcp-tool-namespace-is-config-entry` memory. Any future aggregator must
   preserve it or the 103 `KNOWN_TOOLS` entries, 268 executable/config
   references and 23 frontmatter hints all break at once.
