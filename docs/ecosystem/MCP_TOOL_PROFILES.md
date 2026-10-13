# MCP Tool Profiles — Bodai Ecosystem Reference

> Generated 2026-10-13 by `scripts/generate_tool_profiles_doc.py` against the 21 adopter repos that have `apply_tool_profile()` wired. Source of truth: each repo's `mcp/tools/profiles.py` (Tier-A) or `<pkg>/tools/profiles.py` (Tier-B + Bodai-maintained); this file is regenerated on every script run — do not edit by hand.

## Substrate

`mcp_common.tools.dispatch._apply_tool_profile` (async) and `mcp_common.tools.dispatch.apply_tool_profile` (sync, raises in async contexts) are the canonical helpers. The 21 adopter repos below all call the W0 helper from their `server.py` (or equivalent) startup path. `mcp-common` itself is the substrate where the helper lives — it is NOT in the per-repo table.

## Tier-A core Bodai (4 repos)

The four core Bodai components. Each repo's `profiles.py` docstring links to this cross-ecosystem doc (Tier-A is allowed to reference Mahavishnu per `feedback-no-bodai-mentions-in-mcp-repos`).

| Repo | Env var | Default | Groups |
|---|---|---|---|
| `mahavishnu` | `MAHAVISHNU_TOOL_PROFILE` | `FULL` | _register_otel_tools, _register_self_improvement_tools, _register_clone_tools, _register_goal_team_tools, _register_treesitter_tools, _register_pycharm_tools, _register_search_tools, _register_plan_tools, jot_list, jot_show, jot_add, jot_edit, jot_done, jot_reopen, jot_vitals, jot_search, jot_drain, jot_dispatch, jot_defer, jot_delete, jot_retry, jot_resurface |
| `akosha` | `AKOSHA_TOOL_PROFILE` | `FULL` | register_session_buddy_tools, register_pycharm_tools, register_otel_query_tools, register_fitness_tools, register_eventbridge_tools, register_cross_repo_tools, register_ecosystem_skills |
| `session-buddy` | `SESSION_BUDDY_TOOL_PROFILE` | `FULL` | 3/15/0 |
| `crackerjack` | `?` | `FULL` | eventbridge_tools, language_tools, monitoring_tools, otel_tools, progress_tools, proactive_tools, pycharm_tools, semantic_tools |

## Tier-B MCP servers (15 repos)

Third-party `*-mcp` servers. Each repo's own `profiles.py` is the source of truth for that repo's profile surface; this cross-ecosystem doc is **not** referenced from Tier-B per `feedback-no-bodai-mentions-in-mcp-repos` (Tier-B `*-mcp` repos are NOT Bodai ecosystem members).

| Repo | Env var | Default | Groups |
|---|---|---|---|
| `graphics-mcp` | `GRAPHICS_TOOL_PROFILE` | `FULL` | universal_tools, raster_tools |
| `langsmith-mcp` | `LANGSMITH_TOOL_PROFILE` | `FULL` | 0/0/0 |
| `synxis-crs-mcp` | `SYNXIS_CRS_TOOL_PROFILE` | `FULL` | crs_tools |
| `unifi-mcp` | `UNIFI_TOOL_PROFILE` | `FULL` | 0/0/0 |
| `css-mcp` | `CSS_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `excalidraw-mcp` | `EXCALIDRAW_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `neo4j-mcp` | `NEO4J_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `penpot-api-mcp` | `PENPOT_API_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `porkbun-dns-mcp` | `PORKBUN_DNS_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `porkbun-domain-mcp` | `PORKBUN_DOMAIN_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `raindropio-mcp` | `?` | `FULL` | health_tools |
| `synxis-pms-mcp` | `SYNXIS_PMS_TOOL_PROFILE` | `FULL` | 1/0/0 |
| `mailgun-mcp` | `?` | `FULL` | suppression_tools, webhook_tools |
| `opera-cloud-mcp` | `OPERA_CLOUD_TOOL_PROFILE` | `FULL` | 0/0/0 |
| `spline-mcp` | `SPLINE_TOOL_PROFILE` | `FULL` | integration_tools |

## Bodai-maintained `*-mcp` (2 repos as of 2026-10-13)

Bodai-managed `*-mcp` servers that wire `apply_tool_profile`. These follow the Tier-A cross-link policy (Bodai members MAY reference Mahavishnu) and link to this doc from their own `profiles.py` docstring.

| Repo | Env var | Default | Groups |
|---|---|---|---|
| `cmux-mcp` | `CMUX_TOOL_PROFILE` | `FULL` | socket_tools, browser_tools |
| `chat-bridge-mcp` | `CHAT_BRIDGE_TOOL_PROFILE` | `FULL` | chat_bridge_tools |

## Tier-C MCP servers (3 repos — NOT wired)

`profiles.py` exists on disk but `apply_tool_profile` wiring is not yet verified. Excluded from the 21-adopter count. Re-run this script after Plan 9 (or the equivalent) wires the missing calls — Tier-C repos move to `Bodai-maintained \`-mcp\`` once `apply_tool_profile` is callable from their `server.py` startup.

| Repo | Status |
|---|---|
| `archive-org-mcp` | not wired |
| `medium-mcp` | not wired |
| `scapy-mcp` | wired |

## Per-profile mandatory groups

The Tier-A repos expose the conventional 3-tier model (`MINIMAL` / `STANDARD` / `FULL`). The Tier-B and Bodai-maintained repos are 2-tier (typically `MINIMAL` + `FULL`) because their tool surface is small enough that a `STANDARD` tier adds no value.

| Profile | Tier-A repos | Tier-B + Bodai-maintained repos |
|---|---|---|
| `MINIMAL` | health probes + always-on infrastructure (per-repo specifics vary) | empty (only `discover_tools` meta-tool + `/health` route) |
| `STANDARD` | MINIMAL + management surfaces (terminal, pool, worker, messaging) | not used (Tier-B + Bodai-maintained skip STANDARD) |
| `FULL` | STANDARD + everything else (analytics, OTel, PyCharm, treesitter, plan/jot/clone tools) | all tool groups |

## How to override

| Need | Env var | Effect |
|---|---|---|
| Disable optional tools | `<REPO>_TOOL_PROFILE=standard` | registers only the management/infra groups |
| Force minimal | `<REPO>_TOOL_PROFILE=minimal` | registers only the health + always-on infrastructure groups |

## How to add a new tool to a profile

1. Add the tool to the appropriate group in `<repo>/<package>/mcp/tools/<group>.py` (Tier-A) or `<repo>/<package>/tools/<group>.py` (Tier-B + Bodai-maintained).
2. Add the group to `STANDARD_REGISTRATIONS` or `FULL_REGISTRATIONS` in the repo's `profiles.py`.
3. Re-run `python scripts/generate_tool_profiles_doc.py` to refresh this file.

## How to add a new Bodai-maintained `*-mcp`

1. Wire `_apply_tool_profile` (or `apply_tool_profile` in a sync context) from the new repo's `server.py` startup path.
2. Move the repo entry from Tier-C to `Bodai-maintained \`-mcp\`` in `REPO_LIST`.
3. Re-run `python scripts/generate_tool_profiles_doc.py`.

