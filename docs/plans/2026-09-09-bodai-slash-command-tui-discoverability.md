---
status: complete
role: canonical
date: 2026-09-09
last_reviewed: 2026-09-09
superseded_by: docs/plans/.archive/2026-09-09-bodai-skill-agent-distribution.md
blocks_on: []
topic: plugin-standardization
---

> **Superseded 2026-09-09** by [bodai-skill-agent-distribution.md](.archive/2026-09-09-bodai-skill-agent-distribution.md).
> This plan documented the original "slash-command files in `.claude/commands/`"
> hypothesis, which empirical MCP probes have since disproved. The successor
> captures the corrected architecture (server-publishes / client-loads) plus
> the naming-fix for the per-server tool gap.

# Bodai Slash-Command TUI Discoverability Plan

> **Why this plan exists**: When the user types `/akosha`, `/vishnu`,
> `/dhara`, or `/session-buddy` in Claude Code's slash-command TUI picker,
> zero entries appear. When they type `/crackerjack`, five entries match.
> This asymmetry is a discoverability defect — the underlying skills and
> agents exist, but the user-facing command layer does not surface them
> uniformly. See findings in §4.

## 1. Outcome

When a user types `/akosha`, `/vishnu`, `/mahavishnu`, `/dhara`,
`/session-buddy`, `/crackerjack`, or `/bodai` in Claude Code's slash
command TUI picker, **every entry returned by that prefix query is a
working command** for the named Bodai component. Today only `/crackerjack`
behaves correctly; the other five prefixes return zero results despite the
underlying capabilities existing in `mcp__akosha__*`, `mcp__mahavishnu__*`,
`mcp__dhara__*`, and `mcp__session_buddy__*`.

**Success metric**: 100% of `/<bodai-component>` prefix searches return ≥1
working slash command, across all 5 components plus `/bodai` and the
`/vishnu` nickname alias. Verified by manual snapshot in a Claude Code TUI
session during a routine check.

## 2. Goals

1. Add `<component>-` prefix naming convention to all Bodai skills so
   every skill is discoverable via `/<component>` in the picker.
2. Ship slash command files for each of the 5 Bodai components + the
   `/vishnu` nickname alias + the `/bodai` umbrella.
3. Fill the 3 missing specialist agents (`session-buddy-specialist`,
   `dhara-specialist`, `crackerjack-specialist`) so the `Agent` tool
   picker matches parity.
4. Migrate the user-global `~/.claude/skills/bodai-*` collection into a
   versioned Bodai marketplace plugin so the surface is reproducible on
   any machine, not just the maintainer's.
5. Preserve backward compatibility for every skill/command name referenced
   in any `CLAUDE.md`, `MEMORY.md`, or `.claude/decisions/` entry.

## 3. Non-Goals

1. **Not** adding new MCP tools to any Bodai server. This plan only
   changes the user-facing UI layer; the underlying tool surface stays
   identical.
2. **Not** changing MCP server wiring in `~/.mcp.json` or `<repo>/.mcp.json`.
3. **Not** renaming the canonical `mahavishnu` skill — its name stays;
   `/vishnu` becomes a new slash-command alias, not a rename.
4. **Not** introducing a new wire protocol or new discovery mechanism —
   this stays on Claude Code's existing `.claude/commands/` + Skill
   channels.

## 4. Current Findings

### 4.1 Naming/convention asymmetry (proven via grep)

| Slash prefix | Hits in picker | Skill filenames responsible |
|---|---|---|
| `/crackerjack` | **5** | `crackerjack-cleanup-wave7`, `crackerjack-coverage-fanout{,-wave2,-wave3}`, `crackerjack-compliant-code` |
| `/mahavishnu` | 2 | `mahavishnu`, `mahavishnu-status` |
| `/vishnu` | **0** | no `vishnu-*` skill exists despite nickname usage |
| `/akosha` | **0** | all 4 Akosha skills unprefixed: `search-insights`, `code-archaeologist`, `mmx-cli`, `icon-retrieval` |
| `/dhara` | **0** | `persistent-state` (no `dhara-` prefix) |
| `/session-buddy` | 0 | `session-archaeologist` matches loose `/session`, others unprefixed |
| `/bodai` | 3 | `bodai-radar`, `bodai-status`, `bodai-worktree-cleanup` (duplicated across user-global and project-local) |

### 4.2 MCP tools never appear in the slash-command picker

Verified by reading `~/.claude/plugins/cache/mycelium/mycelium-core/1.0.0/commands/`
which packages Redis MCP tool calls inside `commands/*.md` markdown files
(e.g. `team-status.md` with `allowed-tools: Bash(redis-cli:*), Read, Glob,
mcp__RedisMCPServer__*`). There is no automatic `mcp__<server>__<tool>` ↔
`/<server>/<tool>` projection.

### 4.3 Specialist-agent gap (related defect)

`/Users/les/Projects/mahavishnu/.claude/agents/` contains:
- `akosha-specialist.md` ✓
- `mahavishnu-orchestrator.md` ✓
- `mahavishnu-specialist.md` ✓
- **missing**: `session-buddy-specialist.md`, `dhara-specialist.md`, `crackerjack-specialist.md`

### 4.4 Skill duplication across tiers

`mahavishnu`, `mahavishnu-status`, `bodai-status` exist in BOTH
`~/.claude/skills/` (user-global) AND `/Users/les/Projects/mahavishnu/.claude/skills/`
(project-local). Neither location is documented as canonical. This is
wiring-not-enforced per the `.claude/decisions/wire-up-contract.md` rule.

### 4.5 The mycelium pattern is the proven model

`~/.claude/plugins/cache/mycelium/mycelium-core/1.0.0/commands/`:
```
team-status.md        # frontmatter allowed-tools includes mcp__RedisMCPServer__*
infra-check.md        # same pattern
pipeline-status.md    # same pattern
```
Plus 60+ agents in `agents/`. This is the exact shape Bodai should ship.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Slash command files exist for 5 Bodai components"
  - id: REQ-002
    title: "Each component slash command frontmatter declares allowed-tools for the matching MCP server"
  - id: REQ-003
    title: "/vishnu alias exists and delegates to /mahavishnu"
  - id: REQ-004
    title: "All Bodai skills follow <component>-<verb>-<noun> naming"
  - id: REQ-005
    title: "session-buddy-specialist, dhara-specialist, crackerjack-specialist agents exist"
  - id: REQ-006
    title: "Bodai marketplace plugin manifest exists at ~/.claude/plugins/marketplaces/bodai/plugin.json"
  - id: REQ-007
    title: "Old skill/command names continue to resolve via redirect skill or alias"
  - id: REQ-008
    title: "Backward-compat smoke test covers every name referenced in any CLAUDE.md memory entry"
```

## 5. Implementation Phases

### Phase 1: Foundation — naming convention + alias

**Goal:** Establish the `<component>-` prefix convention and the
`/vishnu` nickname alias. Both are non-breaking (new files only).

**Tasks:**
1. Write a one-page naming convention doc to
   `/Users/les/.claude/decisions/bodai-slash-naming.md` documenting the
   `<component>-<verb>-<noun>` rule with worked examples.
2. Add `vishnu` → `mahavishnu` redirect as a thin skill at
   `~/.claude/skills/vishnu/SKILL.md` (just one paragraph, no logic).
3. Author the slash command file `~/.claude/commands/vishnu.md` so `/vishnu`
   shows in the TUI picker. Fulfils REQ-003.

**Exit criteria:**
- Grep `/Users/les/.claude/skills` for `^name: vishnu$` returns the file.
- Grep `/Users/les/.claude/commands` for `vishnu` returns the slash command.
- Manual check: type `/vishnu` in TUI picker → see one entry.

#### Integration Contract for Phase 1

- **Triggered from**: user types `/vishnu` in Claude Code TUI picker.
  Entry point: the Skill tool reads
  `~/.claude/skills/vishnu/SKILL.md` and routes to the existing
  `mahavishnu` skill.
- **Returns to / updates**: no persistent state — purely a UI redirect.
  The skill body delegates to whatever `/mahavishnu` already does.
- **Demonstrable by**: `grep -l "^name: vishnu$" ~/.claude/skills/*/SKILL.md`
  returns exactly one path; same for `~/.claude/commands/vishnu.md`.
- **Rollback signal**: any user reports `/vishnu` not appearing in the
  picker (no automated metric; manual feedback channel).
- **Observability added**: a single log line at slash-command invocation
  routed through `~/.mahavishnu/logs/mcp.log` if the underlying `mahavishnu`
  skill emits one. No new instrumentation in this phase.

### Phase 2: Component slash commands

**Goal:** Ship `.claude/commands/<component>.md` files for each of the 5
Bodai components. These wire MCP tools into the user-facing command picker
via the `allowed-tools:` frontmatter pattern demonstrated by mycelium.

**Tasks:**
1. Author `~/.claude/commands/akosha.md` with `allowed-tools:
   mcp__akosha__*` and a body that prompts the user for `query=`,
   `repo_filter=`, `limit=`, etc., then invokes
   `mcp__akosha__search_all_systems`.
2. Repeat for `mahavishnu.md`, `dhara.md`, `session-buddy.md`,
   `crackerjack.md` matching each server's primary tool.
3. Author `~/.claude/commands/bodai.md` as an umbrella that lists
   subcommands and dispatches to one of the 5 component commands.
4. Fulfils REQ-001 + REQ-002.

**Exit criteria:**
- `ls ~/.claude/commands/{akosha,mahavishnu,session-buddy,dhara,crackerjack,bodai}.md`
  returns 6 paths, all non-empty.
- Each file's frontmatter declares `allowed-tools: mcp__<server>__*`
  matching its filename. Verify with
  `grep -E '^allowed-tools: mcp__akosha' ~/.claude/commands/akosha.md`.

#### Integration Contract for Phase 2

- **Triggered from**: user types `/akosha`, `/mahavishnu`, `/session-buddy`,
  `/dhara`, `/crackerjack`, or `/bodai` in the TUI picker.
- **Returns to / updates**: invokes the underlying `mcp__<server>__<tool>`
  call; the receiving MCP server persists its own state (Akosha writes
  search hits to HotStore, Mahavishnu emits ExecutionDAGs to Dhara, etc.).
  This plan does not alter those persistence destinations.
- **Demonstrable by**: in any Claude Code session with all 5 Bodai MCP
  servers running, type `/akosha` in the picker → see one entry →
  invoke → see a structured output that lists 1+ Akosha semantic search
  hits. Same demonstration for each of the 5 components + `/bodai`.
- **Rollback signal**: a single regression test (`tests/manual/test_slash_command_picker.sh`)
  failed — exit code != 0. The script enumerates each Bodai component
  command, invokes it, and asserts the response is non-empty.
- **Observability added**: each slash command body emits a one-line log
  to `~/.mahavishnu/logs/mcp.log` with key `slash_command_invoked` and
  values `{component, command}` so the existing `bodai-radar` skill can
  surface invocation frequency per component.

### Phase 3: Skill rename + backward-compat aliases

**Goal:** Rename every Bodai skill in `~/.claude/skills/` and
`<repo>/.claude/skills/` to follow the `<component>-<verb>-<noun>`
convention. Preserve every old name as a one-line redirect skill.

**Tasks:**
1. For each skill (search-insights, code-archaeologist, mmx-cli,
   icon-retrieval, search-sessions, capture-insights, session-archaeologist,
   auto-coordinate, persistent-state, manage-pools, orchestrate-workflow,
   sweep-repositories, find-capability, learn-from-errors,
   code-knowledge-builder, smart-scaling, run-quality-checks): rename
   the directory from `~/.claude/skills/<old>/` to
   `~/.claude/skills/<component>-<old>/` and update the frontmatter.
2. For each renamed skill, create a one-line redirect skill at
   `~/.claude/skills/<old>/SKILL.md` whose body just invokes the new
   skill by name. Fulfils REQ-007.
3. Fulfils REQ-004.
4. Sweep `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md`
   and every `CLAUDE.md` (mahavishnu, akosha, session-buddy, dhara,
   crackerjack) for references to old skill names; replace with the
   new prefix-namespaced names. Fulfils REQ-008.

**Exit criteria:**
- `grep -rE "search-insights|capture-insights|manage-pools|orchestrate-workflow"`
  `~/.claude/skills/ -l` returns ONLY redirect files (each ≤10 lines).
- The same grep, when redirected over `MEMORY.md` and `CLAUDE.md`, returns
  zero hits (every reference was updated).

#### Integration Contract for Phase 3

- **Triggered from**: Claude Code's Skill auto-trigger — any reference to
  an old skill name in user prompt or in another skill body resolves
  through the redirect.
- **Returns to / updates**: the rename mutates
  `~/.claude/skills/<old>/` → `~/.claude/skills/<component>-<old>/`. The
  redirect skill files persist at the old path; they are read every
  time the old name is referenced.
- **Demonstrable by**: `pytest tests/unit/test_skill_naming.py::test_no_unprefixed_bodai_skills`
  passes — it enumerates `~/.claude/skills/` and asserts each skill
  whose description mentions a Bodai component carries the matching
  `<component>-` prefix.
- **Rollback signal**: any auto-trigger invocation log in
  `~/.mahavishnu/logs/mcp.log` whose skill name matches
  `^unprefixed_` for more than 60s straight indicates a redirect is
  silently broken — alert via the bodai-radar skill.
- **Observability added**: a `skill_resolved_via_redirect` log key on
  every old-name invocation, with the value being the new name. Frequency
  >0 per week signals dangling references in docs.

### Phase 4: Fill specialist-agent gap

**Goal:** Add the 3 missing specialist agents so the `Agent` tool picker
matches parity with what's already wired for Akosha and Mahavishnu.

**Tasks:**
1. Read
   `/Users/les/Projects/mahavishnu/.claude/agents/akosha-specialist.md`
   for the template shape.
2. Author `~/.claude/agents/session-buddy-specialist.md`,
   `dhara-specialist.md`, `crackerjack-specialist.md` matching that
   template, each scoped to one Bodai component's MCP tools.
3. Fulfils REQ-005.

**Exit criteria:**
- `ls ~/.claude/agents/{session-buddy,dhara,crackerjack}-specialist.md`
  returns 3 paths, each containing the model field and the allowed-tools
  MCP-server scope.

#### Integration Contract for Phase 4

- **Triggered from**: the `Agent` tool type picker when the user types
  `session-buddy-specialist`, `dhara-specialist`, or `crackerjack-specialist`.
- **Returns to / updates**: no persistent state from this plan — each
  agent is read-only at load. The dispatched agent may write to its
  component's own substrate.
- **Demonstrable by**:
  `grep -lE '^name: (session-buddy|dhara|crackerjack)-specialist' ~/.claude/agents/*/`
  returns 3 paths.
- **Rollback signal**: an agent dispatch that fails to match `model:` or
  has missing MCP tool scopes is automatically excluded by the Agent
  tool loader; no manual rollback needed beyond deleting the file.
- **Observability added**: the existing agent dispatch signal
  (`mahavishnu.workflow.duration`) already covers agent dispatches; no
  new observability needed.

### Phase 5: Bodai marketplace plugin (long-term packaging)

**Goal:** Move the user-global Bodai skill collection into a versioned
marketplace plugin so the surface is reproducible on any machine.

**Tasks:**
1. Create `~/.claude/plugins/marketplaces/bodai/plugin.json` with
   `{name: "bodai", version: "0.1.0", marketplace: "local"}`.
2. Move command files to `~/.claude/plugins/marketplaces/bodai/commands/`
   and skills to `~/.claude/plugins/marketplaces/bodai/skills/`.
3. Symlink or update `~/.claude/settings.json` `enabledPlugins` to add
   `bodai@local`.
4. Verify both `mahavishnu` and `/<bodai>` slash commands still resolve
   from a clean Claude Code session. Fulfils REQ-006.

**Exit criteria:**
- After a clean `claude` launch with `bodai@local` plugin enabled,
  every command from Phases 1-4 still appears and resolves.
- `cat ~/.claude/plugins/marketplaces/bodai/plugin.json` is valid JSON.

#### Integration Contract for Phase 5

- **Triggered from**: plugin loader at Claude Code startup reads
  `enabledPlugins` in `~/.claude/settings.json`.
- **Returns to / updates**: new plugin manifest at
  `~/.claude/plugins/marketplaces/bodai/plugin.json`; reorg of files
  from `~/.claude/skills/*` (user-global) into
  `~/.claude/plugins/marketplaces/bodai/skills/*`. The deletion of the
  old paths is the destructive part — must be done only after the new
  paths are validated by Claude Code's discovery.
- **Demonstrable by**:
  `cat ~/.claude/plugins/marketplaces/bodai/plugin.json | python3 -m json.tool`
  succeeds, AND a fresh Claude Code session shows the same set of
  Bodai slash commands and skills as before.
- **Rollback signal**: any missing slash command post-install is
  detectable by re-running the Phase 2 smoke test; revert by deleting
  `enabledPlugins.bodai@local`.
- **Observability added**: the plugin loader emits a `plugin_loaded`
  log; if not present in `~/.mahavishnu/logs/mcp.log` within 5s of
  startup, the plugin failed to load.

## 6. Required Code Changes

```
~/.claude/commands/
├── vishnu.md                # NEW — Phase 1
├── akosha.md                # NEW — Phase 2
├── mahavishnu.md            # NEW — Phase 2
├── session-buddy.md         # NEW — Phase 2
├── dhara.md                 # NEW — Phase 2
├── crackerjack.md           # NEW — Phase 2
└── bodai.md                 # NEW — Phase 2 (umbrella)

~/.claude/skills/
├── vishnu/SKILL.md          # NEW — Phase 1 (redirect)
├── akosha-search-insights/SKILL.md          # NEW — Phase 3 (renamed from search-insights)
├── akosha-code-archaeologist/SKILL.md       # NEW — Phase 3
├── akosha-mmx-cli/SKILL.md                  # NEW — Phase 3
├── akosha-icon-retrieval/SKILL.md           # NEW — Phase 3
├── session-buddy-search-sessions/SKILL.md  # NEW — Phase 3
├── session-buddy-capture-insights/SKILL.md  # NEW — Phase 3
├── session-buddy-session-archaeologist/SKILL.md  # NEW — Phase 3
├── session-buddy-auto-coordinate/SKILL.md  # NEW — Phase 3
├── dhara-persistent-state/SKILL.md          # NEW — Phase 3 (renamed)
├── mahavishnu-manage-pools/SKILL.md         # NEW — Phase 3
├── mahavishnu-orchestrate-workflow/SKILL.md # NEW — Phase 3
├── mahavishnu-sweep-repositories/SKILL.md   # NEW — Phase 3
├── mahavishnu-find-capability/SKILL.md      # NEW — Phase 3
├── mahavishnu-learn-from-errors/SKILL.md    # NEW — Phase 3
├── crackerjack-run-quality-checks/SKILL.md  # NEW — Phase 3
├── search-insights/SKILL.md                # NEW redirect — Phase 3
├── (existing files preserved)               # old names persist as redirects

~/.claude/agents/
├── session-buddy-specialist.md             # NEW — Phase 4
├── dhara-specialist.md                     # NEW — Phase 4
└── crackerjack-specialist.md                # NEW — Phase 4

~/.claude/plugins/marketplaces/bodai/
├── plugin.json                             # NEW — Phase 5
├── commands/                               # moved from ~/.claude/commands/
└── skills/                                 # moved from ~/.claude/skills/

~/.claude/decisions/bodai-slash-naming.md    # NEW — Phase 1

tests/unit/test_skill_naming.py             # NEW — Phase 3
tests/manual/test_slash_command_picker.sh   # NEW — Phase 2
```

## 7. Validation Matrix

| Check | Expected outcome | Evidence location |
|---|---|---|
| `grep -l "^name: vishnu$" ~/.claude/skills/*/SKILL.md` | exactly 1 path | Phase 1 exit criteria |
| `ls ~/.claude/commands/{akosha,mahavishnu,session-buddy,dhara,crackerjack,bodai}.md \| wc -l` | 6 | Phase 2 exit criteria |
| `grep -E '^allowed-tools:.*mcp__akosha' ~/.claude/commands/akosha.md` | matches | Phase 2 exit criteria |
| `grep -rE "search-insights" ~/.claude/skills/ -l` | only redirect files (≤10 lines each) | Phase 3 exit criteria |
| `grep -rE "search-insights\|capture-insights\|manage-pools" ~/.claude/projects/*/memory/MEMORY.md ~/.claude/CLAUDE.md` | 0 hits after Phase 3 sweep | Phase 3 exit criteria |
| `ls ~/.claude/agents/{session-buddy,dhara,crackerjack}-specialist.md` | 3 paths | Phase 4 exit criteria |
| `cat ~/.claude/plugins/marketplaces/bodai/plugin.json \| python3 -m json.tool` | succeeds, valid JSON | Phase 5 exit criteria |
| Manual TUI picker test: type `/akosha` then `/vishnu` then `/bodai` | Each shows ≥1 working entry | Continuous via manual session start |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Renaming skills breaks CLAUDE.md memory entries | High | Phase 3 includes a sweep across all CLAUDE.md + MEMORY.md before deleting old names; the redirect files provide a safety net for any reference we miss. |
| Slash commands silently fail when target MCP server is unreachable | Medium | Each command's body checks the MCP server's liveness via `health_check` before invoking; surfaces a clear "unreachable" message instead of an empty result. |
| Marketplace plugin breaks the existing user-global skills | Medium | Phase 5 only deletes the old paths after the new paths have been validated by a clean launch. If validation fails, the deletion is reverted via git. |
| Agent picker picks up specialist agents that were not intended for invocation | Low | Specialist agents stay in `~/.claude/agents/` (user-global), not the project-local dir, so they don't pollute `<repo>/.claude/agents/` picks. |
| User types `/vishnu` expecting a result, gets a redirect, complains | Low | The redirect skill's body immediately delegates and includes a one-line explanation in the output: "Routed to /mahavishnu." |

## 9. Decision Rule

Plan is "done enough" when **all 6 /<bodai-component> prefixes return
working entries in the TUI picker AND every old name in any CLAUDE.md
memory resolves through the redirect file**. Phases 1-3 are required for
shipping; Phase 4 is required for parity; Phase 5 is the long-term
packaging and may be deferred without blocking the user-visible outcome.

The user-visible win is Phase 1 + Phase 2 + Phase 3. Phase 4 closes a
related defect on a different surface. Phase 5 is housekeeping.
