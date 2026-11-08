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
  title: Same-named tools document their parameter contract, including the auth parameters
  description: The channel-session tools accept different auth parameters on each server — user_id is the principal mahavishnu's RBAC gate authorizes against (caller-supplied; require_mcp_auth prefers the middleware's session context when it has one), token is the signed credential session-buddy pops and validates. Both are consumed by the tool decorators rather than the tool bodies, so each tool's docstring states which parameter is the auth parameter and which are query filters.
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

### 4.10 Two contract divergences found in Class C

> **Correction (2026-11-08).** An earlier draft of this section read the two
> channel-session tool *bodies* and concluded that `user_id` was a dead filter
> and `token` was vestigial. **Both conclusions were wrong**, and the plan
> originally scheduled their removal. The parameters are load-bearing — they
> are consumed by the *decorators*, not by the tool bodies:
>
> - Mahavishnu's `track_channel_session` and `get_channel_sessions` accept
>   `user_id`, which `require_mcp_auth` reads as the **authenticated
>   principal**. `mahavishnu/mcp/auth.py:183` resolves it from FastMCP
>   Context state first, then falls back to `kwargs.get("user_id")`.
>   Removing the parameter makes every call fail closed with
>   "Authentication required: user_id parameter missing".
> - Session-Buddy's `get_channel_sessions` accepts `token`, which
>   `require_auth` **pops from the call kwargs** and validates as a signed
>   credential (`session_buddy/mcp/auth.py:97-106`) before injecting the
>   caller's `user_id` into the wrapped function. It is the credential.
>
> Neither is a filter, so neither silently returns unfiltered results. The
> genuine divergence is that the two servers use **different auth contracts
> for the same tool names** — mahavishnu takes a principal *name*,
> session-buddy takes a signed *token*. That is an auth-model difference, not
> a naming bug; it is recorded as a follow-up (§11) rather than "fixed" here.
> The lesson generalises: **read the decorator before concluding a parameter
> is unused.**

**The `query_local_traces` divergence is real.** Four implementations of the
same tool name carry four different parameter contracts (akosha, crackerjack,
mahavishnu, session-buddy). Unlike the channel-session parameters, nothing
consumes these — they are plain query filters — so this one *is* unified in
Phase 1.

> **Correction (2026-11-08, post-merge).** Only **three** of the four are in
> a live surface. Session-buddy's `register_otel_trace_tools` is exported and
> unit-tested but never called from `session_buddy/server_optimized.py`, so
> `mcp__session-buddy__query_local_traces` has never existed — confirmed
> against the pre-merge inventory *and* the live `tools/list`. The divergence
> is therefore real in the source and latent in the served surface. Phase 1
> unified all four implementations; wiring session-buddy's is deliberately
> **not** done here — it adds a tool to a 225-tool live server, which is a
> surface change that wants its own review, not a side effect of a
> contract-alignment phase. Tracked in §11.

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

1. **Keep the channel-session auth parameters; document them instead.**
   `user_id` on mahavishnu's proxies is the principal the RBAC gate
   authorizes against (caller-supplied; see
   `docs/decisions/2026-10-29-learning-pipeline-tools-authz-block.md`) — read by
   `require_mcp_auth`; `token` on session-buddy's tool is the signed
   credential `require_auth` pops and validates (§4.10). Both are consumed
   by the decorators, so the tool bodies never see them. Update each
   tool's docstring to say so, so a caller does not read `user_id` as a
   query filter.
1. **Unify `query_local_traces`.** Four implementations of the name carry
   four different contracts; three of them are in a live surface (see the
   correction in §4.10). The fleet-wide contract is akosha's richer set,
   with `task_class` promoted to required:

   ```python
   query_local_traces(
       task_class: str,
       system_id: str | None = None,
       start_time: str | None = None,   # ISO8601, absolute
       end_time: str | None = None,     # ISO8601, absolute
       limit: int = 100,
       dry_run: bool = False,
   ) -> list[dict]
   ```

   `time_range_minutes` is **removed** from the tool contract rather than
   kept alongside the absolute window — two window conventions on one tool
   is the dual-API smell §2 Policy rejects. The relative window survives
   where it belongs, in the *client helpers*
   (`mahavishnu/mcp/bodai_component_client.py:114` and
   `akosha/mcp/client.py:58`), which convert it to an absolute window on the
   wire. Update `akosha/mcp/tools/otel_tools.py:31`,
   `crackerjack/mcp/tools/otel_tools.py:65`,
   `mahavishnu/mcp/tools/otel_tools.py:257` and
   `session_buddy/mcp/tools/memory/otel_trace_tools.py:78` together.
1. **`dry_run` is a shape switch, not a scope switch.** It returns the raw
   stored metadata instead of the full record and clamps `limit` — it does
   **not** disable the `system_id` / `task_class` filters. Akosha's
   pre-existing `dry_run` *did* disable them, and aligning the fleet
   propagated that escape hatch to three more servers; a caller-supplied
   flag that switches off scoping is a real weakness on a tool that carries
   no authentication of its own. Rows outside a filter are reachable by
   omitting `system_id`, which is the documented all-systems query.
1. Confirm no caller is left on the old shape. The Akosha fitness analyzer
   does **not** poll this tool — it reads the local `spans_substrate` table
   (`akosha/processing/fitness_analyzer.py:160`), and its
   `akosha/mcp/client.py` helper has no importers. The two helpers that do
   exist (`akosha/mcp/client.py:59` and
   `mahavishnu/mcp/bodai_component_client.py:115`) are the conversion
   points, so the grep is over their *callers*, not over the fitness
   analyzer.

#### Integration Contract

- **Triggered from**: `mcp__akosha__query_local_traces` /
  `mcp__crackerjack__query_local_traces` /
  `mcp__mahavishnu__query_local_traces` (and its siblings on akosha,
  crackerjack and session-buddy);
  `mcp__mahavishnu__track_channel_session` /
  `mcp__mahavishnu__get_channel_sessions` (called by mahavishnu's
  `BodaiComponentMCPClient.call_tool` against session-buddy at
  `mahavishnu/mcp/bodai_component_client.py:99`).
- **Returns to / updates**: each server's OTel trace store; the
  channel-session store behind session-buddy's `_ChannelSessionStore`.
- **Demonstrable by**: `pytest tests/integration/mcp/test_channel_tracking.py`
  in session-buddy still passes with `token` present; a mahavishnu
  `get_channel_sessions` call with a `sender_id` returns only that sender's
  sessions; the fleet guard reports one `query_local_traces` schema across
  the servers that expose it.
- **Rollback signal**: a caller of either client helper starts receiving an
  "unexpected keyword argument" from the server — that is the wire contract
  breaking in the superset direction. (There is no live consumer to watch,
  so the tripwire is the error, not a trace count.)
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

**Resolved (2026-11-08).** The operator chose the **component-prefix** form
and extended the convention to **every Bodai-maintained repo**, not just the
three that already follow it. The canonical rule is recorded in
`docs/decisions/2026-11-08-mcp-tool-component-prefix-convention.md`.

Consequences for this plan:

- Akosha's remaining 37 bare tools become in scope for a fleet-wide sweep,
  tracked as Phase 5 (§6) and as a follow-up in §11.
- The rename table above is the **first tranche**: the three coincidental
  collisions, renamed to `akosha_*` / `session_buddy_*` / `crackerjack_*`.
- Every later tranche follows the same rule, so the fleet converges on one
  convention rather than two.

Akosha's internal inconsistency during the transition (prefixed
`akosha_find_path` alongside bare `search_code_patterns`) is temporary and
resolves when Phase 5 lands.

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

### Phase 5: Fleet-wide component-prefix sweep

**Goal:** every Bodai-maintained repo exposes only component-prefixed tool
names, so the Claude Code TUI picker can filter by component and no future
aggregator can flatten two tools onto one name.

**Tasks:**

1. Enumerate the repos in scope: mahavishnu, akosha, session-buddy,
   crackerjack, oneiric, mcp-common, plus any other Bodai-maintained MCP
   server. Confirm the list against `settings/repos.yaml` rather than
   assuming.
1. For each server, prefix every tool that is not already prefixed:
   akosha's 37 bare tools are the largest tranche; mahavishnu, session-buddy
   and crackerjack are mostly done already.
1. Apply the rename as a **function-name** change plus the `@tool(name=...)`
   override where the function name cannot move (the `name=` override is
   non-breaking for callers that import the function, and is the form the
   `akosha-tool-naming-gap` decision recommends for the short term).
1. Update `KNOWN_TOOLS`, agent frontmatter, skills, docs and tests in the
   same change — no aliases, per §2 Policy.
1. Leave the shared names **unprefixed** — the twelve in
   `docs/decisions/2026-11-08-mcp-tool-component-prefix-convention.md`:
   the seven mcp-common baseline names (`get_liveness`, `get_readiness`,
   `health_check_all`, `health_check_service`, `wait_for_dependency`,
   `wait_for_all_dependencies`, `discover_tools`), plus `query_local_traces`
   (the fleet-wide trace contract), `get_health` (each server's own
   health), `pycharm_health` (all three proxy the same PyCharm MCP server),
   and `track_channel_session` / `get_channel_sessions` (mahavishnu's
   client speaks these to session-buddy over the wire). The first seven
   are one library fanned out across servers; the other five are shared
   contracts that mean the same thing on every server that has them.
   Prefixing any of the twelve breaks a contract between servers, not just
   a name. Record them in the guard's allowlist as the shared set.

   *(Widened from seven to twelve on 2026-11-08: the first sweep drafts
   renamed `query_local_traces`, `get_health` and `pycharm_health` along
   with everything else.)*

#### Integration Contract

- **Triggered from**: each server's tool-registration path.
- **Returns to / updates**: the `tools/list` payloads on every Bodai port;
  `KNOWN_TOOLS`; agent frontmatter; the skill catalog.
- **Demonstrable by**: the fleet guard reports every tool name as
  component-prefixed, except the shared-baseline allowlist; typing
  `/ak` in the Claude Code TUI picker surfaces akosha's tools.
- **Rollback signal**: the guard reports a bare name outside the allowlist.
- **Observability added**: the guard's `unprefixed_tools` count (outside the
  allowlist) is asserted to be zero.

## 7. Required Code Changes

```
mcp-common/
  mcp_common/health/__init__.py          # rename outer service_name → server_name; add deprecated_tools arg
  mcp_common/baseline_tools.py           # drop get_liveness, get_readiness, health_check_all

crackerjack/
  crackerjack/mcp/tools/pycharm_tools.py   # descriptions for search_code, pycharm_health
  crackerjack/mcp/tools/otel_tools.py      # description for query_local_traces; unify query_local_traces contract
  crackerjack/tests/unit/mcp/test_otel_tools_query_local_traces.py  # dry_run forwarding pin
  crackerjack/mcp/tools/health_tools_wrapper.py  # update for renamed register_health_tools signature

akosha/
  akosha/mcp/tools/otel_tools.py          # unify query_local_traces contract
  akosha/mcp/client.py                     # relative window -> absolute window on the wire
  akosha/tests/unit/test_mcp_client.py      # new — the helper's conversion had no test
  akosha/mcp/tools/akosha_tools.py         # rename detect_anomalies, find_path
  akosha/mcp/tools/__init__.py             # update register_health_tools call
  akosha/mcp/tools/pycharm_tools.py        # description for pycharm_health

session-buddy/
  session_buddy/mcp/tools/memory/search_tools.py       # description + rename search_code
  session_buddy/mcp/tools/session/channel_tracking_tools.py  # document token as the credential; rename detect_anomalies, find_path
  session_buddy/mcp/tools/skills/phase4_tools.py        # rename detect_anomalies
  session_buddy/mcp/tools/collaboration/knowledge_graph_tools.py  # rename find_path
  session_buddy/mcp/tools/monitoring/health_tools.py     # update register_health_tools call
  session_buddy/mcp/tools/ide.py                         # update pycharm_health description if registered

mahavishnu/
  mahavishnu/mcp/tools/health_tools.py      # retire fork; mount mcp_common.health; keep 3 MV tools
  mahavishnu/mcp/tools/session_buddy_tools.py  # document user_id as the principal; align channel-session contract
  mahavishnu/mcp/tools/otel_tools.py         # align query_local_traces contract
  mahavishnu/core/skill_mcp_validator.py     # update KNOWN_TOOLS for renames; add the 3 SB names
  mahavishnu/mcp/tool_versions.py             # query_local_traces 1.0.0 -> 2.0.0 (removed field = MAJOR)
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
| Channel-session contract | `user_id` still accepted on MV (the RBAC principal) and `token` on SB (the credential); each docstring says which is which | `tools/list` probe + `pytest tests/integration/mcp/test_channel_tracking.py` |
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
- **Never cut P1's `query_local_traces` unification.** It is the one place
  where the same tool name genuinely means four different things, and it
  breaks a caller that learned one server's shape. It is also the change
  with a live consumer — the Akosha fitness analyzer.
- **Never cut P2's deprecation-shim parameterization.** Dropping it silently
  changes mahavishnu's operator-visible warnings.

**Naming scheme (resolved 2026-11-08).** The component-prefix form is
settled: `akosha_detect_anomalies` / `session_buddy_detect_anomalies`,
`akosha_find_path` / `session_buddy_find_path`,
`crackerjack_search_code` / `session_buddy_search_code`. The semantic
alternative (`detect_metric_anomalies`, `find_graph_path`,
`search_code_regex`) is **not** used. The guard's invariant ("no bare name
appears on two servers") holds under either scheme; only the naming form
changes, and the prefix form is the one the Claude Code TUI picker
prefix-matches on.

## 11. Follow-ups explicitly out of scope

1. **The trace tools have no authentication.** `query_local_traces` is
   registered without an auth decorator on every server, so `system_id` and
   `task_class` are **query filters, not authorization boundaries** — a
   caller can already pass any `system_id` it likes. That is why Phase 1
   keeps `system_id` optional (it is akosha's pre-existing, documented
   reference contract) and only removes the `dry_run` escape hatch. If
   per-caller scoping is wanted, it needs an authenticated principal and a
   caller→system mapping — a separate piece of work, not a parameter change.
   See `docs/decisions/2026-10-29-learning-pipeline-tools-authz-block.md`,
   which records the same class of gap for `require_mcp_auth` and
   deliberately defers the fleet-wide fix.
2. **Session-Buddy's all-systems path needs the semantic index.** — RESOLVED
   (2026-11-08).
   The tool was never in a live surface, so the index-dependent all-systems
   path was latent. It is now mounted and rewritten: session-buddy's
   `query_local_traces` no longer runs a similarity or text search at all.
   It reads the store directly through a new adapter method
   (`query_conversations_by_classification`), so the all-systems query is a
   plain filtered read with no dependency on the embedding chain.
3. **Session-Buddy's `query_local_traces` is never registered.** — RESOLVED
   (2026-11-08, `33060bd1`).
   The tool is mounted through `REGISTRATION_MAP` (so the profile dispatch
   owns it — FULL tier, never double-registered) and the live FULL surface
   is 226 tools. Wiring it exposed that the old implementation could not
   have worked: it passed `system_id` to `search_conversations(query=...)`,
   which is a CONTENT LIKE search rather than a provenance filter, and the
   all-systems query passed an empty query, which the adapter's text path
   treats as "matches nothing".

   What session-buddy actually stores is now stated in the tool's own
   description rather than left to be discovered: it has no local
   OpenTelemetry span store. It emits spans to the fleet collector and keeps
   its own records in the reflection database, so `task_class` matches a
   memory classification (`facts`, `context`) and `system_id` matches the
   working directory the writing session ran in. A `task_class` from the OTel
   taxonomy matches nothing there, which is an accurate answer rather than a
   bug.
4. **The fleet-wide schema-parity guard (REQ-MCPTD-007) is still Phase 4.**
   Nothing currently stops the `query_local_traces` signatures drifting
   apart again — the guard that would is a Phase-4 deliverable.
5. **The channel-session auth contract divergence.** `track_channel_session`
   and `get_channel_sessions` take different auth parameters on mahavishnu
   (`user_id`, a principal name) than on session-buddy (`token`, a signed
   credential). That is an auth-model difference, not a naming bug, and it
   is why Phase 1 documents the parameters instead of unifying them. Worth
   a separate decision on whether the two servers should converge on one
   credential model. See §4.10.
6. **Akosha's full component-prefix sweep** — akosha's other 37 tools remain
   bare. Tracked by the `akosha-tool-naming-gap` memory; a separate plan.
7. **The stale `KNOWN_TOOLS` / frontmatter references** in §4.11 — the guard
   (§6 Phase 4) *reports* them; the cleanup is a separate change once
   profile-gating is confirmed.
8. **The `mcp__<server>__` namespace itself** — protected by the
   `mcp-tool-namespace-is-config-entry` memory. Any future aggregator must
   preserve it or the 103 `KNOWN_TOOLS` entries, 268 executable/config
   references and 23 frontmatter hints all break at once.
