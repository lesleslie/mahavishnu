---
status: active
role: implementation
kind: plan
date: 2026-11-07
last_reviewed: 2026-11-07
superseded_by: null
blocks_on: []
related:
  - docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md
  - docs/specs/2026-10-15-bifrost-gateway-wiring-design.md
  - config/bifrost/README.md
  - mahavishnu/bifrost/cache_headers.py
  - mahavishnu/core/skill_mcp_validator.py
  - ~/.claude/scripts/mcp-launchd/mcp-ctl.sh
replaces: docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md
topic: mcp-profile-groups
title: "MCP profile groups + shared LLM egress — replacing MCP aggregation"
requirements:
  - id: REQ-MCP-001
    title: "Checked-in MCP server registry is the single source of truth"
  - id: REQ-MCP-002
    title: "Named MCP profiles group servers for task-shaped work"
  - id: REQ-MCP-003
    title: "mahavishnu mcp CLI exposes list/profile/use/sync/status"
  - id: REQ-MCP-004
    title: "Profile activation writes one config entry per server, preserving tool names"
  - id: REQ-MCP-005
    title: "Multi-harness config writing across Claude Code, Codex, Qwen, Gemini, Goose, OpenCode"
  - id: REQ-MCP-006
    title: "Per-server tool-profile gating bounds each profile's tool surface"
  - id: REQ-MCP-007
    title: "Per-upstream health status replaces aggregator telemetry"
  - id: REQ-MCP-008
    title: "MCP servers share Bifrost semantic cache for internal LLM egress"
  - id: REQ-MCP-009
    title: "Registration tables derive from the registry, ending four-table drift"
---

# MCP profile groups + shared LLM egress — replacing MCP aggregation

> **Plan scope**: replace the superseded plan's *MCP aggregation* phase with
> **configuration-time profile groups** — named sets of MCP servers (`web-dev`,
> `bodai-full`, …) that an operator activates per project — and route the MCP
> fleet's **internal LLM egress** through Bifrost so those servers share one
> semantic cache. Definitions live in this repo. Bifrost's MCP gateway is
> retired from the MCP path; Bifrost keeps its LLM-gateway role.

## 1. Outcome

When this plan ships:

- **One checked-in registry** (`config/mcp/servers.yaml`) names every MCP server
  the fleet knows about, with URL, transport, health expectation, and per-server
  tool-profile env.
- **Named profiles** group those servers for task-shaped work. A `web-dev`
  profile (chrome-devtools, playwright, a fetch server) is what a fastblocks or
  splashstand session runs with; a `bodai-full` profile is the whole Bodai set.
- **One operator surface**: `mahavishnu mcp list | profile | use | sync | status`.
  MCPM is a *library dependency* behind it, not a runtime process and not a CLI
  the operator invokes.
- **Profile activation writes one config entry per member server**, using each
  server's original transport. The `mcp__<server>__<tool>` namespace is
  preserved exactly — no aggregation, no rename, no new proxy hop.
- **The tool surface is bounded by the profile, not by the fleet.** Today the
  five Bodai servers expose **496** tools (331 KB of schema) because every
  server runs at `TOOL_PROFILE=full`. A profile cuts that to the subset the
  task needs.
- **The fleet's internal LLM calls share Bifrost's semantic cache** under one
  bucket, so a repeated prompt across servers is served from cache.
- **The superseded plan is closed.** Its Phase 2 (MCP aggregation) and its
  Bifrost-MCP-gateway premise are retired with evidence, not deferred.

**Proof it worked**:

- `mahavishnu mcp profile show web-dev` lists its members with URLs.
- After `mahavishnu mcp use web-dev` in a consumer repo, that repo's MCP
  config contains exactly the profile's members — one entry each, `url`
  preserved — and the session exposes `mcp__<server>__<tool>` names unchanged.
- `mahavishnu mcp status` reports per-server reachability for every registry
  entry.
- A repeated internal LLM prompt from two different Bodai servers is served
  from the Bifrost semantic cache (one write, one hit), evidenced by
  `x-bifrost-cache-*` response headers.

## 2. Goals

1. **Make the tool surface task-shaped.** Group servers so a session sees the
   tools it needs instead of all 496.
2. **Preserve the `mcp__<server>__<tool>` contract.** It is load-bearing for
   268 executable/config references, 525 doc mentions, and
   `mahavishnu/core/skill_mcp_validator.py`'s exact-match `KNOWN_TOOLS`
   frozenset (105 entries) which fails agent/skill validation on any rename.
3. **One operator surface** for MCP server configuration across every harness
   this Mac runs (Claude Code, Codex CLI, Qwen CLI, Gemini CLI, Goose,
   OpenCode, …), matching the existing `mahavishnu bifrost <cmd>` convention.
4. **Share Bifrost's semantic cache across the fleet's internal LLM egress** —
   the real, already-partially-built caching win.
5. **End the four-table registration drift** (`mcp-ctl.sh` 16 entries,
   `mcp-supervisor.sh` 18, repo `.mcp.json` 17, ~20 installed plists, with
   `oneiric` in none of the registries) by making the registry authoritative
   and the generators derive from it.
6. **Keep failures loud.** A dead upstream must fail at session start, naming
   the server — not silently disappear from a `tools/list` that returns 200.

## 3. Non-Goals

- **Runtime MCP aggregation.** No single-endpoint proxy. Rejected with
   evidence: every aggregator renames tools (`<client>-<tool>` in Bifrost,
   `<prefix>_<tool>` in MCPM/FastMCP), which breaks the contract above; the
   `__` server segment is Claude Code's *config-entry* namespace and no
   protocol mechanism can inject it per-tool.
- **Bifrost as the MCP ingress gateway.** Its MCP gateway is retired from this
   path. `config_mcp_clients` holds 0 rows and `mcp_tool_logs` holds 0 rows —
   the capability was never configured or exercised here.
- **Bifrost Skills Repository / cross-harness skill distribution.** The
   superseded plan's Phase 3. Deferred to a future plan: the marketplace route
   currently returns 503 (`skills_external_client_url` unset), the repository
   has no authored skills, and the ecosystem already distributes skills through
   repo-local `.claude/skills/` and plugin marketplaces. Revisit when a
   concrete cross-machine distribution requirement appears.
- **Caching MCP tool results.** Bifrost's semantic cache is an LLM-inference
   plugin (`mcp_tool_execution` is a separate `RequestType` with its own plugin
   interface), and `cache_tool_call_responses` defaults to `false` precisely
   because "a replayed tool call runs in a later caller's agent loop with
   arguments chosen for someone else's prompt." Caching results of mutating
   tools (`write_file`, git commit, worker spawn) is unsafe. Out of scope.
- **Public hosting, per-user virtual keys, enterprise SSO, agent
  distribution, custom sync CLIs, cross-machine skills sync.** Inherited
  unchanged from the superseded plan.
- **Vendoring or forking MCPM.** Consumed as an installed dependency.

## 4. Current Findings

### 4.1 The superseded plan's premise is dead, and its findings were stale

`docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md` aimed to put the 5
Bodai servers behind one Bifrost `/mcp` endpoint. Verified on 2026-11-07:

| Plan claim | Reality |
|---|---|
| Bifrost serves MCP at `:8080` | `:8471` serves both LLM and MCP; nothing listens on 8080 |
| "Bifrost is paused indefinitely" (Gatekeeper) | Live since 2026-10-30; transport pinned v2.4.0 |
| `scripts/bifrost-ctl` drives the lifecycle | Deleted; now `mahavishnu/bifrost/lifecycle.py` + `mahavishnu/cli/bifrost_cli.py` |
| Phase 2 writes `clients[]` into `config/bifrost/config.json` | No `mcp` block exists in `config/bifrost/config.template.json`; live `config_mcp_clients` = **0 rows** |
| Phase 3 edits `config/bifrost/config.json` | The SQLite `config_store` is authoritative; the file is ignored |
| `claude mcp list` → exactly `["bifrost"]` | Unreachable — `.mcp.json` has 17 entries, `~/.claude.json` 4 more. Real outcome: **21 → 17** |
| 5 Bodai servers; oneiric "N/A", stdio | All five are HTTP; oneiric is `:8681`, live, 18 tools |

### 4.2 Aggregation renames every tool — and the rename is build-breaking

- **Bifrost** prefixes at discovery: `fmt.Sprintf("%s-%s", clientName, mcpTool.Name)`
  (upstream `core/mcp/utils.go:1394-1400`) → `mahavishnu-pool_route_execute`.
- **MCPM** mounts each upstream with `prefix=<server_name>` and FastMCP composes
  `prefix_toolname` with a **single underscore** (`fastmcp/server/server.py:2229`)
  → `mahavishnu_pool_route_execute`.
- Neither reproduces the `__` separator. Critically, the `__` segment is
  **Claude Code's config-entry namespace**, derived 1:1 from the configured
  entry name — it is not a tool-name property, and no gateway can inject it
  per-tool. The only way to keep it is to keep one config entry per server.
- Blast radius: `grep -c 'mcp__' mahavishnu/core/skill_mcp_validator.py` → **105**
  exact-match strings in `KNOWN_TOOLS`; 268 executable/config references;
  **525** doc mentions. `skill_mcp_validator.py` already documents a
  triple-underscore edge case (`mcp__session-buddy___code_get_symbol_graph_impl`),
  so the convention is already load-bearing and brittle.

### 4.3 Aggregation does not reduce the tool surface — it adds to it

Live inventory, 2026-11-07 (streamable-HTTP handshake + `tools/list`):

| Server | Port | Tools | `tools/list` bytes |
|---|---|---|---|
| mahavishnu | 8680 | 161 | 109,210 |
| session-buddy | 8678 | 225 | 158,359 |
| crackerjack | 8676 | 53 | 24,575 |
| akosha | 8682 | 39 | 29,452 |
| oneiric | 8681 | 18 | 10,007 |
| **Total** | | **496** | **331,603** |

15 tool names collide across servers (`discover_tools`, `get_health`,
`get_liveness`, `get_readiness`, `health_check_all`, `search_code`,
`wait_for_dependency`, …) — which is why any single-entry namespace needs a
prefix, and why the prefix breaks the contract.

Aggregation delivers the same 496 schemas to the prompt either way, plus
~12 KB of extra prefix text. Only **subsetting** reduces it.

### 4.4 The tool-profile gating already exists and is switched off

`mahavishnu/mcp/tools/profiles.py` gates 153 of mahavishnu's tools behind
`MAHAVISHNU_TOOL_PROFILE`. Measured against the production entry point
(`build_mahavishnu_mcp_server`):

| Profile | mahavishnu tools |
|---|---|
| `full` | 168 (161 live) |
| `standard` | 109 |
| `minimal` | 58 |

Every server is launched at `full` — hardcoded in
`~/.claude/scripts/mcp-launchd/mcp-ctl.sh` (lines 103, 109, 117, 124) and in
the installed plists. The mechanism is built, tested, and unused.

The profile is read **per server process**, so today a harness can point at a
differently-profiled instance. That control is lost if one shared gateway fronts
all servers — another argument for per-server entries.

### 4.5 The four-table registration drift is real and live

| Table | Entries |
|---|---|
| `mcp-ctl.sh` `MCP_SERVERS` | 16 |
| `mcp-supervisor.sh` `MCP_SERVERS` | 18 |
| repo `.mcp.json` (git-tracked) | 17 |
| installed `com.mcp.*.plist` | ~20 |

`oneiric` has a plist and a `.mcp.json` entry but appears in **neither**
registry array — so the supervisor never health-checks it and `mcp-ctl generate`
never manages it.

### 4.6 The cache-sharing benefit is real, and it lives on the LLM egress path

This is the one place Bifrost earns its keep for this fleet, and it is
**already partly built**.

- `mcp-ctl.sh` lines 96-101 launch mahavishnu with
  `ONEIRIC_BIFROST_ENABLED=true`, `ONEIRIC_BIFROST_BASE_URL=http://127.0.0.1:8471/v1`,
  `ONEIRIC_BIFROST_CACHE_MODE=semantic`. **mahavishnu's internal LLM calls
  already flow through Bifrost's semantic cache.**
- **akosha, session-buddy, crackerjack and oneiric do not.** They get no
  `ONEIRIC_BIFROST_*` environment at all — so their internal LLM calls bypass
  the cache, the routing rules, and the cost accounting.
- The code path is already there: `session-buddy/session_buddy/worker.py` and
  `session-buddy/session_buddy/reflection/embeddings.py` reference
  `ONEIRIC_BIFROST`, and `session-buddy/pyproject.toml:73-74` +
  `crackerjack/pyproject.toml:67-69` pin `oneiric` for
  `oneiric.adapters.llm.bifrost` (`REQ-BIFROST-009` / `REQ-BIFROST-010`).
  **The servers are code-ready; they are simply not launched with the env.**
- Cache mechanics (upstream docs + `mahavishnu/bifrost/cache_headers.py`):
  `x-bf-cache-key` selects the bucket; **without it and without the plugin's
  `default_cache_key`, caching never engages**. The live
  `config/bifrost/config.template.json` semantic_cache block sets no
  `default_cache_key`, so a bucket must be named explicitly. Entries are also
  partitioned by identity (virtual key + user) unless
  `disable_identity_scoping` is set.
- **Bifrost's semantic cache does not cache MCP tool executions.**
  `mcp_tool_execution` is a sibling `RequestType` driven through a separate
  plugin interface, and `cache_tool_call_responses` defaults to `false`.

**Conclusion**: "share Bifrost's cache across the MCP fleet" is achievable — by
routing each server's *internal LLM egress* through Bifrost with a shared
traffic class and principal — and it requires **no MCP gateway at all**.

### 4.7 MCPM supplies exactly the tedious part

MCPM v2.15.0 (installed as a `uv tool`, **not** Homebrew — see the memory
`mcpm-install-is-uv-not-brew`) ships client managers for 14 harnesses:
`claude_code`, `codex_cli`, `qwen_cli`, `gemini_cli`, `goose`, `opencode`,
`cursor`, `vscode`, `cline`, `continue_extension`, `windsurf`, `trae`,
`fiveire`, `claude_desktop`. Each encodes that client's config format and
location — the part that would take weeks to reimplement by hand.

Two source facts make it usable in the intended shape:

- `mcpm/clients/base.py:299-310` — `to_client_format` branches: stdio servers
  become `command`/`args`/`env`; **remote servers go through `to_dict()` and
  keep their `url`**. Bodai's HTTP entries stay HTTP entries.
- `mcpm/clients/managers/claude_code.py:23-34` — every manager accepts
  `config_path_override`, so MCPM can be pointed at a repo's `.mcp.json`
  instead of `~/.claude.json`. The CLI exposes it as `--file`
  (`mcpm/commands/client.py:220`).

Activation is scriptable: `--set-servers`, `--add-server`, `--remove-server`,
`--add-profile`, `--remove-profile`, `--set-profiles`, `--file`, `--force`
(`mcpm/commands/client.py:222-229`).

### 4.8 What we deliberately will not do with MCPM

- **No `mcpm profile run <profile> --http`.** That shape is the runtime
  aggregator: `auth_enabled=False` (`mcpm/fastmcp_integration/proxy.py:27`),
  no `/health`, no timeouts, silent port drift
  (`find_available_port` increments on a busy port, DEBUG-level log only), and
  FastMCP's `mounted_components_raise_on_load_error = False`
  (`fastmcp/settings.py:362`) makes a dead upstream's tools vanish from a
  `tools/list` that still returns 200. Aggregation converts a loud
  `ECONNREFUSED` into a quiet, session-long, misattributed absence.
- **No MCPM-managed global store as the source of truth.** `~/.config/mcpm/`
  is machine-local and untracked, so it does not travel and would become a
  fifth registration table. The registry in this repo is authoritative; MCPM
  is a writer library.

## 4.5 Requirements

Declared in the plan frontmatter (`requirements:`). Tracked by
`python scripts/audit_requirements.py`; implementation must carry
`# req: REQ-MCP-NNN` markers.

| ID | Requirement | Fulfilled by |
|---|---|---|
| REQ-MCP-001 | Checked-in MCP server registry is the single source of truth | Phase 1 |
| REQ-MCP-002 | Named MCP profiles group servers for task-shaped work | Phase 1 |
| REQ-MCP-003 | `mahavishnu mcp` CLI exposes list/profile/use/sync/status | Phase 2 |
| REQ-MCP-004 | Profile activation writes one config entry per server, preserving tool names | Phase 3 |
| REQ-MCP-005 | Multi-harness config writing across Claude Code, Codex, Qwen, Gemini, Goose, OpenCode | Phase 3 |
| REQ-MCP-006 | Per-server tool-profile gating bounds each profile's tool surface | Phase 4 |
| REQ-MCP-007 | Per-upstream health status replaces aggregator telemetry | Phase 2 |
| REQ-MCP-008 | MCP servers share Bifrost semantic cache for internal LLM egress | Phase 5 |
| REQ-MCP-009 | Registration tables derive from the registry, ending four-table drift | Phase 4 |

## 5. Implementation Phases

### Phase 1: Registry + profile definitions

**Goal**: one checked-in file names every MCP server; named profiles group them.

**Tasks**:

- [ ] Create `config/mcp/servers.yaml` — one entry per server: `name`, `url`,
      `transport`, `enabled_by_default`, `health` (url + expectation), `env`
      (per-server `*_TOOL_PROFILE`), `harnesses` (which harnesses may use it).
- [ ] Create `config/mcp/profiles.yaml` — named groups referencing server
      names. Seed with `bodai-full` (the 5 Bodai servers) and `web-dev`
      (chrome-devtools, playwright, a fetch server).
- [ ] Add `config/mcp/README.md` documenting the schema and the "registry is
      authoritative" rule.
- [ ] Validate the registry at load: every profile member resolves to a
      server entry; every URL parses; no duplicate names.

**Exit criteria**:

- `config/mcp/servers.yaml` and `config/mcp/profiles.yaml` exist, parse, and
  every profile member resolves.
- The five Bodai servers and the 12 non-Bodai entries in `.mcp.json` are all
  represented exactly once.

#### Integration Contract — Phase 1

- **Triggered from**: `mahavishnu mcp list` (Phase 2) and any registry consumer;
  the loader entry point is `mahavishnu/mcp/registry.py:load_registry()`.
- **Returns to / updates**: `config/mcp/servers.yaml`, `config/mcp/profiles.yaml`
  (both git-tracked).
- **Demonstrable by**: `python -c "from mahavishnu.mcp.registry import load_registry; r=load_registry(); print(len(r.servers), len(r.profiles))"`
  prints the server and profile counts with no unresolved profile member.
- **Rollback signal**: registry load raises on unresolved profile member →
  the CLI exits non-zero and writes nothing to any harness config.
- **Observability added**: registry parse emits one structured log line
  (`registry.loaded`, `servers`, `profiles`) at INFO.

### Phase 2: `mahavishnu mcp` CLI — read-only surface

**Goal**: `mahavishnu mcp list|profile|status` work against the registry
without writing to any harness config.

**Tasks**:

- [ ] Add `mahavishnu/cli/mcp_cli.py` and register the `mcp` subcommand group
      in `mahavishnu/cli.py`.
- [ ] `mahavishnu mcp list` — servers with URL, transport, profile membership,
      and whether the server is enabled in each detected harness.
- [ ] `mahavishnu mcp profile list|show <name>` — profiles and members.
- [ ] `mahavishnu mcp status` — health-probe every registry entry, report
      per-server reachability and the harness config each appears in.
- [ ] Detect installed clients via MCPM's client registry.

**Exit criteria**:

- `mahavishnu mcp list` prints every registry server with its URL.
- `mahavishnu mcp status` reports 5/5 Bodai servers reachable when they are up,
  and names the unreachable one otherwise.

#### Integration Contract — Phase 2

- **Triggered from**: `mahavishnu mcp list|profile|status` from the CLI entry
  point `mahavishnu/cli/mcp_cli.py`.
- **Returns to / updates**: nothing on disk — this phase is read-only by
  construction (deliberate: the first writable path is proven separately).
- **Demonstrable by**: `mahavishnu mcp status` exits 0 and prints a per-server
  table with a `reachable` column.
- **Rollback signal**: a non-zero exit or an unhandled exception in any
  `mcp` subcommand — the subcommand is removed; no state to unwind.
- **Observability added**: one structured log line per status probe
  (`mcp.status.probe`, `server`, `reachable`, `latency_ms`).

### Phase 3: Profile activation across harnesses

**Goal**: `mahavishnu mcp use <profile>` writes the profile's members into the
target harness's config, one entry per server, each keeping its original
transport — and nothing else changes.

**Tasks**:

- [ ] Resolve a profile to its member servers; for each member, obtain the
      client-format entry via MCPM's manager `to_client_format` (remote
      servers keep `url`).
- [ ] Write via MCPM's managers, with `config_path_override` pointing at the
      target repo's `.mcp.json` (project scope) or the harness's own file
      (user scope), per an explicit `--scope` flag.
- [ ] Remove members of previously-active profiles that are not in the new
      profile; never touch entries MCPM does not own.
- [ ] Support `--client claude-code|codex-cli|qwen-cli|gemini-cli|goose|opencode|…`
      and `--dry-run` (print the diff, write nothing).
- [ ] Add `mahavishnu mcp sync` — re-apply the active profile idempotently.
- [ ] Unit-test the round trip: profile → written config → `to_client_format`
      → profile membership, asserting `url` survives for remote servers.

**Exit criteria**:

- After `mahavishnu mcp use web-dev --client claude-code --scope project`, the
  target `.mcp.json` contains exactly the profile's members, each with its
  original `url`, and no other entry changed.
- The resulting session exposes `mcp__<server>__<tool>` names unchanged —
  verified by `mahavishnu mcp status` reporting the same names as before.

#### Integration Contract — Phase 3

- **Triggered from**: `mahavishnu mcp use <profile>` /
  `mahavishnu mcp sync`, entry point `mahavishnu/cli/mcp_cli.py`.
- **Returns to / updates**: the target harness's MCP config — project scope
  `<repo>/.mcp.json`, or the user-scope file MCPM's manager resolves
  (`~/.claude.json` for Claude Code, `~/.codex/config.toml` for Codex CLI).
- **Demonstrable by**: `mahavishnu mcp use web-dev --dry-run` prints the exact
  entry-level diff; applying it and re-running `mahavishnu mcp status` shows
  the profile's members active and the rest inactive.
- **Rollback signal**: `mahavishnu mcp use bodai-full` restores the previous
  membership; every write is preceded by a backup of the target file to
  `<file>.bak` so a bad write is a one-line restore.
- **Observability added**: structured log line per write
  (`mcp.config.written`, `client`, `profile`, `servers_added`,
  `servers_removed`) and a `mcp_config_writes_total` counter.

### Phase 4: Tool-profile gating + registration-drift consolidation

**Goal**: a profile's tool surface is bounded, and one registry feeds every
registration table.

**Tasks**:

- [ ] Change `~/.claude/scripts/mcp-launchd/mcp-ctl.sh` server env blocks from
      `<REPO>_TOOL_PROFILE=full` to `standard` for mahavishnu, akosha,
      session-buddy and crackerjack.
- [ ] Regenerate the plists (`mcp-ctl generate`) and restart; verify live tool
      counts drop (mahavishnu 161 → ~102).
- [ ] Add the `oneiric` entry to both `MCP_SERVERS` arrays — it is currently
      in neither, so the supervisor never checks it.
- [ ] Make the registry the input to the generator: `mcp-ctl generate` and the
      supervisor read `config/mcp/servers.yaml` rather than a hand-maintained
      array. The two registries become views of one source.
- [ ] Record the `*_TOOL_PROFILE` value per server in `config/mcp/servers.yaml`
      so Phase 1 and this phase cannot drift.

**Exit criteria**:

- `mahavishnu mcp list` reports the tool profile in force for every server.
- Live `tools/list` counts match the registry's declared profile.
- `oneiric` appears in both `MCP_SERVERS` arrays and in the supervisor's
  health state file.

#### Integration Contract — Phase 4

- **Triggered from**: `mcp-ctl generate && mcp-ctl restart` (operator-run), and
  `mahavishnu mcp sync` for the registry-derived arrays.
- **Returns to / updates**: `~/Library/LaunchAgents/com.mcp.*.plist`,
  `~/.claude/scripts/mcp-launchd/mcp-ctl.sh`,
  `~/.claude/scripts/mcp-launchd/mcp-supervisor.sh`,
  `~/.local/state/mcp/mcp-state.json`.
- **Demonstrable by**: `mahavishnu mcp list --tools` shows the live
  `tools/list` count per server and the declared profile beside it.
- **Rollback signal**: a Bodai server failing its `mcp_tool_calls_total`
  health check or a supervisor restart count exceeding `MAX_RESTARTS=3` →
  revert the profile value to `full` and re-run `mcp-ctl generate`.
- **Observability added**: supervisor state gains a per-server `tool_profile`
  field; a `mcp_tool_profile` label is added to the existing per-server
  health probe.

### Phase 5: Shared LLM egress — the fleet shares Bifrost's semantic cache

**Goal**: akosha, session-buddy, crackerjack and oneiric route their internal
LLM calls through Bifrost under a shared cache bucket, so a repeated prompt
across servers is served from cache.

**Tasks**:

- [ ] Extend the `mcp-ctl.sh` server env blocks with the same
      `ONEIRIC_BIFROST_*` variables mahavishnu already has
      (`ENABLED=true`, `BASE_URL=http://127.0.0.1:8471/v1`,
      `CACHE_MODE=semantic`), so their `oneiric.adapters.llm.bifrost` path is
      live.
- [ ] Give the fleet a **shared** traffic class so the bucket resolves
      identically across servers (`mahavishnu/bifrost/cache_headers.py:
      resolve_cache_bucket(traffic_class, principal)`).
- [ ] Confirm the identity scope: Bifrost partitions entries by virtual key
      and user unless `disable_identity_scoping` is set. Either align the
      servers on one principal, or set `disable_identity_scoping: true` with
      the isolation cost recorded in the decision log. **Default: align the
      principal** — do not weaken scoping to buy a cache.
- [ ] Set an explicit `default_cache_key` (or send `x-bf-cache-key` per
      request) — without one, the plugin does not engage at all.
- [ ] Add `mahavishnu bifrost cache-report --hours 24` (or extend
      `mahavishnu metrics bifrost`) showing hit rate per bucket, so the
      sharing is observable rather than assumed.
- [ ] Add a `oneiric` server env block (it is missing from `mcp-ctl.sh`
      entirely) so it participates in the same egress.

**Exit criteria**:

- All five Bodai servers appear in `mahavishnu bifrost cache-report` with a
  non-zero request count against the shared bucket.
- A repeated prompt issued by two different servers produces one cache write
  and one hit, evidenced by `x-bifrost-cache-*` response headers in the
  Bifrost access log.
- No server's LLM egress bypasses Bifrost.

#### Integration Contract — Phase 5

- **Triggered from**: `mcp-ctl generate && mcp-ctl restart` for the env
  blocks; per-request `x-bf-cache-key` from `oneiric.adapters.llm.bifrost`.
- **Returns to / updates**: the `com.mcp.*` plists' `EnvironmentVariables`;
  Bifrost's semantic_cache plugin config (`default_cache_key`,
  `disable_identity_scoping`) in `config/bifrost/config.template.json` — which
  is a **seed only**; the SQLite `config_store` is authoritative, so the live
  change goes through `mahavishnu bifrost` or the Management API, never by
  editing `config/bifrost/config.json`.
- **Demonstrable by**: `mahavishnu bifrost cache-report --hours 24` shows a
  non-zero hit rate on the shared bucket; `curl -s http://127.0.0.1:8471/health`
  still returns `{"status":"ok"}`.
- **Rollback signal**: Bifrost error rate on any provider above 50% over 60s
  (the existing `MahavishnuBifrostLocalErrorRateHigh` alert shape) → unset
  `ONEIRIC_BIFROST_ENABLED` for the affected server and restart it.
- **Observability added**: per-bucket hit-rate and request-count series in the
  Bifrost dashboard, plus a `mahavishnu.bifrost.cache.hit` counter exported
  through the existing Prometheus registry.

### Phase 6: Retire the aggregation path

**Goal**: the superseded plan is closed and its premise is recorded as
rejected, so nobody re-litigates it from the plan index.

**Tasks**:

- [ ] Set the superseded plan's frontmatter to `status: superseded`,
      `role: superseded`, `superseded_by: docs/plans/2026-11-07-mcp-profile-groups-and-shared-llm-egress.md`,
      and add a short "Retired — and why" section citing this plan's §4.1–4.3.
- [ ] Record the decision in `docs/decisions/` — the tool-namespace constraint
      (`mcp__<server>__<tool>` is Claude Code's config-entry namespace; no
      gateway can inject it per-tool) is a durable architectural constraint, not
      a plan detail.
- [ ] Confirm `config_mcp_clients` and `mcp_tool_logs` remain at 0 rows and
      that no harness references `http://127.0.0.1:8471/mcp`.
- [ ] Re-run `python scripts/regenerate_plan_index.py` so the index reflects
      the supersession.

**Exit criteria**:

- `grep -rn "8471/mcp" ~/.claude.json .mcp.json ~/.codex/config.toml` returns
  nothing.
- The plan index shows the old plan as superseded with a pointer to this one.

#### Integration Contract — Phase 6

- **Triggered from**: `python scripts/regenerate_plan_index.py` after the
  frontmatter edit.
- **Returns to / updates**: `docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md`
  frontmatter, `docs/decisions/`, `docs/plans/PLAN_INDEX.md`.
- **Demonstrable by**: `grep -n "status:" docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md`
  shows `superseded`, and the regenerated index links it to this plan.
- **Rollback signal**: none — this phase only edits documentation; revert the
  commit.
- **Observability added**: none (documentation-only phase; stated explicitly
  per the template's convention).

## 6. Required Code Changes

**New — mahavishnu**:

- [ ] `mahavishnu/mcp/registry.py` — registry + profile loading and
      validation.
- [ ] `mahavishnu/cli/mcp_cli.py` — the `mahavishnu mcp` subcommand group.
- [ ] `tests/unit/test_mcp_registry.py` — schema, validation, profile
      resolution.
- [ ] `tests/unit/test_mcp_cli.py` — list/profile/use/sync/status.
- [ ] `tests/integration/test_mcp_profile_activation.py` — round trip against
      a scratch config file; asserts `url` survives and unrelated entries are
      untouched.

**Modified — mahavishnu**:

- [ ] `mahavishnu/cli.py` — register the `mcp` subcommand group.
- [ ] `pyproject.toml` — add `mcpm` as a dependency (or an optional
      `dependency-group` entry if the group stays out of the base install —
      decide in Phase 1; the repo already has the `dependency-groups` pattern
      for narrow integrations).

**Modified — operator environment (outside this repo)**:

- [ ] `~/.claude/scripts/mcp-launchd/mcp-ctl.sh` — profile values, Bifrost
      env blocks, `oneiric` entry, registry-derived arrays.
- [ ] `~/.claude/scripts/mcp-launchd/mcp-supervisor.sh` — `oneiric` entry.
- [ ] `config/bifrost/config.template.json` — semantic_cache
      `default_cache_key` (seed only; live store is authoritative).

**Documentation**:

- [ ] `config/mcp/README.md` — registry schema.
- [ ] `docs/decisions/2026-11-07-mcp-tool-namespace-constraint.md` — the
      constraint and its consequences.
- [ ] `CLAUDE.md` — the MCP server/tool-count figures are stale (161 live for
      mahavishnu, 496 across the five Bodai servers); correct them.

## 7. Validation Matrix

| Check | Command | Expected | Evidence location |
|---|---|---|---|
| Registry parses | `mahavishnu mcp list` | every server with URL | terminal output |
| Profiles resolve | `mahavishnu mcp profile show web-dev` | members with URLs | terminal output |
| Per-upstream health | `mahavishnu mcp status` | per-server `reachable` column | terminal output |
| Activation diff | `mahavishnu mcp use web-dev --dry-run` | entry-level diff, no writes | terminal output |
| Activation writes | `mahavishnu mcp use web-dev --scope project` | target `.mcp.json` = profile members | file diff |
| Transport preserved | `grep '"url"' <target>.mcp.json` | `url` present, no `mcpm run` shims | file diff |
| Names unchanged | session tool list | `mcp__<server>__<tool>` unchanged | session transcript |
| Validator green | `python scripts/audit_requirements.py` | 0 orphans, 0 phantoms | terminal output |
| Validator green | `python -m pytest tests/integration/test_audit_requirements.py` | pass | terminal output |
| Tool surface bounded | `mahavishnu mcp list --tools` | mahavishnu ≈102 tools at `standard` | terminal output |
| No stray MCP gateway | `grep -rn "8471/mcp" ~/.claude.json .mcp.json` | no matches | terminal output |
| Shared cache live | `mahavishnu bifrost cache-report --hours 24` | all 5 servers, non-zero hit rate | terminal output |
| Bifrost healthy | `curl -s http://127.0.0.1:8471/health` | `{"status":"ok"}` | terminal output |
| No orphans | `python scripts/audit_orphans.py` | no new orphan symbols | terminal output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| MCPM's client manager writes stdio shims instead of `url` entries | low | `to_client_format` (`mcpm/clients/base.py:299-310`) branches on server type; verified in source. Round-trip unit test asserts `url` survives (REQ-MCP-004). |
| MCPM writes user scope while the repo needs project scope | medium | Every manager accepts `config_path_override` (`claude_code.py:23-34`); `--scope project` selects the repo's `.mcp.json`. |
| Writing `.mcp.json` dirties a git-tracked file | medium | `--scope project` writes are backed up to `<file>.bak`; the registry-driven default set is the tracked baseline, and per-consumer repos may carry their own generated `.mcp.json`. Decide the ownership rule in Phase 1. |
| Profiles live in this repo but are consumed by fastblocks/splashstand | medium | Cross-repo read dependency. Mitigate by having each consumer repo check in its own generated `.mcp.json` and re-run `mahavishnu mcp sync` after a registry change; add a CI check for drift. |
| `mcpm` upgrades break the CLI | low | Pin `mcpm==2.15.0` in the dependency spec (the current `uv` receipt is unpinned); add a CI guard test like `test_bifrost_transport_version.py`. |
| Shared cache weakens isolation between callers | medium | Default to aligning servers on one principal, **not** `disable_identity_scoping: true`. Record the tradeoff in `docs/decisions/`. |
| The four-table drift reappears | medium | REQ-MCP-009 makes the registry authoritative and the generators derive from it; a CI check asserts the arrays match the registry. |
| `standard` profile removes a tool a workflow depends on | medium | `discover_tools` remains registered; roll back per server by setting the profile back to `full` in the registry and re-running `mcp-ctl generate`. |
| The superseded plan is re-litigated from the index | low | Phase 6 records the namespace constraint as a decision, not a plan detail. |

## 9. Decision Rule

The plan is "done enough" when:

- **Phase 1**: `config/mcp/servers.yaml` and `config/mcp/profiles.yaml` parse,
  and every profile member resolves to a server entry.
- **Phase 2**: `mahavishnu mcp list|profile|status` work read-only against the
  registry and report per-server reachability.
- **Phase 3**: `mahavishnu mcp use web-dev` writes exactly the profile's
  members into a target harness's config as `url` entries, and the resulting
  session's tool names are unchanged.
- **Phase 4**: every Bodai server runs at `standard` (or a documented
  alternative), `oneiric` is registered in both supervisor arrays, and the
  live tool count per server matches the registry.
- **Phase 5**: all five Bodai servers appear in the Bifrost cache report with
  a non-zero shared-bucket hit rate.
- **Phase 6**: the superseded plan is marked superseded, the namespace
  constraint is recorded as a decision, and the plan index is regenerated.

Cut rules:

- If Phase 5's shared-bucket hit rate stays at zero after the env change, ship
  Phases 1-4 and diagnose the bucket separately — do not gate the profile work
  on the cache work.
- If Phase 3 cannot preserve `url` entries for a given harness, ship that
  harness as "config not managed" rather than degrading it to stdio shims.
- If the registry's ownership rule (this repo vs. each consumer repo) cannot be
  settled, ship Phase 1 with the registry in this repo and treat per-repo
  `.mcp.json` generation as Phase 3's follow-up.

## References

- `docs/plans/2026-10-19-bifrost-mcp-skills-aggregation.md` — the superseded
  plan (Phase 2 aggregation and the Bifrost-MCP-gateway premise are retired).
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — Bifrost LLM-side
  design; §4.1/§4.2 are superseded by `config/bifrost/README.md` and by the
  `llm_gateway` package deletion (commit `03146be0`).
- `config/bifrost/README.md` — authoritative record of Bifrost's live state,
  transport pin, and config-store authority.
- `mahavishnu/bifrost/cache_headers.py` — `x-bf-cache-key` /
  `resolve_cache_bucket` semantics.
- `mahavishnu/core/skill_mcp_validator.py` — the exact-match `KNOWN_TOOLS`
  registry that makes tool renames build-breaking.
- `~/.claude/scripts/mcp-launchd/mcp-ctl.sh` — the server registry, the
  `TOOL_PROFILE=full` values, and the `ONEIRIC_BIFROST_*` env blocks.
- `docs/decisions/wire-up-contract.md` — the Integration Contract policy this
  plan implements.
- `docs/decisions/mcp-backend-wiring-discipline.md` — per-feed health
  requirements satisfied by `mahavishnu mcp status`.
- MCPM — <https://mcpm.sh/> · <https://github.com/pathintegral-institute/mcpm.sh>
- Bifrost — <https://docs.getbifrost.ai/mcp/overview> ·
  <https://docs.getbifrost.ai/features/governance/virtual-keys> ·
  <https://github.com/maximhq/bifrost>
