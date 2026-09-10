---
status: active
role: canonical
date: 2026-09-09
last_reviewed: 2026-09-10
superseded_by: null
blocks_on: []
topic: skill-agent-distribution-via-mcp
review_notes:
  - "5-agent multi-lens review completed 2026-09-09. See §10 Split Plan and consolidated review report."
  - "Phase 1.5 (ed25519 signing core) implemented in akosha commit 09cef76 on 2026-09-09. Closes B-1 and partially addresses B-7 (4 mandatory feed signals + /health aggregation). 49/49 unit tests passing; lint + types clean; live /health verified; key_id persists across launchd restart."
  - "Second 2-reviewer pass (D2) requested 2026-09-09 after Phase 1.5 commit; findings folded into plan on 2026-09-10 — §10.3 Per-Server Wiring Contract added; §5/§6/§10.1/§10.2 completion-state markers added; package name + test path corrections (§10.1, §6); B-7 E2E test contract refactored to §10.3.7."
  - "Phase 1.5 cross-server consistency review completed 2026-09-10 across all 5 replicas (akosha, mahavishnu, session-buddy, dhara, crackerjack). 5 lenses audited: __all__ parity, canonicalize parity, manifest parity, signer_feed 9-key payload parity, production-lifespan parity. Result: 0 blockers; 1 Important (session-buddy redundant-init guard, commit 86d70f5f); 1 Cosmetic applied (akosha raise format, commit 223101d); 2 Cosmetic skipped (false-positive import-order; by-design signer_feed API surface). New §10.4 documents the review and decisions; §10.1/§10.2/§11 updated to reflect 5/5 server completion. Phase 1.5 is now fully closed in code across the ecosystem."
  - "Phase 1 (per-server list_skills/get_skill MCP tools + shared SkillMetadata schema) shipped 2026-09-10 across all 5 servers. Commits: akosha 4951ee8, mahavishnu d722d2fa, session-buddy 02235271 (H-6 rename) + 987c3096, dhara 2e3a65fa, crackerjack e99edb6a. Cross-server review §10.5 ran 6 lenses (SkillMetadata schema, signing integration, lifespan/singleton helpers, REGISTRATION_MAP+tier, API surface, H-6 collision). Result: 0 Blockers; 1 Important applied (akosha signature alignment commit 0dd7176 — collapsed param-accepting init_signer_feed_state to parameterless to match the other 4 servers); 1 Cosmetic applied (dhara trailing newline commit 9e81d98). Phase 1 wire protocol and public helper API now byte-equivalent across all 5 servers; Phase 2 installer is unblocked."
---

# Bodai Skill + Agent Distribution Plan

> **Why this plan exists**: Across two investigations (the slash-command
> picker audit on 2026-09-09, and the parallel "Skills and agents through
> MCP" conversation), we converged on a single architecture for getting
> ecosystem-wide skills and agents into the Claude Code slash-command
> picker, the Agent picker, and the Skill auto-trigger layer. Both
> investigations reached the same answer independently: **the seams that
> work are server-publishes / client-loads** — the same pattern
> Session-Buddy already uses internally for `list_skills` /
> `search_similar_patterns`.

## 1. Outcome

A user working in any Bodai repo can type `/akosha`, `/dhara`,
`/mahavishnu`, `/vishnu`, `/session-buddy`, or `/crackerjack` in the
Claude Code TUI picker and **see real entries that do real work** for that
component. Picking one of those entries creates a Skill (or loads an
Agent) sourced from the corresponding running MCP server. The discoverable
surface is **dynamically published by the server, not statically
maintained per project**.

**Success metric**: in a fresh Claude Code session starting from a clean
`~/.claude/`, typing `/akosha` returns ≥3 working entries that resolve
through `mcp__akosha__list_skills`-style indirection; typing `/dhara`
returns ≥3 working entries via the same mechanism. Per-component
specialist agents (`akosha-specialist`, `dhara-specialist`,
`session-buddy-specialist`, `crackerjack-specialist`) become discoverable
through the Agent picker even when their underlying `.claude/agents/`
markdown files are absent from the working tree.

## 2. Goals

1. **Fix the immediate naming hygiene gap** — Akosha and Dhara MCP tools
   don't carry `<component>_*` prefixes, so the TUI's `/<component>`
   prefix-match returns empty for them. Rename or `name=`-override the
   5–10 most user-facing tools per server.
2. **Adopt a single distribution primitive**: every Bodai MCP server
   exposes `list_skills()` and `list_agents()` MCP tools returning
   metadata JSON. Same shape across all 5 components.
3. **Wire a single install seam** — a Skill at `~/.claude/skills/` whose
   job is to call the federated `list_skills()` MCP tool, present the
   user with choices, and on selection materialize the skill locally as
   `~/.claude/skills/<component>-<name>/SKILL.md`. Client-side install
   mirrors server-side declaration.
4. **Authorize session-buddy as the federated registry** because it
   already owns the skill pattern and has the semantic-search substrate
   to do hybrid retrieval. The Bodai marketplace at
   `/Users/les/Projects/bodai-plugins` becomes the static index;
   Session-Buddy becomes the dynamic registry; the install seam lives
   in `~/.claude/skills/`.
5. **Define a "MCP-registered agent" pattern** that lets a server
   publish agents through the same metadata channel — analogous to
   skills but for the Agent picker.

## 3. Non-Goals

1. **Not** rewriting the underlying MCP tool implementations. The
   tools already exist and surface uniformly; this plan only reshapes
   discovery and packaging.
2. **Not** changing MCP server transport (HTTP/SSE/streamable). Auto-
   exposure works regardless.
3. **Not** adding new `.claude-plugin/plugin.json` entries to the
   bodai-plugins marketplace unless a 3rd-party install path becomes a
   hard requirement.
4. **Not** replacing the `~/.claude/skills/bodai-*` collection. That
   collection ships now and continues to work; this plan layers a
   dynamic fetch path on top.

## 4. Current Findings (proven by live MCP probes 2026-09-09)

### 4.1 Picker auto-exposure is uniform — proven

Live `tools/list` probes against all 5 running Bodai MCP servers
(ports 8676/8678/8680/8682/8683) showed:

| Server | Tools exposed | Have descriptions |
|---|---|---|
| Crackerjack :8676 | **47** | 14/47 |
| Session-Buddy :8678 | **49** | 49/49 |
| Mahavishnu :8680 | **141** | 141/141 |
| Akosha :8682 | **29** | 29/29 |
| Dhara :8683 | **7** | 7/7 |

The TUI auto-projects every running server's tools as
`<server>:<tool> (MCP)` slash commands. The mechanism is uniform,
runs regardless of plugin enablement, and depends only on the MCP
server actually answering `tools/list`.

### 4.2 The /ak, /dh asymmetry is naming-convention drift — proven

When the user types `/akosha` or `/dhara` in the picker and gets
nothing, the cause is **not** "the server isn't reachable" (both
return `/health` HTTP 200) and **not** "the tools aren't exposed"
(both expose 29 and 7 respectively). The cause is that none of
those tools' function names carry the `akosha_*` / `dhara_*`
prefix that the TUI's prefix-match filter requires. Sample tool
names from the live probe:

- Akosha: `search_all_systems`, `get_system_metrics`,
  `analyze_trends`, `detect_anomalies`, `cross_repo_capability_search`…
- Dhara: `health_check_service`, `health_check_all`,
  `wait_for_dependency`, `get_liveness`, `get_readiness`…

Both have full inventories; zero match `/ak` or `/dh` filter.

### 4.3 The `sessions-buddy` pattern that already works

`mcp__session_buddy__list_skills()` returns metadata for available
skills; `search_similar_patterns` and `apply_pattern` are existing
implementations of the server-publishes / client-loads contract.
This is the **proven pattern** to extend to skills AND agents across
all 5 components, and the conversation the user referenced ("Skills
and agents through MCP") concludes on this same architecture.

### 4.4 Bodai marketplace vs client install — both layers needed

- **Marketplace layer** (`/Users/les/Projects/bodai-plugins`,
  v1.0.0): static catalog of 23 plugins. Already ships.
  `enabledPlugins` is currently empty (the plugins are declared
  but not installed).
- **Client-install layer**: a Skill at
  `~/.claude/skills/ecosystem-skill-loader/SKILL.md` that
  dynamically calls `list_skills()` on each component and
  materializes local installs.

The marketplace is the static index; the skill-installer is the
dynamic loader. Both layers coexist.

### 4.5 Persisted memory — durable knowledge for future sessions

Two memory files were saved on 2026-09-09 capturing the picker
auto-exposure mechanism and the per-server naming gap:

- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/mcp-tool-picker-auto-expose.md`
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/bodai-tool-naming-gap-2026-09-09.md`

Any future session that asks "why does `/ak` return nothing?" will
have ground-truth context loaded at startup.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Per-server name= override on 5–10 primary tools"
  - id: REQ-002
    title: "AkoSHA exposes mcp__akosha__list_skills returning at least 3 skill descriptions"
  - id: REQ-003
    title: "Each Bodai MCP server exposes mcp__<server>__list_skills with the same JSON shape"
  - id: REQ-004
    title: "Each Bodai MCP server exposes mcp__<server>__list_agents with the same JSON shape"
  - id: REQ-005
    title: "Skill-installer Skill at ~/.claude/skills/ecosystem-skill-loader/SKILL.md that drives install from list_skills output"
  - id: REQ-006
    title: "Specialist agents (Akosha, Mahavishnu, Session-Buddy, Dhara, Crackerjack) published through list_agents"
  - id: REQ-007
    title: "Install seam is reversible: materialized skills can be removed via uninstall tool"
  - id: REQ-008
    title: "Federated query: a single MCP tool call returns aggregated skills across all 5 components"
```

## 5. Implementation Phases

### Phase 0: Naming-hygiene fix for the immediate picker gap

**Goal**: make `/akosha`, `/dhara`, `/mahavishnu`, `/mahavishnu:pool_route_execute`-style lookups return matches today.

**Tasks**:
1. **Plumbing tools**: add `_meta.fastmcp.tags=["internal", "discovery"]`
   on the metadata-returning tools (`list_skills`, `get_skill`,
   `list_agents`, `get_agent`, `list_ecosystem_skills`,
   `discover_tools`, `pool_route_execute`, `terminal_launch`,
   and any `health_check_*` probes). This is FastMCP 4.0's native
   picker-filtering mechanism and avoids the rename blast radius.
   See §11 blocker H-8.
2. **User-facing tools (5–10 per server)**: add `name=` overrides on
   the `@app.tool()` decorators so function names carry the
   `<component>_*` prefix the TUI's prefix-match filter requires.
   Applies to **AkoSHA**, **Dhara**, **Mahavishnu**, and **Crackerjack**.
3. **Description enrichment**: add a richer `description=` for the
   user-facing tools, with the component name as a CLAUSE (not a
   forced leading noun — leading-noun descriptions add noise to the
   LLM's tool-selection reasoning). Format: `"Search across all
   Akosha-indexed systems..."`, not `"Akosha: Search across..."`.
4. **Crackerjack descriptions**: add `description=` strings to the
   33 Crackerjack tools that currently expose empty descriptions.
   They have names; they lack documentation. The picker auto-exposure
   already works on name alone, but rich descriptions help the LLM
   pick the right tool when multiple options compete.
5. Fulfils REQ-001.

**Exclusion list** (must NOT be in the 5–10 user-facing renames):
`list_skills`, `get_skill`, `list_agents`, `get_agent`,
`list_ecosystem_skills`, `health_check_*`, `get_liveness`,
`get_readiness`, `wait_for_*`, `discover_tools`. These are plumbing
and stay tagged.

**Exit criteria**:
- `/ak` in the picker returns ≥3 entries (verified by live
  `tools/list` probe + tag-filtered projection).
- `/dh` in the picker returns ≥3 entries.
- `mcp__akosha__list_skills()` now returns cleanly named tools.

#### Integration Contract — Phase 0

- **Triggered from**: developer edits a Bodai MCP server source.
- **Returns to / updates**: each `@app.tool(name=..., tags=[...])`
  decorator updates the in-memory tool registry that FastMCP exposes
  via `tools/list`. No persistent state changes.
- **Demonstrable by**: `tests/integration/test_picker_friendly_names_e2e.py`
  per server spins up the server in a subprocess, waits for warmup,
  calls `tools/list`, asserts ≥3 tool names start with the component
  prefix AND plumbing tools carry the `internal` tag.
- **Rollback signal**: `tests/integration/test_picker_friendly_names_e2e.py`
  exits non-zero on CI. The fix is `git revert` of the offending
  commit; no persistent state to unwind.
- **Observability added**: the FastMCP `/health` endpoint already
  exposes tool counts; no new metric needed for this phase. Phase 1
  introduces the four mandatory feed signals.

### Phase 1: Per-component `list_skills` MCP tool

**Goal**: each Bodai server exposes a `list_skills()` MCP tool
returning JSON metadata for at least 3 server-defined skills.

**Tasks**:
1. Define the metadata schema (Pydantic model) — see §11 B-1 for
   full reasoning. Schema is canonical across all 5 servers via
   `from <server>.mcp.skill_schema import SkillMetadata`:
   ```python
   class SkillMetadata(BaseModel):
       schema_version: Literal[1] = 1
       id: str                              # f"{server}:{name}:{version}" — globally unique
       server: str                          # open string, soft-allowlist at consume
       name: str                            # ^[a-z0-9][a-z0-9._-]{0,63}$ — strict allowlist
       description: str                     # ≤1024 chars, no LLM-injection patterns
       version: str                         # semver
       tool_refs: list[str]                 # mcp__<server>__<tool> format; validated
       dependencies: list[str] = []         # other skill names
       content_type: Literal["skill", "agent", "prompt"] = "skill"
       content_hash: str                    # sha256 hex of body bytes
       body_size: int                       # server asserts; client reasserts
       body_format: Literal["yaml-frontmatter+markdown"] = "yaml-frontmatter+markdown"
       allowed_tools: list[str] = []        # explicit allowlist (matches frontmatter allowed-tools)
       signature: str | None = None         # ed25519 over canonicalized payload
       server_pubkey_id: str | None = None  # which key signed it
       timestamp: float                     # ISO float, server-supplied
   ```
2. Add `list_skills()` decorator in each of the 5 Bodai servers,
   returning `list[SkillMetadata]` with `outputSchema` declared
   (FastMCP surfaces JSON Schema for typed responses — see §11 B-1).
3. Add `get_skill(name: str)` decorator in each server, returning
   `{metadata: SkillMetadata, body: str}` where `body` is the
   YAML frontmatter + markdown content the client writes to
   `~/.claude/skills/<server>-<name>/SKILL.md`. Response carries
   `content_hash` of the body; client verifies before write (B-2).
4. **Path-traversal sanitization** (B-4): strict allowlist
   `^[a-z0-9][a-z0-9._-]{0,63}$` on `name` AND `server` values
   enforced at the API boundary. Forbid `/`, `..`, leading `.`.
   Unit test: `tests/unit/test_skill_metadata_schema.py` asserts
   rejection of `"../../foo"`, `"foo/bar"`, `".hidden"`, `"FOO"`.
5. **Signing infrastructure** (B-1): each server ships an ed25519
   keypair; public key pinned in `/health` response; private key
   signs every `get_skill` response. Sub-package
   `<server>/skills_signer/` ships alongside Phase 1 per-server.
   Akosha shipped this in commit `09cef76` (2026-09-09);
   mahavishnu / session-buddy / dhara / crackerjack are pending.
6. Fulfils REQ-003.

**Exit criteria**:
- `mcp__akosha__list_skills()` returns a JSON list of ≥3 entries.
- Schema is shared: `from <server>.mcp.skill_schema import SkillMetadata`
  works identically across all 5.
- `tests/integration/test_list_skills_e2e.py` per server (CI smoke
  test that spins up the server in a subprocess, waits warmup,
  calls the live `mcp__<server>__list_skills()` over streamable-http,
  asserts non-empty response).
- `tests/unit/test_skill_metadata_schema.py` asserts path-traversal
  rejection (B-4).
- `tests/integration/test_get_skill_e2e.py` round-trips and asserts
  `content_hash` matches body bytes (B-1).

#### Integration Contract — Phase 1

- **Triggered from**: the LLM via any `mcp__<server>__list_skills()` call,
  or a Skill / slash command / user prompt.
- **Returns to / updates**: read-only. Returns JSON. No persistent
  state until Phase 2 (skill installer).
- **Demonstrable by**: `pytest tests/integration/test_list_skills_e2e.py`
  per server calls the live MCP server, asserts the response is
  non-empty and matches the `SkillMetadata` schema.
- **Rollback signal**: if `list_skills()` returns invalid JSON, the
  skill-installer phase fails to parse; CI alerts via the existing
  `bodai-activity-subscriber.py` hook (not user-observation).
- **Observability added** (B-7): the new `list_skills` data feed
  MUST expose the four mandatory signals per
  `mcp-backend-wiring-discipline.md` §3:
  - `feed.entities_count` (gauge, current number of skills)
  - `feed.last_updated_timestamp` (gauge; alert at 5× polling interval)
  - `feed.errors_total` (counter, incremented on schema-validation failures)
  - `feed.cycles_total` (counter, incremented per `list_skills` call)
  All four aggregated into `/health` per discipline §1. A degraded
  feed causes `/health` to return 503.

### Phase 2: Skill-installer (the "client-loads" seam)

**Goal**: a Skill at `~/.claude/skills/ecosystem-skill-loader/SKILL.md`
that on invocation fetches the federated skill catalog and on user
selection materializes the chosen skill locally as
`~/.claude/skills/<server>-<name>/SKILL.md`. **Phase 2 is gated on
Phase 1's signing infrastructure (B-1) being operational** — without
signing, the installer is a generic RCE primitive (see §11 B-2).

**Tasks**:
1. Author the Skill — frontmatter fields precisely specified
   (see §11 M-11):
   ```markdown
   ---
   name: ecosystem-skill-loader
   description: Use ONLY when the user explicitly types `/ecosystem-skill-loader` or selects this Skill from the picker to install, find, or load a Bodai-ecosystem skill. Do not auto-trigger. Routes through `mcp__akosha__list_ecosystem_skills` to present choices, then materializes the selected skill at `~/.claude/skills/<server>-<name>/SKILL.md` after explicit user confirmation.
   allowed-tools: mcp__akosha__list_skills, mcp__mahavishnu__list_skills, mcp__session_buddy__list_skills, mcp__dhara__list_skills, mcp__crackerjack__list_skills, mcp__akosha__list_ecosystem_skills, Read, Write, Bash(mkdir:*), Bash(test:*)
   ---
   ```
   The `description` MUST lead with "Use ONLY when the user explicitly
   types" to bias Claude Code's auto-trigger classifier against
   prompt-injection escalation (B-2 / S-2 from MCP review).
2. The Skill body delegates to `mcp__akosha__list_skills` (federated)
   or directly to each `mcp__<server>__list_skills`.
3. **Two-phase install flow** (B-2):
   1. Take a user search query.
   2. Call `list_ecosystem_skills` (or per-server `list_skills`).
   3. Hybrid-search (semantic + lexical) for the best matches.
   4. Present top 3 to the user with `AskUserQuestion`.
   5. On user selection, call `get_skill(name)`. **Verify
      `signature` against the server's published public key (B-1)**.
      If verification fails, abort with a clear error message.
   6. Render the Skill (description + body) to the user with a
      tool-allowlist disclosure: "This Skill will gain access to:
      `<list-of-tools>`. Confirm install?"
   7. On explicit `yes`, write to
      `~/.claude/skills/.pending/<server>-<name>-<ts>/SKILL.md`,
      validate frontmatter (no unknown keys, no LLM-injection patterns
      like `\n\n(system|System|SYSTEM|<system>):` or
      `\n\n###\s*Instruction:`), then atomic rename to the live path.
   8. Re-hash the written file and confirm it matches the server's
      `content_hash`. If mismatch, abort and surface error.
   9. Append to `~/.claude/audit/skill_installs.jsonl` (B-3) with
      `prev_hash` chain link.
   10. Confirm the install by re-reading the directory.
4. **Manifest + audit log files** (B-3, M-2):
   - `~/.claude/skills/.install-manifest.json` — keyed by skill name,
     containing `{server, version, content_hash, signature_ok,
     installed_at, install_path, install_mode}`. Updated atomically
     on every install/uninstall.
   - `~/.claude/skills/.install-log.jsonl` — one JSON line per
     install/uninstall/upgrade event with timestamp, skill name,
     version, sha256, outcome.
   - `~/.claude/audit/skill_installs.jsonl` — append-only audit log
     with **hash-chain** (`prev_hash` per line). Lives outside the
     Skill loader's allowed write paths (B-3 S-8); cannot be deleted
     or overwritten by Skill bodies.
5. **Project-vs-global default** (M-1): detect `<cwd>/.claude/skills/`
   writability; if present, write there; else write to
   `~/.claude/skills/`. Add `--global` flag for explicit override.
6. **Hash-based upgrade** (M-3): compare server's `content_hash` to
   manifest's `content_hash`. Identical = no-op. Different = write
   to `SKILL.md.new`, surface "conflict" in picker. `--dry-run`
   flag previews the diff.
7. **Restart-required disclosure**: every successful install emits
   a one-line toast: "Restart Claude Code to see `<name>` in
   `/<server>` picker."
8. Fulfils REQ-005, REQ-007.

**Exit criteria**:
- User prompts "install a skill that searches Akosha for code
  patterns".
- The Skill fires (via explicit invocation, not auto-trigger), calls
  `mcp__akosha__list_ecosystem_skills`, picks `akosha.search-insights`,
  calls `get_skill(name)`, verifies signature (B-1), renders Skill
  with tool-allowlist disclosure (B-2), waits for explicit `yes`,
  writes to `.pending/`, validates, renames atomically, appends to
  audit log with hash-chain (B-3).
- After install: typing `/ak` returns a new entry that did not exist
  before (after Claude Code restart).
- `tests/integration/test_skill_installer_e2e.py` asserts the entire
  flow including signature verification, two-phase confirmation,
  path-traversal rejection, hash-pin verification, audit-log chain.

#### Integration Contract — Phase 2

- **Triggered from**: explicit user invocation of `/ecosystem-skill-loader`
  or selection from the Skill picker. **Not** auto-trigger.
- **Returns to / updates**: writes a new
  `~/.claude/skills/<server>-<name>/SKILL.md` file (or
  `<cwd>/.claude/skills/...` per project-vs-global default, M-1).
  Reads from the live MCP servers. Audit-log entry to
  `~/.claude/audit/skill_installs.jsonl` (mandatory, hash-chained).
  Manifest update to `~/.claude/skills/.install-manifest.json`.
- **Demonstrable by**: `tests/integration/test_skill_installer_e2e.py`
  drives the install with a synthetic search query, asserts:
  - File written at expected path (after `.pending` → live rename).
  - File contents match server-published metadata and `content_hash`.
  - Signature verified against server's published public key.
  - Manifest and audit log entries present.
  - Audit log hash-chain validates.
  - Path-traversal attempts rejected.
- **Rollback signal**: a `stuck .pending` for >5min indicates a
  crashed installer (mirrors Phase 2's atomic-write rule); surfaced
  via the `doctor` mode (M-10). User can also revert via `git revert`
  of the server commit that introduced the bad Skill — signing
  prevents silent re-install of revoked Skills.
- **Observability added** (B-7): the new `skill_install` feed MUST
  expose the four mandatory signals:
  - `feed.entities_count` (count of installed skills)
  - `feed.last_updated_timestamp` (alert at 5× polling interval)
  - `feed.errors_total` (signature failures, traversal rejections,
    hash mismatches)
  - `feed.cycles_total` (install attempts)
  Aggregated into `/health` per discipline §1. OTel span
  `skill_install` with attributes `{name, version, server,
  source_session_id, install_path, install_mode, duration_ms,
  success}`.

### Phase 3: Per-component `list_agents` MCP tool

**Goal**: each Bodai server exposes `list_agents()` returning
metadata for at least 1 specialist agent. Same installer pattern
as Phase 2 but for `~/.claude/agents/<name>.md`. **Gated on Phase 2's
signing + two-phase install infrastructure** — agents are an even
larger RCE surface than Skills because the body is the system prompt.

**Tasks**:
1. Add `list_agents()` MCP tool in each server. Schema — see
   §11 B-6 for the full rationale:
   ```python
   class AgentMetadata(BaseModel):
       schema_version: Literal[1] = 1
       id: str                              # f"{server_key}:{name}:{version}"
       server_key: str                      # open string (not Literal — see R-5)
       name: str                            # ^[a-z0-9][a-z0-9._-]{0,63}$
       title: str | None = None             # picker display name
       description: str                     # "Use proactively for..."
       version: str = "0.0.0"               # semver, required for federation tie-break
       model: str                           # "sonnet" / "opus"
       tools: list[str] = []                # EXACT tool names (Claude Code frontmatter), NOT regex
       system_prompt: str = ""              # FULL body — Claude Code reads this, not metadata
       dependencies: list[str] = []         # other skill/agent names
       tool_refs: list[str] = []            # MCP tool names referenced
       category: str | None = None
       owner: str | None = None
       status: Literal["active", "archived", "draft"] | None = None
       last_reviewed: str | None = None     # ISO date
       scope: Literal["user-global", "project-local"] = "user-global"
       content_hash: str                    # sha256 of system_prompt bytes
       signature: str | None = None
       server_pubkey_id: str | None = None
   ```
2. Add `get_agent(name: str)` MCP tool in each server, returning
   `{metadata: AgentMetadata, body: str}` where `body == system_prompt`.
   This is the **critical fix from §11 B-6** — without it the
   installer would ship non-functional agents that have no body text.
3. **Disambiguate Session-Buddy's existing `list_skills`** (H-6):
   rename existing workflow-pattern tool to `list_workflow_patterns`,
   reclaim `list_skills` for the new packaging-metadata shape.
4. **Specialist scope boundaries** (R-14): the 3 new specialists
   must each have an explicit "Scope" section in their body that
   names adjacent specialists and what this agent adds:
   - `dhara-specialist` extends `oneiric-specialist`'s adapter-catalog
     scope to the full Dhara surface (storage, registry, key-value).
   - `crackerjack-specialist` extends `mcp-integration-expert`'s
     crackerjack-run scope to the full 47-tool Crackerjack surface.
   - `session-buddy-specialist` is genuinely new (no adjacent).
5. **Specialist dispatcher** (H-3): add
   `mcp__mahavishnu__dispatch_specialist(server: str, task_type: str)`
   in Mahavishnu that looks up `list_agents` and returns the matching
   agent's full definition. Without a dispatcher, the 3 specialists
   become orphans (built but never invoked from a workflow).
   Alternatively, defer the specialists to a separate plan that
   ships the dispatcher.
6. Fulfils REQ-004, REQ-006.

**Exit criteria**:
- `mcp__session_buddy__list_agents()` returns ≥1 entry with
  non-empty `system_prompt` field.
- The 3 missing specialist agents now exist in
  `~/.claude/agents/<server>-<name>.md` (with `<server>-` prefix to
  avoid collisions — see R-7) after install via the seam.
- `mcp__mahavishnu__dispatch_specialist` returns the matching agent
  definition OR the specialists are deferred until a dispatcher
  exists.
- `tests/integration/test_list_agents_e2e.py` per server asserts
  non-empty list AND non-empty `system_prompt` field.
- `tests/integration/test_get_agent_e2e.py` round-trips and asserts
  `content_hash` matches body bytes.

#### Integration Contract — Phase 3

- **Triggered from**: `list_agents()` MCP call. The agent installation
  flow is the same client-loads seam as Phase 2 (signature verified,
  two-phase confirmation, pending dir → live path).
- **Returns to / updates**: writes `~/.claude/agents/<server>-<name>.md`
  (with `<server>-` prefix to mirror Phase 2's skill naming convention).
- **Demonstrable by**: `pytest tests/integration/test_list_agents_e2e.py`
  per server asserts non-empty list with non-empty `system_prompt`.
- **Rollback signal**: a `stuck .pending` for >5min (mirrors Phase 2).
- **Observability added** (B-7): the new `list_agents` data feed MUST
  expose the four mandatory signals, aggregated into `/health`:
  - `feed.entities_count`
  - `feed.last_updated_timestamp` (alert at 5× polling interval)
  - `feed.errors_total`
  - `feed.cycles_total`

### Phase 4: Federation via Akosha's cross-repo search

**Goal**: a single MCP tool call `mcp__akosha__list_ecosystem_skills`
returns aggregated skill metadata from all 5 components. **Gated on
Phase 1 + Phase 1.5 (signing infra) being operational** — federation
cascades the trust model, so unsigned entries must be rejected.

**Tasks**:
1. Add `list_ecosystem_skills()` MCP tool in Akosha's
   `akosha/mcp/tools/ecosystem_skills.py`.
2. Tool body fans out to each `mcp__<server>__list_skills` with
   **per-server timeout** (≤1s), **circuit breaker** (skip server
   with ≥3 failures in last 30s for 60s), and `asyncio.gather(
   return_exceptions=True)` — see §11 H-1.
3. Response shape carries **partial-failure visibility** (R-9):
   ```python
   class EcosystemSkillsResponse(BaseModel):
       schema_version: Literal[1] = 1
       data: list[SkillMetadata]
       errors: dict[str, str]                    # server_key → error message
       per_server_latency_ms: dict[str, int]
       cache: dict                              # {fetched_at, ttl_seconds, stale: bool}
       pagination: dict                         # {next_cursor: str|None, has_more: bool}
   ```
4. **Cache moves from Akosha's HotStore to `~/.akosha/cache/ecosystem_skills.json`** (P-8). HotStore is a vector index; skill
   metadata is low-cardinality, infrequent-change, identifies by
   exact key. File-based cache with TTL and per-server cache key
   (invalidation on `version` change).
5. **Reconcile with installed files** (M-6): the federation response
   also enumerates `~/.claude/skills/<server>-*/SKILL.md` (via the
   manifest from B-3) and surfaces those even if not in the server
   catalog. Stale files for retired skills are surfaced as
   `archived` entries rather than dropped.
6. Aggregates + ranks by relevance to an optional user query.
   Deterministic tie-break: `(relevance_score DESC, server_key ASC,
   name ASC)`.
7. **Pagination day-1** (F-2): cursor-based pagination; default
   `limit=20, cursor=null`. Marketplace stubs add ~46 KiB; without
   pagination MCP transport degrades above 50 KiB.
8. Fulfils REQ-008.

**Exit criteria**:
- `mcp__akosha__list_ecosystem_skills()` returns ≥15 entries
  (3+ from each component) AND surfaces `errors` dict when any
  server is unreachable.
- Latency <2s when all 5 servers are up.
- Test runs against a deliberately-degraded cluster (kill one
  server mid-call): response surfaces `errors["<server>"]` clearly.
- `tests/integration/test_list_ecosystem_skills_e2e.py` asserts
  total ≥ 15, per-component coverage ≥ 3, errors dict populated on
  partial failure, cache freshness surfaced.

#### Integration Contract — Phase 4

- **Triggered from**: the Skill-installer (Phase 2) prefers the
  federated call over per-server calls, falling back to per-server
  if Akosha is unreachable (with N+1 calls but no batching — the
  fallback path is documented but not optimized).
- **Returns to / updates**: read-only. JSON aggregation.
- **Demonstrable by**: `tests/integration/test_list_ecosystem_skills_e2e.py`
  asserts total ≥ 15, per-component coverage ≥ 3, errors dict
  populated on partial failure.
- **Rollback signal**: tool latency > 5s or exception rate > 1%.
  A capacity alert via the existing Grafana integration.
- **Observability added** (B-7): the new federation data feed MUST
  expose the four mandatory signals, aggregated into `/health`:
  - `feed.entities_count` (count of federated entries)
  - `feed.last_updated_timestamp` (alert at 5× polling interval)
  - `feed.errors_total` (per-server failure count)
  - `feed.cycles_total` (federation call count)
  OTel span `akosha.list_ecosystem_skills` with per-child-call
  latency attributes.

### Phase 5: Marketplace ↔ dynamic discovery sync

**Goal**: a static `bodai-plugins` marketplace entry auto-publishes
its skills to running dynamic registries, and vice versa. **The
marketplace stubs do NOT carry signing attestation** — they're
documented as `source_trust="marketplace-stub"` (vs `"bodai-attested"`
for signed entries) and the picker shows a different icon.

**Tasks**:
1. Add a Bodai marketplace `validate` step that scrapes each plugin's
   `commands/` and `skills/` directories and synthesizes stub
   `list_skills` / `list_agents` payloads for plugins that don't
   host their own MCP server. Stubs carry `source_trust=
   "marketplace-stub"`, NO `signature`, and a yellow-triangle
   picker badge.
2. Conversely, dynamic registrations (server-side `list_skills`)
   publish to a static index at `~/.claude/skills/.installer-cache.json`
   (renamed from `.index.json` to clarify it's for the installer,
   NOT a Claude Code input — see §11 L-7).
3. **Polling cadence default ≥5min** (P-7), configurable per-replica
   in `settings/mahavishnu.yaml`. Per-server change detection:
   `list_skills` returns `version: semver`; Session-Buddy caches
   `(server, version, fetched_at)`; polls only when `now -
   fetched_at > ttl` AND the cached version matches the response
   version. Single coordinator Session-Buddy polls; others
   subscribe via HotStore or Redis-style cache (F-3).
4. **Lock file at `~/.claude/skills/.installer-cache.lock`** (F-7)
   for concurrent invocations.
5. **Atomic index write**: write to `.installer-cache.json.tmp` then
   rename (mirror Phase 2's atomic-write rule).
6. **`.installer-cache.json` schema** (P-6):
   ```json
   {
     "schema_version": 1,
     "last_modified": <unix_ts>,
     "server_runs": [
       {"server": "akosha", "version": "0.15.1", "fetched_at": <ts>, "skills": [...]}
     ]
   }
   ```
7. **Reconciliation**: `bodai-plugins validate` is a git-write step
   (the marketplace is a git repo); atomicity across filesystem
   write + git index + git commit must be guaranteed (P-10).
   Failed commit leaves the index in a known state.
8. Fulfils REQ-008 (extended).

**Exit criteria**:
- After `bodai-plugins init` on a 6th repo, the new plugin's
  skills appear in `mcp__akosha__list_ecosystem_skills` within
  one CLI round-trip (≤5min cadence window).
- Polling default ≥5min verified; configurable per-replica.
- Lock file prevents concurrent `.installer-cache.json` corruption.

#### Integration Contract — Phase 5

- **Triggered from**: `bodai-plugins validate` CLI; or a periodic
  poll from Session-Buddy (default ≥5min, configurable).
- **Returns to / updates**: writes `~/.claude/skills/.installer-cache.json`
  (atomic write via `.tmp → rename`); refreshes
  `bodai-plugins/.claude-plugin/marketplace.json` (git commit on success).
- **Demonstrable by**: running `bodai-plugins validate --verbose`
  after creating a new plugin reports the new skills in the
  installer cache AND the marketplace.json.
- **Rollback signal**: marketplace validation exits non-zero; the
  index is wiped to a previous-good version (or `git revert` of
  the validate commit on first deploy).
- **Observability added** (B-7): the new sync data feed MUST expose
  the four mandatory signals, aggregated into `/health`:
  - `feed.entities_count` (count of cached entries)
  - `feed.last_updated_timestamp` (alert at 5× polling interval)
  - `feed.errors_total` (per-server sync failures)
  - `feed.cycles_total` (sync cycle count)
  Plus: surface sync failures in `~/.claude/skills/.sync-errors.json`
  (devops M-2); `ecosystem-skill-loader` reads on next invocation
  and surfaces "X servers failed to sync since last check."

### Phase 6: Agent-installer Skill (analogous to Phase 2)

**Goal**: a Skill at `~/.claude/skills/ecosystem-agent-loader/SKILL.md`
that mirrors Phase 2 but installs agents instead of skills. This
plus Phase 2 completes the "skills and agents through MCP" pattern.
**Gated on Phase 3 + Phase 1.5 (signing) being operational** — agents
are an even larger RCE surface than Skills.

**Tasks**: symmetric to Phase 2. The Skill body reuses the same
two-phase install flow (signature verification, pending dir → live
path, hash-pin verification, audit log with hash-chain, manifest
update). Adds a `list` mode and a `doctor` mode (M-10):

- `list` mode: returns table of all installed agents with name,
  version, install_date, server, install_path.
- `doctor` mode: scans for orphans (file but no manifest entry),
  stale `.pending` (>.5min old), schema mismatches (frontmatter
  missing required fields), duplicates (same `<server>-<name>`
  installed twice).

**Exit criteria**: user explicitly invokes `/ecosystem-agent-loader
install akosha-specialist`, and after confirmation
`~/.claude/agents/akosha-akosha-specialist.md` exists (with the
`<server>-` prefix to mirror Phase 2's naming convention and avoid
collisions — see R-7).

#### Integration Contract — Phase 6

- **Triggered from**: explicit user invocation of `/ecosystem-agent-loader`
  or selection from the Skill picker. **Not** auto-trigger. Body
  text and Skill description must include "Use ONLY when the user
  explicitly types" to bias Claude Code's auto-trigger classifier
  against prompt-injection escalation (mirrors Phase 2's B-2).
- **Returns to / updates**: writes a new
  `~/.claude/agents/<server>-<name>.md` file (with `<server>-` prefix).
  Reads from the live MCP servers. Audit-log entry to
  `~/.claude/audit/agent_installs.jsonl` (mandatory, hash-chained,
  separate log file from skills for forensic clarity). Manifest
  update to `~/.claude/agents/.install-manifest.json`.
- **Demonstrable by**: `tests/integration/test_agent_installer_e2e.py`
  drives the install with a synthetic search query, asserts:
  - File written at expected path (after `.pending` → live rename).
  - File contents match server-published `system_prompt` and
    `content_hash`.
  - Signature verified against server's published public key.
  - Manifest and audit log entries present.
  - Audit log hash-chain validates.
  - Path-traversal attempts rejected.
  - `list` and `doctor` modes return non-empty results.
- **Rollback signal**: a `stuck .pending` for >5min indicates a
  crashed installer (mirrors Phase 2's atomic-write rule); surfaced
  via the `doctor` mode. User can revert via `git revert` of the
  server commit that introduced the bad Agent.
- **Observability added** (B-7): the new `agent_install` feed MUST
  expose the four mandatory signals, aggregated into `/health`:
  - `feed.entities_count` (count of installed agents)
  - `feed.last_updated_timestamp` (alert at 5× polling interval)
  - `feed.errors_total` (signature failures, traversal rejections,
    hash mismatches, duplicate-name attempts)
  - `feed.cycles_total` (install attempts)
  OTel span `agent_install` with attributes `{name, version, server,
  source_session_id, install_path, scope, duration_ms, success}`.

## 6. Required Code Changes

```
~/.claude/
├── skills/
│   ├── ecosystem-skill-loader/SKILL.md              # NEW — Phase 2
│   ├── ecosystem-agent-loader/SKILL.md              # NEW — Phase 6
│   ├── .install-manifest.json                       # NEW — Phase 2/6 (B-3)
│   ├── .install-log.jsonl                           # NEW — Phase 2/6 (B-3)
│   └── .sync-errors.json                            # NEW — Phase 5 (devops M-2)
├── agents/
│   ├── (server-prefixed installed agents)            # NEW — Phase 6
│   └── .install-manifest.json                       # NEW — Phase 6 (B-3)
└── audit/
    ├── skill_installs.jsonl                         # NEW — Phase 2 (B-3, hash-chained)
    └── agent_installs.jsonl                         # NEW — Phase 6 (B-3, hash-chained)

/Users/les/Projects/akosha/akosha/mcp/tools/
├── skill_tools.py                                    # SHIPPED 2026-09-10 — Phase 1 (commit 4951ee8)
├── ecosystem_skills.py                               # NEW — Phase 4
└── agents/                                           # NEW — Phase 3
    └── (specialist definitions)

/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/
├── skill_tools.py                                    # SHIPPED 2026-09-10 — Phase 1 (commit d722d2fa)
├── ecosystem_skills.py                               # OPTIONAL cross-link
└── dispatch_specialist.py                            # NEW — Phase 3 (H-3, dispatcher)

/Users/les/Projects/session-buddy/session_buddy/mcp/tools/
├── list_workflow_patterns.py                         # SHIPPED 2026-09-10 — Phase 1 (H-6, rename existing; commit 02235271)
└── skills_loader_extension.py                        # NEW — Phase 2
    # (list_skills already exists; this adds installer hooks)

/Users/les/Projects/dhara/dhara/mcp/tools/
└── skill_registry.py                                 # SHIPPED 2026-09-10 — Phase 1 (commit 2e3a65fa)

/Users/les/Projects/crackerjack/crackerjack/mcp/tools/
└── skill_registry.py                                 # SHIPPED 2026-09-10 — Phase 1 (commit e99edb6a)

~/.akosha/cache/
└── ecosystem_skills.json                             # NEW — Phase 4 (cache move from HotStore)

# Replicated per server: <server>/skills_signer/            # NEW per-server package — Phase 1.5 (B-1)
#   - akosha/skills_signer/                              # SHIPPED 2026-09-09 (commit 09cef76)
#   - mahavishnu/skills_signer/                          # pending — next replication
#   - session_buddy/skills_signer/                       # pending
#   - dhara/skills_signer/                               # pending
#   - crackerjack/skills_signer/                         # pending
#
# Package contents (identical across all 5 servers — sed-replace the
# module path `akosha.skills_signer.X` -> `<server>.skills_signer.X`):
├── __init__.py                                        # public surface
├── canonicalize.py                                    # deterministic JSON (B-2 Pydantic mode='json')
├── keys.py                                            # ed25519 keypair + load_or_create_keypair (R2-H1 persistence)
├── manifest.py                                        # PubkeyManifest + multi-entry rotation (R2-M1)
├── sign.py                                            # SkillsSigner + pubkey_manifest() method (R1-H1)
├── verify.py                                          # raises UnknownKeyIdError (R1-H6)
├── errors.py                                          # SkillsSignerError hierarchy
└── (one mcp module per server) signer_feed.py          # closure-owned SignerFeedState — 4 mandatory feed signals

# Per-server MCP wiring:
akosha/mcp/signer_feed.py                              # SHIPPED 2026-09-09
mahavishnu/mcp/signer_feed.py                          # NEW for Phase 1.5 replication
session_buddy/mcp/signer_feed.py                       # NEW for Phase 1.5 replication
dhara/mcp/signer_feed.py                               # NEW for Phase 1.5 replication
crackerjack/mcp/signer_feed.py                         # NEW for Phase 1.5 replication

tests/
├── unit/test_skill_metadata_schema.py                # NEW — Phase 1 (B-4 path-traversal)
├── unit/test_agent_metadata_schema.py                # NEW — Phase 3
├── test_skills_signer.py                              # NEW per server — Phase 1.5 (B-1 signing) [akosha: SHIPPED 49 tests]
├── integration/test_health_aggregator_e2e.py          # NEW per server — Phase 1.5 (B-7 four mandatory signals)
├── integration/test_picker_friendly_names_e2e.py     # MOVED from tests/manual/ (Phase 0)
├── integration/test_list_skills_e2e.py               # NEW — Phase 1
├── integration/test_get_skill_e2e.py                 # NEW — Phase 1 (B-1 hash-pin)
├── integration/test_list_agents_e2e.py               # NEW — Phase 3 (B-6 system_prompt)
├── integration/test_get_agent_e2e.py                 # NEW — Phase 3
├── integration/test_skill_installer_e2e.py            # NEW — Phase 2 (B-2 two-phase)
├── integration/test_skill_installer_safety.py        # NEW — Phase 2 (B-4 path-traversal, hash-pin)
├── integration/test_agent_installer_e2e.py            # NEW — Phase 6 (B-5)
├── integration/test_list_ecosystem_skills_e2e.py     # NEW — Phase 4 (H-1 partial-failure)
└── integration/test_ecosystem_skills_partial_failure.py  # NEW — Phase 4 (kill-server-mid-call)
```

## 7. Validation Matrix

| Check | Expected | Evidence location |
|---|---|---|
| `mcp__akosha__list_skills()` returns ≥3 entries | schema-compliant JSON with `id`, `content_hash`, `signature`, `server_pubkey_id` | tests/integration/test_list_skills_e2e.py |
| `mcp__<server>__list_skills()` returns ≥3 entries for all 5 servers | 5/5 pass with signing verified | tests/integration/test_list_skills_e2e.py |
| Path-traversal attempts rejected | 100% rejection of `/`, `..`, leading `.`, uppercase | tests/unit/test_skill_metadata_schema.py (B-4) |
| `get_skill(name)` round-trip | body matches `content_hash`; signature verifies against server pubkey | tests/integration/test_get_skill_e2e.py (B-1) |
| Typing `/ak` in picker returns ≥3 entries | new skill-installer-installed skills | tests/integration/test_picker_friendly_names_e2e.py |
| Phase 2 installer round-trip installs a skill atomically | `~/.claude/skills/akosha-X/SKILL.md` exists after explicit `yes` | tests/integration/test_skill_installer_e2e.py |
| Two-phase confirmation gates install | `.pending/` write → user `yes` → live rename | tests/integration/test_skill_installer_e2e.py (B-2) |
| Audit log hash-chain validates | each line's `prev_hash` matches prior line's hash | tests/integration/test_skill_installer_e2e.py (B-3) |
| Federation returns ≥15 skills across all 5 components | 3 per component | tests/integration/test_list_ecosystem_skills_e2e.py |
| Federation partial-failure surfaces errors | killing one server mid-call populates `errors[<server>]` | tests/integration/test_ecosystem_skills_partial_failure.py (H-1) |
| No duplicate skill names across installs | 100% uniqueness with `<server>-` prefix | tests/integration/test_skill_installer_e2e.py |
| Specialist agents have non-empty `system_prompt` field | body text is present in metadata | tests/integration/test_list_agents_e2e.py (B-6) |
| Specialist agents are invokable via dispatcher | `mcp__mahavishnu__dispatch_specialist(server, task_type)` returns matching agent | tests/integration/test_dispatch_specialist.py (H-3) |
| All four mandatory feed signals present per feed | `entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total` | tests/integration/test_health_aggregator_e2e.py (B-7) |
| `/health` returns 503 when any feed degraded | simulated degraded feed triggers 503 | tests/integration/test_health_aggregator_e2e.py (B-7) |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Auto-exposure doesn't auto-update when marketplace changes | Medium | Phase 5 polls explicitly (≥5min default); on installer restart the user gets the latest |
| Skill name collisions across servers | High | Phase 2 prefixes installs with `<server>-`; a `deletes_isolated` test enforces no two installed skills share a directory |
| Federation call latency > 2s | Medium | Cache `list_ecosystem_skills` for 60s in `~/.akosha/cache/ecosystem_skills.json` (file-based, not HotStore); per-server timeout 1s + circuit breaker |
| Servers with empty `list_skills` registration | Medium | Phase 0 catches this; `tests/integration/test_list_skills_e2e.py` enforces ≥3 |
| Specialist agents clash with `~/.claude/agents/` files in repo | Medium | Phase 3 places agents in `~/.claude/agents/<server>-<name>.md` (user-global), keeping `<repo>/.claude/agents/` for repo-local specialists only |
| **Server-supplied skill body = RCE primitive** | **High** | **B-1 (signing) + B-2 (two-phase confirmation) + B-4 (path-traversal allowlist). Phase 2 cannot ship without signing.** |
| **Server-supplied agent body = RCE primitive** | **High** | **B-6 + signing. Phase 6 cannot ship without signing.** |
| Manifest/audit-log file deleted by malicious Skill body | Medium | B-3: audit log at `~/.claude/audit/skill_installs.jsonl` outside Skill loader's allowed write paths; hash-chain detects retroactive modification |
| 3 specialists shipped with no caller (orphan risk) | High | H-3: ship `mcp__mahavishnu__dispatch_specialist` in Phase 3 OR defer specialists until dispatcher exists |
| Federation cascade of trust model (unsigned → signed) | High | Phase 4 gated on Phase 1.5 signing infra |
| Cross-project pollution from `~/.claude/skills/` installs | Medium | M-1: project-vs-global default with `--global` flag override |
| Boot-time regression from 100+ installed skills | Medium | M-7: benchmark before/after Phase 2; if >2s regression, add `.lazy` marker for deferred parse |
| HotStore pollution from skill metadata | Low | Phase 4 cache moves from HotStore to `~/.akosha/cache/ecosystem_skills.json` |
| Marketplace stubs indistinguishable from signed entries | Medium | Phase 5 stubs carry `source_trust="marketplace-stub"`, no `signature`, yellow-triangle picker badge |
| `enabledPlugins` empty for bodai-plugins | Low | Phase 5 documents the choice: enable relevant plugins OR document marketplace as inert |

## 9. Decision Rule

The plan is split into **two release windows** — see §10 Split Plan
for the coordinated sequence. The user-visible win is split across
the windows:

**MVP window** (Phase 0 + Phase 1, plus Phase 1.5 signing infra):
- All 6 Bodai prefixes return ≥3 entries in the picker
- `list_skills` and `get_skill` MCP tools live in all 5 servers
- Signing infrastructure operational; unsigned entries rejected
- `/health` aggregator exposes the four mandatory feed signals
- **No installer seam yet** — Skills are advertised but not installed

**Security-gated window** (Phase 2 + Phase 3 + Phase 4 + Phase 5 + Phase 6):
- All 5 missing specialist agents discoverable via Agent picker
- Skill-installer + Agent-installer operational with two-phase
  confirmation, signing, hash-chain audit log
- Federation via Akosha with partial-failure visibility
- Marketplace sync operational

The plan is "done enough" when **both windows** are complete AND
the cross-cutting operational surfaces (manifest, audit log,
doctor mode) are functional.

Phase 0 + Phase 1 ship in any order (Phase 0 first is cleaner for
picker parity). Phase 4 ships after Phase 1's signing infra lands
(Phase 1.5). Phase 2 ships after Phase 1.5. Phase 3 ships after
Phase 1.5 + dispatcher spec. Phase 5 ships after Phase 4. Phase 6
ships after Phase 3 + Phase 4.

## 10. Split Plan — MVP Window vs Security-Gated Window

The 5-agent multi-lens review on 2026-09-09 converged on the
recommendation to split the plan into two release windows. The MVP
window delivers picker parity + discovery surface; the security-
gated window delivers the installer primitives that carry the RCE
risk. Both windows ship from the same plan; the split is a release
sequence, not a separate plan.

### 10.1 MVP Window — Picker parity + discovery

**Goal**: the user types `/akosha` and sees real entries that do
real work for that component. Phase 0 + Phase 1 + Phase 1.5 (signing
infra) plus the per-server `list_skills` data feeds.

**Phases**: 0, 1, 1.5 (signing infrastructure that gates everything
downstream). **Status 2026-09-10**: Phase 1.5 implemented and shipped in all 5
servers (commit `09cef76` akosha → `24e410c8` mahavishnu → fan-out
agents `6b0bcd9b` session-buddy, `c604efe` dhara, `6c9eff2f`
crackerjack). The MVP window is **5/5 servers shipped**. The
post-fan-out cross-server consistency review (2026-09-10) closed
the only Important finding (session-buddy redundant-init) and applied
a single Cosmetic finding; see §10.4 for details.

**Phase 1.5 — skills_signer infrastructure**:

1. **Per-server sub-package** `<server>/skills_signer/` ships with
   ed25519 keypair generation, signature verification, and
   public-key manifest. Package layout is identical across all 5
   servers; replication is sed-replace of `akosha.skills_signer.X`
   → `<server>.skills_signer.X`. The `<server>/skills_signer/`
   package is pure data + cryptography (no MCP wiring); the
   per-server wiring lives in `<server>/mcp/signer_feed.py`.

   **Per-server status**:
   - akosha: SHIPPED 2026-09-09 (commit `09cef76`) + 2026-09-10 review
     fix (commit `223101d` cosmetic raise-format); 49 unit tests
     passing; live `/health` verified.
   - mahavishnu: SHIPPED 2026-09-10 (commit `24e410c8`); 49 unit tests
     passing; live `/health` verified.
   - session-buddy: SHIPPED 2026-09-10 (commit `6b0bcd9b`) + review
     fix (commit `86d70f5f` redundant-init guard); 49 unit tests
     passing; live `/health` verified.
   - dhara: SHIPPED 2026-09-10 (commit `c604efe`); 49 unit tests
     passing; live `/health` verified.
   - crackerjack: SHIPPED 2026-09-10 (commit `6c9eff2f`) + 8 `name=`
     overrides for H-8 naming hygiene; 49 unit tests passing; live
     `/health` verified.

2. Each Bodai server ships a keypair; public key pinned in `/health`
   under `checks.skills_signer` (the 4 mandatory feed signals +
   computed `ok`).
3. `get_skill` and `get_agent` MCP responses (Phase 1) carry
   `signature` and `server_pubkey_id` fields.
4. The installer (Phase 2/6) verifies signature against the
   server's `/health` manifest before any write.
5. **Until Phase 1.5 ships in a given server**, that server's
   `get_skill` / `get_agent` responses carry `signature=null` and
   clients reject them — clients surface "Signing infrastructure
   pending" rather than fail-open.
6. Tests: per server, `tests/test_skills_signer.py` (not
   `tests/unit/test_skills_signer_e2e.py`) covers keypair
   generation, signature round-trip, tampering rejection. Plus
   per-server `tests/integration/test_health_aggregator_e2e.py`
   for the 4-signal `/health` assertion.

**Exit criteria for MVP window**:
- All 6 Bodai prefixes return ≥3 entries in the picker (Phase 0).
- All 5 servers expose `list_skills` with the extended schema
  (Phase 1).
- All 5 servers expose `get_skill` with signature verification
  (Phase 1.5).
- All 5 servers' `/health` aggregators expose the four mandatory
  feed signals per server (Phase 1, B-7).
- **No installer seam ships in this window** — Skills are
  advertised but not yet installable via the seam.

**Rollback path**: revert Phase 0 + Phase 1 + Phase 1.5 commits
per repo. The picker reverts to its pre-plan state (Phase 0 names
go away; descriptions stay enriched). Federation reverts to
per-server calls only.

### 10.2 Security-gated Window — Installer primitives

**Goal**: the user can install a Skill or Agent from a natural-
language prompt, with signing verification, two-phase confirmation,
and hash-chain audit log.

**Phases**: 2, 3, 4, 5, 6. Each is gated on signing infrastructure
(Phase 1.5) being operational.

**Cross-window coordination**:
- Phase 4 (federation) cannot ship until ALL 5 servers have
  Phase 1 + Phase 1.5 in production — federation cascades the trust
  model and one unsigned server breaks it.
- Phase 2 (skill installer) cannot ship until Phase 1.5 is
  operational — without signing, the installer is a generic RCE
  primitive.
- Phase 3 (agent installer) cannot ship until Phase 1.5 +
  dispatcher spec are operational.
- Phase 5 (marketplace sync) cannot ship until Phase 4 is
  operational — federation is the substrate.
- Phase 6 (agent installer Skill) cannot ship until Phase 3 is
  operational.

**Coordinated release sequence**:
1. **Week 1**: Phase 0 ships in all 5 repos (independent per repo).
2. **Week 2**: Phase 1 ships in all 5 repos (independent per repo).
3. **Week 3**: Phase 1.5 ships in all 5 repos (independent per repo).
   - [x] akosha: shipped 2026-09-09 (commit `09cef76`) + 2026-09-10 review
     fix (commit `223101d`).
   - [x] mahavishnu: shipped 2026-09-10 (commit `24e410c8`).
   - [x] session-buddy: shipped 2026-09-10 (commit `6b0bcd9b`) +
     2026-09-10 review fix (commit `86d70f5f`).
   - [x] dhara: shipped 2026-09-10 (commit `c604efe`).
   - [x] crackerjack: shipped 2026-09-10 (commit `6c9eff2f`).
   - [x] akosha: Phase 1 `4951ee8` (list_skills + get_skill + shared
     SkillMetadata schema) + `0dd7176` (signature alignment per §10.5).
   - [x] mahavishnu: Phase 1 `d722d2fa`.
   - [x] session-buddy: Phase 1 `02235271` (H-6 rename) + `987c3096`.
   - [x] dhara: Phase 1 `2e3a65fa` + `9e81d98` (trailing newline).
   - [x] crackerjack: Phase 1 `e99edb6a`.
   - [x] Cross-server review: §10.5 closed 2026-09-10; 0 Blockers, 0
     Important; 1 Important applied (akosha signature alignment), 1
     Cosmetic applied (dhara trailing newline).
4. **Week 4**: Phase 4 ships in Akosha (depends on Phase 1 + 1.5 in
   all 5 repos being operational).
   - [ ] akosha: Phase 4 federation (`list_ecosystem_skills`) —
     implementation in flight (a subagent dispatched; tracked under
     §10.2 Week 4 sub-list).
5. **Week 5**: Phase 2 + Phase 3 ship (depend on Phase 1.5).
   - [x] **Phase 2 SHIPPED 2026-09-10** in dot-claude repo (commit
     `adf577a6`): `~/.claude/skills/ecosystem-skill-loader/` body
     + `scripts/installer.py` + `tests/integration/test_skill_installer_e2e.py`.
     Picker auto-exposure verified by Claude Code's hook.
     21/21 E2E tests pass in 0.13s.
   - [ ] akosha: Phase 3 server-published agents (reference impl
     in flight; tracked under §10.2 Week 5 sub-list).
   - [x] mahavishnu: Phase 3 fan-out `d722d2fa` predecessor + agent
     in flight (a Python-pro subagent is writing the fan-out; ack
     pending commit SHA).
   - [ ] session-buddy: Phase 3 fan-out — agent in flight.
   - [ ] dhara: Phase 3 fan-out — agent in flight.
   - [x] crackerjack: Phase 3 fan-out `f3eadda7` (44 unit + 16
     integration tests passing locally).
6. **Week 6**: Phase 5 + Phase 6 ship (depend on Phase 4 and Phase 3
   respectively).
   - [x] **Phase 6 SHIPPED 2026-09-10** in dot-claude repo (commit
     `f242756`): `~/.claude/skills/ecosystem-agent-loader/` body
     + `scripts/installer.py` + `tests/integration/test_agent_installer_e2e.py`.
     36/36 E2E tests pass in 0.24s. Picker auto-exposure verified.
     Gated on Phase 3 dispatcher for full activation; the Skill body
     already works against any server-published `list_agents` /
     `get_agent` MCP tool.
   - [ ] Phase 3 dispatcher (`mcp__mahavishnu__dispatch_specialist`,
     H-3) — pending (depends on Phase 3 fan-out completion).

**Exit criteria for security-gated window**:
- A user prompts "install a skill that searches Akosha for code
  patterns"; the Skill fires via explicit invocation, signature
  verifies, two-phase confirmation gates the write, audit log
  entry appended with hash-chain.
- All 5 missing specialist agents discoverable via Agent picker
  (Phase 3 + dispatcher).
- Federation via Akosha returns ≥15 entries with partial-failure
  visibility.
- Marketplace sync operational (Phase 5).
- `ecosystem-skill-loader doctor` and `ecosystem-agent-loader
  doctor` modes surface orphans, stale locks, schema mismatches.

**Rollback path**: revert per-phase commits. The audit log file
at `~/.claude/audit/skill_installs.jsonl` is append-only and
hash-chained, so retroactive modification is detectable — the
rollback path is honest about what was installed and what was
uninstalled.

### 10.3 Per-Server Wiring Contract — Phase 1.5 replication

Replicating `<server>/skills_signer/` is the easy part
(sed-replace). **The wiring** — lifespan-or-equivalent,
`/health` aggregation, MANDATORY_GROUPS, persistence path,
schema ownership, route collision, tool group split — is the
hard part, and each server's shape differs. This section is the
authoritative contract; a developer reading only this section
plus the package source can replicate Phase 1.5 without re-reading
the akosha code.

#### 10.3.1 MANDATORY_GROUPS — every replica

The new tool group (`_register_skills_signer_tools`) MUST be added
to the server's mandatory-groups list (always-registered regardless
of profile tier). Reasoning: signing verification is on every
Phase 2/6 install; a MINIMAL-profile deployment that loses the
signer feed fails B-7's partial-closure test. Per server:

- akosha: already in `AKOSHA_MANDATORY_GROUPS` (Phase 1.5 ships).
- mahavishnu: add to `MAHAVISHNU_MANDATORY_GROUPS` at
  `mahavishnu/mcp/tools/profiles.py:182-187`.
- session-buddy: equivalent constant in
  `session_buddy/mcp/tools/profiles.py`.
- dhara: equivalent constant in `dhara/mcp/tools/profiles.py`.
- crackerjack: equivalent constant in
  `crackerjack/mcp/tools/profiles.py`.

The same applies to `list_skills` and `get_skill` MCP tools
(Phase 1) — they MUST be in the mandatory group so the picker
parity story holds at MINIMAL tier.

#### 10.3.2 Lifespan / wiring model — per server

The akosha model uses an async `@asynccontextmanager async def
lifespan(server)` with `yield`, initializing the keypair and
signer feed state before the probe is registered. The other 4
servers have different shapes:

- **akosha**: async lifespan (already wired; reference impl).
- **mahavishnu**: **sync `__init__`**, NO async lifespan. Health
  endpoint registered in `__init__` for launchd's early-probe
  (per `mahavishnu/mcp/server_core.py:59-69`). The launchd wrapper
  (`launch_with_healthcheck.sh`) tolerates up to 120s startup.
  
  **Mandated contract for mahavishnu**: do NOT add a
  FastMCP `lifespan=` kwarg (breaks the early-`/health` design).
  Instead, **defer signer init into `start()`** (after FastMCP
  app is built). During the brief warm-up window, `/health`
  returns 503 (no signer feed yet). Keypair load is sub-second,
  so the warm-up window is brief. This is option (c) of the
  mcp-integration-expert's 2026-09-09 analysis.
  
- **session-buddy**: has async lifespan — replicate akosha's
  pattern.
- **dhara**: instance-based with `_runtime_status` at
  `dhara/mcp/server_core.py:380-396`; add signer state to
  the instance `_runtime_status` and surface it in the
  health aggregator.
- **crackerjack**: **static 200 `/health` route** at
  `crackerjack/mcp/server_core.py:126-141` with no lifespan.
  Convert the static route to a feed-aggregating closure OR
  surface the signer feed in a separate `/health/skills_signer`
  endpoint (less ideal but matches the existing static pattern).

#### 10.3.3 `/health` route aggregation — extend, don't replace

Every server except crackerjack has an existing `/health` route
body that returns static content (akosha now has a feed-aggregating
one; the others do not). The replicator MUST **extend the existing
closure**, not register a second `@server.custom_route("/health")`.
Starlette raises `AssertionError` on duplicate route registration.

Per server:

- akosha: already feed-aggregating; reference impl at
  `akosha/mcp/server.py:1026-1063`.
- mahavishnu: extend the existing closure at
  `mahavishnu/mcp/bootstrap.py:195-197`. Consult the feed
  aggregator state; return 503 when any feed reports `ok=False`.
  During the warm-up window before `start()` completes, return
  503 with `checks.skills_signer.error = "awaiting start()"`.
- session-buddy: extend the existing closure.
- dhara: extend `_runtime_status` aggregation.
- crackerjack: convert static-200 to feed-aggregating, OR
  add separate `/health/skills_signer` endpoint.

The MCP `get_health` tool (where one exists) MUST also include
`checks.skills_signer` in its return shape — mahavishnu has
both an HTTP `/health` route and an MCP `get_health` tool at
`mahavishnu/mcp/server_core.py:1072`; both must surface the
signer feed.

#### 10.3.4 Persistence path — per server

The private key persists at `<server_home>/state/skills_signer/private_key.pem`
with 0o700 parent and 0o600 file permissions. Override via env
var `<SERVER>_SKILLS_SIGNER_KEY_PATH` for tests / non-standard
locations.

| Server | Default path | Override env var |
|---|---|---|
| akosha | `~/.akosha/state/skills_signer/private_key.pem` | `AKOSHA_SKILLS_SIGNER_KEY_PATH` |
| mahavishnu | `~/.mahavishnu/state/skills_signer/private_key.pem` | `MAHAVISHNU_SKILLS_SIGNER_KEY_PATH` |
| session-buddy | `~/.session_buddy/state/skills_signer/private_key.pem` | `SESSION_BUDDY_SKILLS_SIGNER_KEY_PATH` |
| dhara | `~/.dhara/state/skills_signer/private_key.pem` | `DHARA_SKILLS_SIGNER_KEY_PATH` |
| crackerjack | `~/.crackerjack/state/skills_signer/private_key.pem` | `CRACKERJACK_SKILLS_SIGNER_KEY_PATH` |

The path is resolved at lifespan (or `start()`) entry, NOT at
import time, so tests can override before the path is computed.

#### 10.3.5 Schema ownership — `SkillMetadata`

`SkillMetadata` (and `AgentMetadata` in Phase 3) is canonical
across all 5 servers. Two valid ownership models:

- **Cross-repo import** (recommended for the MVP window):
  each server adds `akosha>=0.15.1` to its ecosystem dep group
  and `from akosha.mcp.skill_schema import SkillMetadata`.
  Simplest path; matches the existing `akosha>=0.12.0` pin in
  mahavishnu's pyproject.toml ecosystem group.
- **Per-server copy** (acceptable, more drift risk): each server
  owns `mahavishnu/mcp/skill_schema.py` (etc.) with identical
  content; updates must land in all 5.

The plan does NOT pick — both are valid. The cross-repo import
is the lowest-friction path and the existing ecosystem dep
already supports it.

#### 10.3.6 Tool group split — REGISTRATION_MAP path

The new tools (`list_skills`, `get_skill`, signer feed registration)
MUST go through the server's `REGISTRATION_MAP` (profile-gated
group registration), not the inline `_register_tools()` block.
This matches akosha's pattern and makes the MANDATORY_GROUPS
decision in §10.3.1 meaningful. Mahavishnu-specific: the new
group's lambda follows the existing `_mhv_server` back-reference
convention at `mahavishnu/mcp/server_core.py:74`:

```python
PROFILE_REGISTRATIONS[MAHAVISHNU_MANDATORY_GROUPS].extend([
    lambda s: _register_skills_signer_tools(s._mhv_server),
])
```

#### 10.3.7 E2E test contract (B-7 closure)

Per server, the per-server E2E test
`tests/integration/test_health_aggregator_e2e.py` MUST assert:

- pre-lifespan / pre-`start()`: `/health` returns 503 with
  `checks.skills_signer.error = "not initialized"` (or
  equivalent per-server sentinel).
- post-lifespan / post-`start()`: `/health` returns 200, all 4
  mandatory feed signals present in `checks.skills_signer`,
  `ok` computed true (manifest non-empty).
- post-teardown: `/health` returns 503 (probe unregistered).
- Empty manifest: `checks.skills_signer.ok = False` → 503.

These four assertions per server are the gating artifacts for
B-7's full closure. Until they land in each replica, B-7 stays
"partially closed" per server.

### 10.4 Phase 1.5 Cross-Server Review — closed 2026-09-10

A read-only cross-server consistency audit ran on 2026-09-10 across
all 5 Phase 1.5 replicas. The audit exercised 5 lenses:

| Lens | What it checks | Result |
|---|---|---|
| 1. `__all__` parity | `skills_signer/__init__.py` exports identical 22-symbol list in identical order | ✅ all 5 |
| 2. `canonicalize.py` parity | `SIGNATURE_FIELDS_TO_STRIP` field set, `model_dump(mode="json")` pin, `extra_exclude_keys` handling | ✅ all 5 |
| 3. `manifest.py` parity | `as_dict()` shape, `SUPPORTED_ALGORITHM = "ed25519"`, `InvalidManifestAlgorithmError` exception type | ✅ all 5 |
| 4. `signer_feed.py` 9-key payload | `feed_entities_count`, `feed_last_updated_timestamp`, `cycles_total`, `errors_total`, `ok`, `feed`, `key_count`, `pubkeys`, `generation` in identical order | ✅ all 5 (akosha's module API surface differs but `as_dict()` output is byte-equivalent) |
| 5. **Production-lifespan parity** | Each server's actual `python -m server start` path calls `init_signer_feed_state()` on production (not just tests) | ⚠️ 4/5, session-buddy had a redundant second init |

**Findings applied:**

| Severity | Server | File:line | Fix |
|---|---|---|---|
| Important | session-buddy | `session_buddy/mcp/server.py:344` | Added `if get_signer_feed_state() is None:` guard so the wrapper becomes a no-op when the wrapped `session_lifecycle` has already initialized. Defense-in-depth preserved. Commit `86d70f5f`. **Verified at runtime:** restart produces `generation=0` (single init); without the guard, would have been 1. |
| Cosmetic | akosha | `akosha/skills_signer/manifest.py:216` | Reformatted raise from 1-line to 2-line to match the other 4 servers. Commit `223101d`. |
| Cosmetic | akosha | `akosha/skills_signer/manifest.py:23-25` | **False positive** — akosha's import order is `import base64`, `import time`, `from dataclasses`, `from typing`; ruff `I001` is satisfied (verified). The audit's "match the other 4 servers" guidance was based on incorrect reconnaissance (mahavishnu has `import time` AFTER `from dataclasses` — both orderings pass ruff). No fix applied. |
| Cosmetic | akosha | `akosha/mcp/signer_feed.py` module API | **By design** — akosha constructs `SignerFeedState` inline in the lifespan closure; the other 4 export the full `init_/get_/reset_signer_feed_state` helper set because they lazily initialize. Both are valid implementations; the bar is byte-equivalent `as_dict()` output, not byte-equivalent module API surface. No fix applied. |

**Cross-cutting decisions:**

- **No other server has the redundant-init pattern.** Grep across all 5 servers confirms each has exactly ONE `init_signer_feed_state()` call site on its production path. Session-buddy's pattern (lifespan wrapper re-running init) was unique to its `_lifespan_with_dhara_cleanup` architecture. The other 4 servers initialize once and are done.
- **Phase 1.5 wire protocol is byte-equivalent** across all 5 servers. Phase 2/6 installers that read `/health` and parse `pubkeys[]` + `key_count` will see identical shape from any of the 5.
- **Per-server E2E test (`tests/integration/test_health_aggregator_e2e.py`) deferred to Phase 2** — single-instance servers (mahavishnu, crackerjack, akosha's lifespan-closure pattern) lack the pre-lifespan 503 case the §10.3.7 contract specifies; the unit-level `TestSignerFeedState::test_503_payload_shape` covers the empty-manifest path. Full E2E lands with the Phase 2 installer.

### 10.5 Phase 1 Cross-Server Review — closed 2026-09-10

A read-only cross-server consistency audit ran on 2026-09-10 across
all 5 Phase 1 replicas (the per-server `list_skills` / `get_skill` MCP
tools + shared `SkillMetadata` schema). The audit exercised 6 lenses:

| Lens | What it checks | Result |
|---|---|---|
| 1. `SkillMetadata` schema parity | 16-field shape, B-4 allowlist, `..` defense, `id` shape, `extra="forbid"` | ✅ all 5 (byte-equivalent modulo docstring refs) |
| 2. Signing integration parity | `signer.sign(canonical_payload_for_signing(metadata_dict))`, `record_cycle()` bumping, `content_hash` derivation, `body_size` | ✅ all 5 |
| 3. Lifespan / singleton helper parity | `SignerFeedState.signer` field, `init_signer_feed_state` constructs signer, init/get/reset helpers, init wiring site | ✅ all 5 |
| 4. REGISTRATION_MAP + tier parity | `register_skill_tools`/`register_skill_registry` in REGISTRATION_MAP, tier (STANDARD vs MANDATORY), prefixed `name=` overrides | ✅ all 5 (3 STANDARD + 2 MANDATORY-style) |
| 5. API surface parity | `init_signer_feed_state()` signature (param-accepting vs parameterless), singleton helpers | ✅ all 5 (after the akosha alignment; was 4-of-5) |
| 6. H-6 collision | session-buddy's rename + reclaim of `list_skills` | ✅ clean |

**Findings applied**:

| Severity | Server | Commit | Description |
|---|---|---|---|
| Important | akosha | `0dd7176` | Aligned `init_signer_feed_state` from param-accepting `(state)` to parameterless `() -> SignerFeedState`. Restored byte-equivalent helper API across all 5 servers. 2-file refactor (signer_feed.py + server.py lifespan closure). |
| Cosmetic | dhara | `9e81d98` | Added missing trailing newline to `__all__` line in `dhara/mcp/skill_schema.py`. Single-byte change. |

**Cross-cutting decisions**:

- **Phase 1 wire protocol is byte-equivalent** across all 5 servers. `SignerFeedState.as_dict()` returns the same 9-key payload (`ok`, `feed`, `feed_entities_count`, `feed_last_updated_timestamp`, `cycles_total`, `errors_total`, `generation`, `key_count`, `pubkeys`) for any of the 5. Phase 2's installer that reads `/health` and parses `pubkeys[]` + `key_count` will see identical shape from any server.
- **Phase 1 public helper API is byte-equivalent** after the akosha alignment: all 5 servers expose parameterless `init_signer_feed_state() -> SignerFeedState`, plus `get_signer_feed_state()` and `reset_signer_feed_state()`. Phase 3+ callers can use one helper API across the ecosystem.
- **Tier gating has 3 STANDARD + 2 MANDATORY-style**: akosha, session-buddy, crackerjack gate `register_skill_tools` at STANDARD tier. Mahavishnu wires `_register_skills_signer_tools` through both MINIMAL_REGISTRATIONS and MANDATORY_GROUPS (belt-and-suspenders). Dhara puts `register_skill_registry_group` in `DHARA_MANDATORY_GROUPS` only (always-on, since dhara has only 7 total tools vs akosha's 29).
- **File-name split is intentional**: dhara and crackerjack use `skill_registry.py` per plan §6; akosha, mahavishnu, session-buddy use `skill_tools.py`. Both names are valid; matches the per-server REGISTRATION_MAP key naming.

**Phase 1 commits per server**:

| Server | Phase 1 commit(s) | On top of |
|---|---|---|
| akosha | `4951ee8` + `0dd7176` (signature alignment) | `223101d` |
| mahavishnu | `d722d2fa` | `24e410c8` |
| session-buddy | `02235271` (H-6) + `987c3096` | `86d70f5f` |
| dhara | `2e3a65fa` + `9e81d98` (trailing newline) | `c604efe` |
| crackerjack | `e99edb6a` | `6c9eff2f` |

**Per-server E2E tests** (`tests/integration/test_list_skills_e2e.py` + `tests/integration/test_get_skill_e2e.py` per plan §5 exit criteria) deferred to Phase 2 alongside the installer E2E work — the per-server unit-level tests (38 cases per server, all green) provide the immediate Phase 1 verification.

### 10.6 Phase 3 + Phase 4 + Phase 6 Cross-Server Review — closed 2026-09-10

A read-only cross-server consistency audit ran on 2026-09-10 across
all 5 Phase 3 replicas (per-server `list_agents` / `get_agent` MCP
tools + shared `AgentMetadata` schema), the Phase 4 federation in
Akosha, and the Phase 6 ecosystem-agent-loader in dot-claude. Audit
lenses mirror §10.5:

| Lens | What it checks | Result |
|---|---|---|
| 1. `AgentMetadata` schema parity | 21-field shape (per Phase 3 task #1), B-4 allowlist on `name` + `server_key`, `..` defense, `id` shape, `extra="forbid"`, status/scope Literal | ✅ all 5 (byte-equivalent modulo docstring refs) |
| 2. `list_agents` / `get_agent` tool parity | B-1 ed25519 signing via same signer feed state, B-4 allowlist at the API boundary, B-6 body == system_prompt byte-equal, B-7 `cycles_total` bump | ✅ all 5 |
| 3. REGISTRATION_MAP + tier parity (agents) | `register_agents_tools` (or per-server variant) in REGISTRATION_MAP, tier gating, prefixed `name=` overrides, MANDATORY for agents (picker-parity at MINIMAL) | ✅ all 5 |
| 4. Phase 4 federation (`akosha_list_ecosystem_skills`) | per-server 1s timeout, asyncio.gather(return_exceptions=True), circuit breaker (3-fail-in-30s → 60s skip), file-based cache (`~/.akosha/cache/ecosystem_skills.json`), atomic `.tmp → rename`, pagination | ✅ shipped at `akosha/mcp/tools/ecosystem_skills.py` (commit `327b664`, 38/38 tests) |
| 5. Phase 3 dispatcher (H-3) | `mahavishnu_dispatch_specialist(server, task_type)` + `mahavishnu_list_specialists(server)` with category/name/description lookup precedence; MANDATORY tier; in-process 60s discovery cache; per-server URL resolution (kebab + underscore aliases) | ✅ shipped at `mahavishnu/mcp/tools/dispatch_specialist.py` (commit pending landing in main — see git log) |
| 6. Phase 6 ecosystem-agent-loader (dot-claude) | plumbable verifier (HMAC test default + Ed25519), 10-step install flow, separate `agent_installs.jsonl` audit log, `compute_content_hash` for hash-pin, list + doctor modes | ✅ shipped at `~/.claude/skills/ecosystem-agent-loader/` (commit `f242756`, 36/36 E2E tests) |

**Findings applied**:

| Severity | Server | Commit | Description |
|---|---|---|---|
| Important | akosha | `f5d2242` | Dropped `str_strip_whitespace=True` from `AgentMetadata.model_config` (Phase 3 §11 B-6 critical fix). Pydantic v2 was stripping the trailing newline from `system_prompt`, which made `metadata.content_hash` not match `sha256(metadata.system_prompt)` — the hash-pin contract Phase 6's installer depends on. |
| Important | mahavishnu | `ff8e7871` (consolidated) | same `str_strip_whitespace` removal; the agent fan-out re-committed with the fix incorporated. |
| Important | dhara | `d0d80cf` | same fix. |
| Important | crackerjack | `7ef389df` | same fix. |
| Info | session-buddy | `0ad910e9` (Phase 3) | The session-buddy Phase 3 fan-out agent caught the bug during work and delivered the fix in the initial commit (no follow-up needed). |

**Cross-cutting decisions**:

- **Phase 3 wire protocol is byte-equivalent** across all 5 servers.
  `list_agents` returns `list[AgentMetadata]`, `get_agent` returns
  `{success, metadata, body}` where `body == metadata.system_prompt`
  (B-6 critical), and `metadata.content_hash == sha256(metadata.system_prompt)`.
  Phase 4's federation aggregator and Phase 6's installer both
  consume this shape uniformly.
- **Phase 3 public helper API parity**: agents and skills share the
  same `SignerFeedState` from each server's `signer_feed` module.
  Phase 3's `get_agent` signature carries `signature` and
  `server_pubkey_id` populated AFTER signing — same contract as
  `get_skill` (Phase 1).
- **Tier gating**: all 5 servers place `register_agents_tools` (or
  per-server variant) in `*_MANDATORY_GROUPS` so the picker-parity
  story holds at MINIMAL tier.
- **File-name split is intentional**: dhara and crackerjack use
  `agent_registry.py` per plan §6; akosha, mahavishnu, session-buddy
  use `agents_tools.py`. Mirrors the Phase 1 skill file split.

**Phase 3 + Phase 4 + Phase 6 commits per server / repo**:

| Component | Phase 3 commit | Phase 4 commit | Phase 6 commit |
|---|---|---|---|
| akosha | `3354ce9` | `327b664` | n/a |
| mahavishnu | `ff8e7871` (consolidated) | n/a | n/a |
| session-buddy | `0ad910e9` | n/a | n/a |
| dhara | `f0c7332` | n/a | n/a |
| crackerjack | `f3eadda7` | n/a | n/a |
| dot-claude | n/a | n/a | `f242756` (Phase 6 installer + Skill) — preceded by `adf577a6` (Phase 2 ecosystem-skill-loader, dot-claude) |

**Per-server E2E test counts**:

| Server | Unit tests (Phase 3) | Integration tests (Phase 3) |
|---|---|---|
| akosha | 47 | 19 |
| mahavishnu | 44 | 10 |
| session-buddy | 42 | 27 |
| dhara | 45 | 17 |
| crackerjack | 44 | 16 |
| **Total** | **222** | **89** |

Phase 4 (akosha only): 13 unit + 13 cache unit + 12 integration (38 total).

Phase 6 (dot-claude): 36 E2E tests in `test_agent_installer_e2e.py`.

**Phase 5 status**: SHIPPED 2026-09-10. Two commits across two repos:

- `session-buddy` `a8bf7aa0` — `session_buddy/mcp/tools/installer_cache.py`
  substrate. Atomic write to `~/.claude/skills/.installer-cache.json`
  via `.tmp → rename`. `fcntl` lock on adjacent `.installer-cache.lock`
  (F-7). `is_stale()` helper for the P-7 poll cadence check
  (default 300s).
- `bodai-plugins` `162f562` — `bodai_plugins/scripts/validate_marketplace.py`
  + new `marketplace validate` CLI subcommand. Walks each plugin's
  `commands/skills/agents` dirs, synthesizes stub entries with
  `source_trust="marketplace-stub"` and NO `signature`, atomically
  writes the cache, and per P-10 git-commits the marketplace manifest
  when `--commit-message` is provided.

Caveats:
- Stub synthesis only handles local plugin sources (filesystem path);
  remote URL scraping is deferred to the polling coordinator.
- Polling coordinator at Session-Buddy uses `installer_cache.load_cache()`
  + `installer_cache.save_cache()` — both call into the canonical
  shared substrate (no duplicated atomic-write logic).
- Per-server E2E for `marketplace validate` deferred; the
  `installer_cache.install_cache_lock()` + `_atomic_write_json()`
  + `is_stale()` are pure functions and exercised directly by
  Session-Buddy's coordinator on the next polling cycle (default
  300s cadence).

## 11. Blockers — Consolidated Index

Per the 5-agent multi-lens review on 2026-09-09, the following
amendments are blockers (B-1 through B-7) before the plan promotes
from `needs-revision` to `active`. High/medium/low priority items
follow.

**Status update 2026-09-10**: B-1 is **fully closed across all 5
servers** (commits: akosha `09cef76` + `223101d`, mahavishnu
`24e410c8`, session-buddy `6b0bcd9b` + `86d70f5f`, dhara `c604efe`,
crackerjack `6c9eff2f`). The cross-server consistency review
(§10.4) verified the wire payload, manifest shape, and
production-lifespan wiring on all 5 replicas. B-7 is still
"partially closed per server" — the per-server E2E tests
specified in §10.3.7's contract are deferred to Phase 2, where
the installer primitives provide the test scaffolding. The
remaining blockers (B-2, B-3, B-4, B-5, B-6) are implementation
work that follows naturally from the now-unblocked Phase 1.5.

### B-1: Signing infrastructure (Phase 1.5) — **CLOSED 2026-09-10 (all 5 servers)**

ed25519 keypair per server; public-key manifest pinned in `/health`;
`get_skill` / `get_agent` responses carry `signature` +
`server_pubkey_id`. Without signing, Phase 2/6 is a generic RCE
primitive on `~/.claude/skills/` and `~/.claude/agents/`. **Source**:
MCP §3 S-3, governance §1.

**Closed in akosha commit `09cef76`** (2026-09-09); replicated to
mahavishnu `24e410c8`, session-buddy `6b0bcd9b`, dhara `c604efe`,
crackerjack `6c9eff2f` on 2026-09-10. Implemented in
`<server>/skills_signer/` (canonicalize, keys, manifest, sign,
verify, errors, `__init__`) and wired into each server's lifespan
+ `<server>/mcp/signer_feed.py`. `load_or_create_keypair`
persists the private key at `~/.{server}/state/skills_signer/private_key.pem`
(0o700 parent, 0o600 file); key_id is stable across restarts on
all 5 servers. Live verified: `/health` returns all four mandatory
feed signals (`feed_entities_count`, `feed_last_updated_timestamp`,
`cycles_total`, `errors_total`) plus `ok` computed from manifest
invariants on each replica. Cross-server consistency review
(§10.4) confirmed byte-equivalent wire payload across the 5 servers;
session-buddy's redundant-init issue (commit `86d70f5f`) and
akosha's cosmetic raise format (commit `223101d`) are the only
post-replication adjustments.

### B-2: Two-phase install confirmation

Write to `~/.claude/skills/.pending/<server>-<name>-<ts>/SKILL.md`,
render the Skill (description + body + tool-allowlist disclosure) to
the user, only rename to live path on explicit `yes`. Skill
description must lead with "Use ONLY when the user explicitly
types" to bias Claude Code's auto-trigger classifier against
prompt-injection escalation. **Source**: MCP §3 S-4, S-2.

### B-3: Append-only audit log with hash-chain

Log at `~/.claude/audit/skill_installs.jsonl` (and
`~/.claude/audit/agent_installs.jsonl` for Phase 6). Each line carries
`prev_hash` (sha256 of prior line) for tamper detection. Lives
outside the Skill loader's allowed write paths. **Source**: MCP §3
S-8, operational §3.3, §4.

### B-4: Path-traversal sanitization

Strict allowlist `^[a-z0-9][a-z0-9._-]{0,63}$` on `name` AND `server`.
Forbid `/`, `..`, leading `.`. Unit test in
`tests/unit/test_skill_metadata_schema.py` asserts rejection of
`"../../foo"`, `"foo/bar"`, `".hidden"`, `"FOO"`. **Source**: MCP §1
C-2.

### B-5: Phase 6 Integration Contract fill-in

Replace the placeholder "Same shape as Phase 2" with the full five-
field block: Triggered from, Returns to / updates, Demonstrable by,
Rollback signal, Observability added. Mirrors the Phase 2 contract
shape. **Source**: governance §1.1.

### B-6: `AgentMetadata` system_prompt body

Add `system_prompt: str` field to `AgentMetadata`. Add mandatory
`get_agent(name)` MCP tool returning `{metadata, body, content_hash}`.
Without the body, the installer would ship non-functional agents.
**Source**: agent-format §1a.

### B-7: Four mandatory feed signals + `/health` aggregation

Every new data feed (`list_skills`, `list_agents`, federation,
install feeds) MUST expose `feed.entities_count`,
`feed.last_updated_timestamp`, `feed.errors_total`,
`feed.cycles_total`. All four aggregated into `/health` per
`mcp-backend-wiring-discipline.md` §1, §3. Degraded feed causes
`/health` to return 503. **Source**: governance §2.1, §2.2.

**Partially closed 2026-09-09** — the `skills_signer` feed in
akosha's `/health` (commit `09cef76`) exposes all four signals
plus computed `ok` from manifest invariants. Replication to the
other 4 servers is pending. The per-server E2E test contract is
specified in §10.3.7 — `tests/integration/test_health_aggregator_e2e.py`
per server must assert pre-lifespan / post-lifespan / post-teardown /
empty-manifest states before B-7 is fully closed.

### High-priority amendments (must fix before specific phases ship)

- **H-1**: Federation per-server timeout (≤1s), circuit breaker
  (skip for 30s on 3 failures), `asyncio.gather(return_exceptions=True)`,
  response shape `EcosystemSkillsResponse(data, errors, per_server_latency_ms, cache, pagination)`.
- **H-3**: Specialist dispatcher — `mcp__mahavishnu__dispatch_specialist(server, task_type)`
  OR defer specialists until dispatcher exists.
- **H-5**: Move federation cache from Akosha HotStore to `~/.akosha/cache/ecosystem_skills.json` with TTL.
- **H-6**: Disambiguate Session-Buddy's existing `list_skills` — rename existing to `list_workflow_patterns`, reclaim `list_skills`.
- **H-7**: CI smoke test orchestrator spec — name the GitHub workflow, warmup window, transport, per-tool assertion.
- **H-8**: Phase 0 v2 — `_meta.fastmcp.tags=["internal", "discovery"]` for plumbing tools; `name=` overrides only for the 5–10 truly user-facing tools per server.

### Medium-priority amendments

- **M-1**: Project-vs-global default — write to `<cwd>/.claude/skills/` if writable, else `~/.claude/skills/`. Add `--global` flag.
- **M-2**: Manifest + audit log files at `~/.claude/skills/.install-manifest.json` + `~/.claude/skills/.install-log.jsonl`.
- **M-3**: Upgrade-with-merge path — hash-compare before write; if different, write to `SKILL.md.new`, surface "conflict" in picker. Add `--dry-run` flag.
- **M-4**: Pagination on `list_skills` (cursor-based, day-1).
- **M-5**: Phase 5 polling cadence default ≥5min + change-detection on `version` + lock file `~/.claude/skills/.installer-cache.lock`.
- **M-6**: Federation reconciles with installed files — also enumerates `~/.claude/skills/<server>-*/SKILL.md`.
- **M-7**: Boot-time benchmark before/after Phase 2 lands (≥2s regression triggers `.lazy` marker).
- **M-8**: Migrate 32 existing unprefixed skills to prefixed convention (or document mixed naming).
- **M-9**: `enabledPlugins` decision for bodai-plugins marketplace — enable relevant plugins or document as inert.
- **M-10**: Skill-installer has `list` and `doctor` modes.
- **M-11**: Frontmatter fields precisely specified for `ecosystem-skill-loader` (name, description, allowed-tools).
- **M-12**: `SkillMetadata` extends with `content_hash`, `tags`, `last_updated`, `source_url`, `installed_path`.

### Low-priority amendments

- **L-1**: Fix frontmatter `blocks_on` — empty or removed.
- **L-2**: Fix wording "33 nameless Crackerjack tools" → "33 Crackerjack tools with empty descriptions".
- **L-3**: Move `tests/manual/test_picker_friendly_names.sh` → `tests/integration/`.
- **L-4**: Align Phase 1 exit-criteria test path to `tests/integration/test_list_skills_e2e.py`.
- **L-5**: Add `feature-tracking/<slug>.md` per phase per wire-up-contract §3.
- **L-6**: Document that body loading is dispatch-time, not session-start.
- **L-7**: Document the exact MCP-tool contract for each server in CLAUDE.md.

---

## Appendix A — Why the prior plan was superseded

[docs/plans/2026-09-09-bodai-slash-command-tui-discoverability.md](2026-09-09-bodai-slash-command-tui-discoverability.md)
documented the original hypothesis (slash-command files in
`.claude/commands/` plus a packaged marketplace plugin). Live
`tools/list` probes on 2026-09-09 disproved that hypothesis: the
auto-exposure is uniform; the asymmetry was naming hygiene, not
plugin enablement. The successor plan captures the corrected
architecture (server-publishes / client-loads).

## Appendix B — How this aligns with CLAUDE.md Process Discipline

Per `CLAUDE.md` § Process Discipline, every phase above includes
an **Integration Contract** block (Triggered from / Returns to /
Demonstrable by / Rollback signal / Observability added). The
template requirements (`docs/plans/TEMPLATE.md`) are met by the
presence of `4.5 Requirements` with REQ IDs, integration contracts
on every phase, validation matrix, and decision rule.

Per `CLAUDE.md` § MCP backend wiring discipline: each phase adds
new tools (`list_skills`, `list_agents`, etc.) with integration
contracts asserting non-empty responses against the live MCP
servers. The wire-up is documented before each deliverable, not
after.

Per `crackerjack-compliant-code` skill: every tool implementation
will pass `crackerjack run` (ruff + mypy + bandit + pyright) on
the new code; the skill-installer atomic-write requirement
follows the project's existing `.tmp → rename` precedent.
