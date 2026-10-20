---
status: active
role: implementation
kind: plan
date: 2026-10-19
last_reviewed: 2026-10-19
superseded_by: null
blocks_on: []
related:
  - docs/plans/2026-10-17-bifrost-oneiric-gateway-adapter.md
  - docs/specs/2026-10-15-bifrost-gateway-wiring-design.md
  - config/bifrost/README.md
  - scripts/bifrost-ctl
  - ~/Library/LaunchAgents/ai.bifrost.gateway.plist
  - ~/.config/secrets.env
replaces: null
topic: bifrost-mcp-skills-aggregation
title: "Bifrost MCP aggregation + Skills distribution — local single-VK plan"
---

# Bifrost MCP aggregation + Skills distribution — local single-VK plan

> **Plan scope**: re-bootstrap local Bifrost from paused state; aggregate the 5
> Bodai MCP servers behind one Bifrost `/mcp` endpoint per harness; activate
> the Bifrost Skills Repository and register marketplace URLs in Claude Code,
> Codex, and Qwen Code on this machine. Single shared virtual key sourced from
> `~/.config/secrets.env`. No public hosting, no per-user VKs, no agent
> distribution, no custom sync CLIs.

## 1. Outcome

When this plan ships:

- **Bifrost is live on this Mac** at `http://localhost:8080` with a codesigned
  native binary, launchd-managed, JSON-logged.
- **5 Bodai MCP servers** (`mahavishnu` 8680, `akosha` 8682, `session-buddy`
  8678, `crackerjack` 8676, `oneiric`) are reachable as upstream clients
  behind Bifrost's single `/mcp` endpoint.
- **Each harness on this Mac** (`claude`, `codex`, `qwen`) has exactly
  **one** MCP server entry: `bifrost`. Per-harness config drops from
  N entries to 1.
- **Skills Repository active** at the local gateway; Claude Code and Codex
  register their marketplace URLs; Qwen Code uses
  `qwen extensions install <bifrost-claude-marketplace-url>` for
  install-time-converted plugins.
- **Single shared virtual key** in `~/.config/secrets.env` (`BIFROST_VIRTUAL_KEY`)
  used by all harnesses on this machine.

**Proof it worked**:

- `curl http://localhost:8080/health` returns `{"status":"ok"}` within 5s of
  `scripts/bifrost-ctl start`.
- `claude mcp list | jq '.[] | .name'` returns exactly `["bifrost"]`
  (1 entry, not 5).
- From Claude Code, a prompt that requires a tool only present in
  `mcp__session-buddy__*` (or any of the 5 Bodai servers) succeeds; the
  `bifrost.log` entry within 5s shows the upstream dispatch.
- `claude plugin marketplace list` includes the local Bifrost Claude Code
  marketplace URL; `codex plugin marketplace list` includes the local
  Bifrost Codex marketplace URL.
- One skill from the Bifrost Skills Repository installs into Claude Code
  (`/plugin install bifrost-<name>`), Codex (per Codex marketplace
  install), and Qwen Code (`qwen extensions install ...`).

## 2. Goals

1. **Re-bootstrap local Bifrost** from the paused state documented at
   `config/bifrost/README.md:7-12` (Gatekeeper rejection of the unsigned
   native binary).
2. **Aggregate Bodai MCP servers** behind Bifrost's `/mcp` endpoint so
   each harness has 1 MCP entry instead of 5.
3. **Activate the Skills Repository** and register marketplace URLs in
   Claude Code, Codex, and Qwen Code on this machine.
4. **Source the shared VK** from `~/.config/secrets.env` per
   `feedback-credentials-source-secrets-env.md` (source at use-time,
   never inline).
5. **Disable Bifrost's auto tool injection** (`mcp_disable_auto_tool_inject: true`)
   so tools don't double-inject through the LLM gateway path and the
   `/mcp` discovery path.

## 3. Non-Goals

- **Public hosting.** No Tailscale, Cloudflare Tunnel, ngrok, or any
  publicly-reachable URL. Marketplace URLs are `http://localhost:8080/...`
  and only work for clients on the same Mac.
- **Per-user virtual keys.** One VK shared by all operators on this
  machine. Per-user attribution is sacrificed for operational simplicity.
- **Enterprise SSO / Identity Provider integration.** Okta, Entra,
  Keycloak, Google Workspace all out of scope.
- **Agent distribution.** Claude Code agents (`.md` files in
  `~/.claude/agents/`), Codex prompts (`~/.codex/prompts/*.md`), and
  Qwen extensions are all out of scope. The user explicitly removed
  this from the equation.
- **Custom sync CLIs.** `jup`, `npx skills`, `polyagent.io`,
  `skillsync.dev`, `unifiedagent.com/cli` — none adopted. Vercel's
  `npx skills` is available for ad-hoc use but not part of this plan.
- **Cross-machine skills sync.** Single-machine scope. Team scaling
  would require exposing Bifrost publicly (out of scope) or moving to
  per-operator local gateways (also out of scope).
- **Bifrost semantic cache tuning.** The cache plugin exists at
  `config.template.json:131-143` but is left in its current
  direct-only mode per the Bifrost README guidance for subscription-backed
  traffic.
- **New cloud providers.** No new Bifrost provider entries beyond what
  `config/bifrost/config.template.json` already declares.

## 4. Current Findings

### 4.1 Bifrost is paused indefinitely on this Mac

`config/bifrost/README.md:7-12`:

> **Bifrost is paused indefinitely.** The upstream `@maximhq/bifrost` npm
> package ships a native Go binary with Mach-O metadata
> (`LC_VERSION_MIN_MACOSX sdk 10.4`, no `LC_BUILD_VERSION`) that modern
> macOS strict-validators and Gatekeeper reject. Re-downloading newer
> package versions does not help — the npm `bin.js` hardcodes the same
> `v1.6.0/bin/bifrost-http-0` path regardless of the package version.
> The fix must come from the upstream build pipeline.

Workaround documented at `config/bifrost/README.md:230-237`:

- `chmod +x ~/Library/Caches/bifrost/<version>/bin/bifrost-http-0`
- `codesign --force --sign - ~/Library/Caches/bifrost/<version>/bin/bifrost-http-0`

The launchd job `ai.bifrost.gateway` and `ai.bifrost.redis-stack` plists
remain in `~/Library/LaunchAgents/` for reactivation per
`config/bifrost/README.md:14-17`.

### 4.2 Bodai MCP servers (5 upstream clients for the aggregation layer)

Per `CLAUDE.md` Ecosystem Context table:

| Server | Port | Role |
|---|---|---|
| Mahavishnu | 8680 | Orchestrator (control plane) |
| Akosha | 8682 | Seer (intelligence) |
| Session-Buddy | 8678 | Builder (memory) |
| Crackerjack | 8676 | Inspector (quality) |
| Oneiric | N/A | Foundation (config loader) |

Each currently consumed via per-harness MCP entries (5 entries per harness
in `~/.claude.json` `mcpServers`). The MCP transport varies (HTTP for some,
stdio for others) — Bifrost accepts both as upstream clients.

### 4.3 Bifrost Skills Repository has two separate marketplace endpoints

Per context7 `/maximhq/bifrost` `docs/features/skills-repository`:

| Harness | Marketplace endpoint | Schema |
|---|---|---|
| Claude Code | `<base>/api/skills/serve/claude-code/.claude-plugin/marketplace.json` | Claude Code plugin schema |
| Codex CLI | `<base>/api/skills/serve/codex` | Codex-specific schema (`.agents/plugins/marketplace.json`) |

The two schemas are distinct. Bifrost serves both from separate endpoints;
clients register the URL via their native marketplace command.

### 4.4 Qwen Code consumes Claude Code plugins via install-time conversion

Per [qwenlm.github.io/qwen-code-docs/en/users/extension/introduction](https://qwenlm.github.io/qwen-code-docs/en/users/extension/introduction/):

> "Claude plugins are automatically converted to Qwen Code format during
> installation" — `claude-plugin.json` becomes `qwen-extension.json`,
> agent configs become Qwen subagents, and skills are mapped over.

So `qwen extensions install <bifrost-claude-marketplace-url>` works
without Bifrost serving a Qwen-specific marketplace endpoint.

### 4.5 The shared VK lives in `~/.config/secrets.env`

Per `feedback-credentials-source-secrets-env.md`:

> Credentials (API keys, bearer tokens) live in `~/.config/secrets.env`
> as canonical source; source into env at use-time; never inline.

Bifrost VK sourcing: stored as `BIFROST_VIRTUAL_KEY` in
`~/.config/secrets.env`. Harnesses read at launch (e.g., via the shell
profile or `bifrost auth set-virtual-key --stdin` pattern from
`github.com/maximhq/bifrost/blob/dev/docs/cli-agents/claude-code.mdx`).

### 4.6 `scripts/bifrost-ctl` provides all the lifecycle primitives

Per `scripts/bifrost-ctl:28-30`, the operator commands are:

```
install | sync-config | start | stop | restart | rebootstrap |
status | tail | foreground
```

`rebootstrap` (line 171) is the right entry point for Phase 1: it
copies the config template, removes the SQLite `config.db`, kills any
orphan listener, and bootstraps the launchd job.

## 5. Implementation Phases

### Phase 1: Re-bootstrap local Bifrost

**Goal**: Bifrost is live at `http://localhost:8080` with a codesigned
native binary, launchd-managed, JSON-logged.

**Tasks**:

- [ ] Run `scripts/bifrost-ctl rebootstrap` to drop stale config and
  bootstrap the launchd job from `config/launchd/ai.bifrost.gateway.plist`.
- [ ] Locate the binary at
  `~/Library/Caches/bifrost/<version>/bin/bifrost-http-0` (the `v1.6.0`
  path is hardcoded per `config/bifrost/README.md:11`).
- [ ] `chmod +x` the binary (per `config/bifrost/README.md:234`).
- [ ] `codesign --force --sign -` the binary (per
  `config/bifrost/README.md:237`).
- [ ] `scripts/bifrost-ctl start`; wait for
  `~/.local/state/mcp/ready/bifrost.ready` to appear (60s timeout per
  `scripts/bifrost-ctl:80-88`).
- [ ] Verify health: `curl -s http://localhost:8080/health` returns
  `{"status":"ok"}`.

**Exit criteria**:

- `lsof -nP -iTCP:8471 -sTCP:LISTEN` shows the listener.
- `curl http://localhost:8080/health` returns 200 OK.
- `tail ~/.local/state/mcp/logs/bifrost.log` shows JSON-formatted lines.

#### Integration Contract — Phase 1

- **Triggered from**: `scripts/bifrost-ctl rebootstrap && scripts/bifrost-ctl start`
  (operator-run on this Mac).
- **Returns to / updates**: launchd job `ai.bifrost.gateway` running;
  `~/Library/Caches/bifrost/<version>/bin/bifrost-http-0` is executable
  and codesigned; `~/.config/bifrost/config.json` materialized from
  `config/bifrost/config.template.json`.
- **Demonstrable by**: `curl -s http://localhost:8080/health | jq .status`
  returns `"ok"` within 30s of `start`.
- **Rollback signal**: `scripts/bifrost-ctl stop` — listener dies,
  `lsof -nP -iTCP:8471 -sTCP:LISTEN` shows nothing.
- **Observability added**: `~/.local/state/mcp/logs/bifrost.log` JSON line
  emission; ready file `~/.local/state/mcp/ready/bifrost.ready`.

### Phase 2: MCP aggregation (Bodai servers behind Bifrost)

**Goal**: Each harness on this Mac has exactly 1 MCP entry
(`bifrost` at `http://localhost:8080/mcp`). The 5 Bodai MCP servers are
reachable as upstream clients.

**Tasks**:

- [ ] Add the 5 Bodai upstream clients to `config/bifrost/config.json`
  (or via the Bifrost Management API at
  `POST /api/mcp/clients`). Transport: HTTP for `mahavishnu`,
  `akosha`, `session-buddy`, `crackerjack`; stdio for `oneiric` if
  it's a local-launched process.
- [ ] Set `client.mcp_disable_auto_tool_inject: true` in
  `config/bifrost/config.json` (per `docs.getbifrost.ai/mcp/overview`
  "Recommended: disable auto tool injection").
- [ ] Store the shared VK as `BIFROST_VIRTUAL_KEY` in
  `~/.config/secrets.env` (operator-run; create the file if absent
  with `chmod 600`).
- [ ] On each harness on this Mac, run:
  ```
  source ~/.config/secrets.env
  claude mcp add --transport http bifrost http://localhost:8080/mcp \
    --header "Authorization: Bearer ${BIFROST_VIRTUAL_KEY}" \
    --scope user
  ```
- [ ] E2E test: from Claude Code, prompt something that requires a
  tool only present in `mcp__session-buddy__*` (e.g.,
  "search session-buddy for any checkpoints mentioning
  bifrost-mcp"); assert it succeeds.
- [ ] Assert `bifrost.log` records the dispatch with
  `caller_id` set to the VK name.

**Exit criteria**:

- `claude mcp list` returns exactly `["bifrost"]` (1 entry, not 5).
- All 5 Bodai servers' tool inventories are reachable through the
  single `bifrost` entry.
- E2E test from Claude Code: tool only in `mcp__session-buddy__*` works.

#### Integration Contract — Phase 2

- **Triggered from**: edit `config/bifrost/config.json` `clients[]`
  block + per-operator `claude mcp add` command (sourcing
  `BIFROST_VIRTUAL_KEY` from `~/.config/secrets.env`).
- **Returns to / updates**: per-operator `~/.claude.json`
  `mcpServers.bifrost` entry (single); `config/bifrost/config.json`
  `clients[]` block with 5 Bodai upstream entries;
  `~/.config/secrets.env` gains `BIFROST_VIRTUAL_KEY`.
- **Demonstrable by**: `claude mcp list | jq '.[].name'` returns
  `["bifrost"]`; from Claude Code, calling a tool only present in
  `mcp__session-buddy__*` succeeds and `bifrost.log` records a
  matching dispatch line within 5s.
- **Rollback signal**: `claude mcp remove bifrost` per operator +
  revert `config/bifrost/config.json` `clients[]` block to empty.
- **Observability added**: per-tool-call JSON log line in
  `bifrost.log` (Bifrost's MCP gateway emits these natively).

### Phase 3: Skills distribution (marketplace URLs in 3 harnesses)

**Goal**: Skills Repository active; one marketplace URL per Claude Code,
one per Codex, one Qwen Code install command documented.

**Tasks**:

- [ ] In `config/bifrost/config.json` (or via Management API), set
  `client.skills_external_client_url: "http://localhost:8080"`
  per `github.com/maximhq/bifrost/blob/dev/docs/deployment-guides/config-json/client.mdx`.
- [ ] Verify the marketplace endpoints serve JSON:
  - `curl http://localhost:8080/api/skills/serve/claude-code/.claude-plugin/marketplace.json`
  - `curl http://localhost:8080/api/skills/serve/codex`
- [ ] Register Claude Code marketplace on each operator's install:
  ```
  claude plugin marketplace add http://localhost:8080/api/skills/serve/claude-code/.claude-plugin/marketplace.json
  ```
- [ ] Register Codex marketplace on each operator's install:
  ```
  codex plugin marketplace add http://localhost:8080/api/skills/serve/codex
  ```
- [ ] Document Qwen Code install in a one-line runbook:
  ```
  qwen extensions install http://localhost:8080/api/skills/serve/claude-code/.claude-plugin/marketplace.json
  ```
  (Qwen does install-time conversion from `claude-plugin.json` to
  `qwen-extension.json` per the Qwen Code extension docs.)
- [ ] Author one skill in the Bifrost dashboard (or via
  `POST /api/skills`) named `bifrost-smoke-test` with a trivial
  `SKILL.md`.
- [ ] E2E test from each harness: install `bifrost-smoke-test`; assert
  the skill appears in Claude Code's `~/.claude/skills/`, Codex's
  installed plugins store, and Qwen Code's `~/.qwen/extensions/`.

**Exit criteria**:

- The `bifrost-smoke-test` skill installs successfully into Claude
  Code, Codex, and Qwen Code from the local Bifrost marketplace URL.
- `bifrost.log` records the served-version per install.

#### Integration Contract — Phase 3

- **Triggered from**: edit `config/bifrost/config.json`
  `client.skills_external_client_url` + per-operator
  `claude plugin marketplace add` / `codex plugin marketplace add` /
  `qwen extensions install` commands.
- **Returns to / updates**: per-operator Claude Code
  `~/.claude/plugins/marketplaces.json` entry; Codex's installed
  marketplace store; Qwen Code's `~/.qwen/extensions/` (post-conversion
  to `qwen-extension.json`).
- **Demonstrable by**: install `bifrost-smoke-test` from the local
  marketplace → assert it appears in all three harnesses'
  skill/plugin directories and `bifrost.log` records the served
  version.
- **Rollback signal**: `claude plugin marketplace remove`,
  `codex plugin marketplace remove`, `qwen extensions uninstall`.
- **Observability added**: per-serve JSON log line in `bifrost.log`
  from the Skills Repository plugin.

## 6. Required Code Changes

This plan is **integration + config + runbook**, not new code. Files
touched:

- [ ] `config/bifrost/config.json` (post-bootstrap, on this Mac):
  add `clients[]` block with 5 Bodai upstream servers; set
  `mcp_disable_auto_tool_inject: true`; set
  `skills_external_client_url: "http://localhost:8080"`.
- [ ] `~/.config/secrets.env` (new file, `chmod 600`): add
  `BIFROST_VIRTUAL_KEY=<operator-rotated-vk>`.
- [ ] `~/.claude.json` (per operator): gains single `mcpServers.bifrost`
  entry from `claude mcp add`.
- [ ] `~/.claude/plugins/marketplaces.json` (per operator): gains
  entry from `claude plugin marketplace add`.
- [ ] `~/.codex/config.toml` or per-Codex marketplace store (per
  operator): gains entry from `codex plugin marketplace add`.
- [ ] `~/.qwen/extensions/<name>/qwen-extension.json` (per Qwen
  operator, post-conversion from `claude-plugin.json`): materialized by
  `qwen extensions install`.
- [ ] `scripts/bifrost-ctl`: no changes (existing `rebootstrap` /
  `start` / `stop` / `status` / `tail` cover Phase 1).
- [ ] `docs/cookbook/bifrost-local-aggregation.md` (new): operator
  runbook distilling Phases 1-3 into a step-by-step checklist.

## 7. Validation Matrix

| Check | Command | Expected | Evidence location |
|---|---|---|---|
| Bifrost healthy | `curl -s http://localhost:8080/health` | `{"status":"ok"}` | terminal output |
| Listener bound | `lsof -nP -iTCP:8471 -sTCP:LISTEN` | non-empty PID line | terminal output |
| Launchd job running | `scripts/bifrost-ctl status` | `state = running` | terminal output |
| Binary codesigned | `codesign -dv ~/Library/Caches/bifrost/<version>/bin/bifrost-http-0` | non-empty authority line | terminal output |
| VK present | `grep BIFROST_VIRTUAL_KEY ~/.config/secrets.env` | single match | terminal output |
| VK permissions | `stat -f '%p' ~/.config/secrets.env` | `100600` (mode 600) | terminal output |
| Claude Code single MCP entry | `claude mcp list` | `bifrost` only | terminal output |
| Codex marketplace registered | `codex plugin marketplace list` | includes the local Bifrost URL | terminal output |
| Claude Code marketplace registered | `claude plugin marketplace list` | includes the local Bifrost URL | terminal output |
| Qwen Code install runs | `qwen extensions install <bifrost-claude-marketplace-url>` | success | terminal output |
| Bifrost log streaming | `tail -F ~/.local/state/mcp/logs/bifrost.log` | JSON lines | terminal output |
| Bodai tool reachable through Bifrost | prompt Claude Code to use `mcp__session-buddy__*` tool | success | session-buddy side effect |
| Skill installation log line | `grep "served" ~/.local/state/mcp/logs/bifrost.log` | one or more matches | terminal output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Gatekeeper rejects the unsigned binary again after re-download | medium | `chmod +x` + `codesign --force --sign -` workaround per `config/bifrost/README.md:230-237` |
| Local-only marketplace URLs only work for same-machine clients | high (by design) | Documented as Non-Goal #1; team scaling deferred to a future plan if Bifrost goes public |
| Shared VK = no per-user cost attribution or rate limiting | low (acceptable for ~5 operators) | Documented as Non-Goal #2; per-user VK migration is a future plan if needed |
| `config.db` config_store cache prevents later config edits from taking effect | medium | Per `config/bifrost/README.md:152-160`: stop gateway, remove `~/.config/bifrost/config.db`, re-run `rebootstrap` |
| macOS launchd cascade-failure after reboot | medium | Per `feedback-macos-reboot-launchd-keepalive-cascade.md`: re-run `scripts/bifrost-ctl start` after any reboot |
| `mcp_disable_auto_tool_inject: true` breaks a Bodai tool that relies on auto-injection | low | Test E2E before flipping the flag; if a regression appears, drop the flag (accept duplicate-tool risk) |
| Bifrost Skills Repository `skills_external_client_url: "http://localhost:8080"` blocks skill install if the harness resolves `localhost` differently | low | All three harnesses (Claude Code, Codex, Qwen Code) resolve `localhost` to loopback consistently on macOS |
| `~/.config/secrets.env` doesn't exist | medium (greenfield) | Bootstrap doc in `scripts/bifrost-ctl status` notes the missing-file case; operator creates it via `touch ~/.config/secrets.env && chmod 600 ~/.config/secrets.env` |
| `mcp__session-buddy__*` (or any Bodai server) is offline and a tool call fails | low | E2E test selects a known-available tool; production rollback is per-server restart, not a Bifrost issue |

## 9. Decision Rule

The plan is "done enough" when:

- **Phase 1**: `curl http://localhost:8080/health` returns `{"status":"ok"}`
  after a fresh `scripts/bifrost-ctl rebootstrap && start` cycle, and the
  binary passes `codesign -dv` with a valid authority line.
- **Phase 2**: `claude mcp list` returns exactly `["bifrost"]` (1 entry),
  and at least one tool only present in `mcp__session-buddy__*` (or any
  of the 5 Bodai servers) is reachable through the single Bifrost entry
  on this machine.
- **Phase 3**: A single authored skill (`bifrost-smoke-test`) installs
  successfully into Claude Code, Codex, and Qwen Code on this machine
  from the local Bifrost marketplace URL, and `bifrost.log` records the
  served-version per install.

No phase is "deferrable" — all three are operational prerequisites for
calling this plan shipped. Cut rules:

- If Phase 3 marketplace URLs fail for Qwen Code only, ship Phase 1-2
  fully and document Qwen Code as a follow-up (Qwen's install-time
  conversion is its own dependency).
- If Phase 2 fails for one specific Bodai server (e.g., transport
  incompatibility), ship Phase 1 fully, ship Phase 2 for the working 4
  servers, document the failing server as a follow-up.
- Phase 1 is unconditional — without a live Bifrost, nothing else
  matters.

## 10. References

- `docs/plans/2026-10-17-bifrost-oneiric-gateway-adapter.md` —
  companion plan that already shipped; lands 24 Bodai LLM call sites
  on oneiric BifrostLLMRouter. Independent of this plan; consumes the
  same gateway.
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — Bifrost
  gateway wiring design v1.5; reference for the launchd plist, env
  vars, and tool-injection toggle.
- `config/bifrost/README.md` — local Bifrost paused-state notes;
  Gatekeeper workaround documented at lines 230-237.
- `scripts/bifrost-ctl` — operator lifecycle script;
  `rebootstrap` (line 171) is the Phase 1 entry point.
- `feedback-credentials-source-secrets-env.md` — VK sourcing from
  `~/.config/secrets.env` at use-time.
- `feedback-macos-reboot-launchd-keepalive-cascade.md` — reboot
  recovery pattern.
- `feedback-no-backwards-compat-pre-1.0.md` — replace-not-extend; no
  legacy config blocks kept.
- `feedback-keep-plan-files-tracked.md` — `git add docs/plans/*.md`
  before commit so `git clean -fd` doesn't drop this file.
- `feedback-commit-plan-files-immediately.md` — commit this file
  right after writing.
- [github.com/maximhq/bifrost](https://github.com/maximhq/bifrost) —
  authoritative source for Bifrost features.
- [docs.getbifrost.ai/features/skills-repository](https://docs.getbifrost.ai/features/skills-repository)
  — Skills Repository feature spec.
- [docs.getbifrost.ai/mcp/overview](https://docs.getbifrost.ai/mcp/overview)
  — MCP Gateway aggregation behavior + `mcp_disable_auto_tool_inject`
  recommendation.
- [qwenlm.github.io/qwen-code-docs/en/users/extension/introduction](https://qwenlm.github.io/qwen-code-docs/en/users/extension/introduction/)
  — Qwen Code install-time conversion of Claude Code plugins.