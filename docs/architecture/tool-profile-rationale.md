# Mahavishnu MCP Tool Profile — Rationale (W1.1 backfill, 2026-08-18)

**Status:** Backfilled 2026-08-19 (post-W1.1 wave; this doc was absent during the
original W1.1 dispatch because the rationale-doc convention was formalized
during W2+).

**Wave:** W1 (backfill) — adopted `apply_tool_profile()` before the formal plan.
**Helper:** `mcp_common.tools.dispatch._apply_tool_profile` (mcp-common 0.18.0+).
**Env var:** `MAHAVISHNU_TOOL_PROFILE` (defaults to `FULL` — preserves v1.x
backward compatibility for every existing operator).

## Context

Mahavishnu is the Bodai ecosystem orchestrator (port 8680). Its MCP server
exposes ~180 decorated tools across 17 profile-gated groups plus inline core
tools (`list_repos`, `trigger_workflow`, `get_health`, etc.) that are always
registered. Without profile gating, every consuming LLM pays context cost for
every group regardless of operational mode. Pre-W1, all 17 groups were
registered unconditionally — a known context-bloat hot spot.

W1.1 backfilled the W0 helper from mcp-common so operators can dial down tool
surface to the operational mode they actually need (CI probe vs. full
orchestration).

## Profile Tiers

Defined in `mahavishnu/mcp/tools/profiles.py`:

| Tier | Groups included | Operator profile |
|------|-----------------|------------------|
| **MINIMAL** | `health_tools` | K8s liveness probe, read-only monitoring |
| **STANDARD** | MINIMAL + `terminal`, `pool`, `worker`, `worker_contract`, `repository_messaging`, `git_analytics`, `session_buddy`, `openhands`, `primitive` | Day-to-day orchestration |
| **FULL** | STANDARD + `otel`, `self_improvement`, `clone`, `goal_team`, `treesitter`, `adapter_registry`, `pycharm` | Full power-user / dev mode |

Inline core tools in `_register_tools()` (e.g. `list_repos`, `trigger_workflow`)
remain at every profile — they are the workflow primitives the orchestrator
itself depends on.

`register_worktree_tools` is intentionally NOT in any profile tier because it
is gated by `WorktreeCoordinator` runtime state, not by profile.

## Why these groupings

- **Health/Session/Webhook** — added to `MAHAVISHNU_MANDATORY_GROUPS` so they
  register at every profile. K8s probes, load balancers, and Mahavishnu's own
  async workflows depend on them being reachable from MINIMAL.
- **MINIMAL = `health_tools`** — chosen so any Tier-A MCP client (or a fresh
  LLM context) can probe ecosystem health without paying for ~170 irrelevant
  tool schemas.
- **STANDARD** — chosen to cover daily dev work: pools, workers, terminals,
  repos. Any operator running `mahavishnu pool route` needs this set.
- **FULL** — gates the heavy / experimental / niche tools (OTel, adapter
  introspection, PyCharm IDE bridge). These pay context cost and are only
  relevant when explicitly needed.

## Configuration Precedence

1. `MAHAVISHNU_TOOL_PROFILE` env var (preferred).
1. `tool_profile` in `settings/local.yaml` (Oneiric layered config).
1. Default `FULL` — preserves v1.x behavior; every existing operator keeps
   every tool unless they opt in to a smaller profile.

Loaded via `settings_yaml_loader()` in `tools/profiles.py`. The loader uses
`mahavishnu.core.config.get_settings().tool_profile` and is best-effort (any
exception → loader returns `None` and the W0 helper falls back to env or default).

## Cross-Repo Considerations

- **Mandatory groups rename (W0.5 split):** Pre-W0.5, mahavishnu declared
  `MAHAVISHNU_MANDATORY_TOOLS` which conflated "always-on group keys" with
  "subset-check tool names". W0.5 split renamed it to
  `MAHAVISHNU_MANDATORY_GROUPS` (dispatch driver) and the subset check moved
  to a separate `essential_tool_names` parameter on the W0 helper. The live
  set still contains the four infrastructure-critical groups.
- **Back-reference trick:** The W0 helper's `REGISTRATION_MAP` requires callables
  taking `(FastMCP) -> None`, but mahavishnu's per-group functions take the
  `FastMCPServer` wrapper. The `_mhv_server` back-reference (set in
  `FastMCPServer.__init__`) is how the lambda adapters recover the wrapper
  for each call. This pattern is unique to repos where the per-group functions
  expect a non-FastMCP object.

## Tests

`mahavishnu/tests/unit/test_wiring.py` — AST guard + golden-fixture comparisons
at MINIMAL/STANDARD/FULL + parameterized `MANDATORY_GROUPS ⊆ REGISTRATION_MAP`
invariants. Plus the existing `test_mcp_profiles.py` regression suite.

## References

- Master plan: `docs/superpowers/plans/2026-08-18-mcp-tool-profile-adoption.md`
- Helper source: `/Users/les/Projects/mcp-common/mcp_common/tools/dispatch.py`
- Profiles module: `mahavishnu/mcp/tools/profiles.py`
- Per-group bootstrap functions: `mahavishnu/mcp/bootstrap.py`
