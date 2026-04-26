# Config Consolidation: Mahavishnu as Self-Contained Dev Environment

**Date:** 2026-04-26
**Status:** Draft
**Approach:** Native project config (Approach A)

## 1. Problem Statement

All Claude Code configuration is currently scattered across global `~/.claude/` and `~/.claude.json`, with Mahavishnu using an `additionalDirectories` workaround to access them. This creates several problems:

1. **No single source of truth** — configs live in two global locations plus Mahavishnu's local `.claude/`
2. **Not version-controlled** — global configs are invisible to git, making changes untrackable
3. **Not portable** — can't share the dev environment across machines or team members
4. **Not product-like** — Mahavishnu can't be distributed as a pre-packaged environment
5. **Not multi-tool** — only Claude Code can read the configs; Mahavishnu CLI/TUI cannot

## 2. Goals

- Move all custom agents, skills, commands, workflows, tools, hooks, and MCP server definitions into the Mahavishnu project directory
- Use Claude Code's native project-scoped config (`.claude/` + `.mcp.json`) — no symlinks, no sync
- Keep secrets and Claude app state global (they can't and shouldn't move)
- Make configs readable by both Claude Code and Mahavishnu CLI/TUI
- Version-control the canonical config in git
- Provide a migration script with dry-run and rollback

## 3. Non-Goals

- Managing plugins (stays in Claude Code's plugin system)
- Managing project memories (auto-managed by Claude Code)
- Replacing `~/.claude/settings.json` (secrets, env vars, plugin toggles stay global)
- Supporting non-Mahavishnu sessions with full config access (those sessions add Mahavishnu to `additionalDirectories` if needed)

## 4. Current State Inventory

| Config | Location | Count | Format |
|--------|----------|-------|--------|
| Agents | `~/.claude/agents/` | 101 | Markdown with YAML frontmatter |
| Skills | `~/.claude/skills/` | 22 (with SKILL.md) + 5 symlinks to `~/.agents/skills/` + docs | Markdown directories |
| Commands | `~/.claude/commands/` | 10 | Markdown |
| Workflows | `~/.claude/commands/workflows/` | 8 | Markdown |
| Tools | `~/.claude/commands/tools/` | 6 | Markdown |
| Hooks | `~/.claude/hooks/` | 4 (1 Python, 1 JSON, scripts in `~/.claude/scripts/`) | JSON + Python + Shell |
| MCP Servers | `~/.claude.json` → `mcpServers` | 33 | JSON |
| Global CLAUDE.md | `~/.claude/CLAUDE.md` | 1 (260 lines) | Markdown |
| Permissions | `~/.claude/settings.local.json` | 1 | JSON |
| Env vars + secrets | `~/.claude/settings.json` | 1 | JSON |
| Plugins | `~/.claude/plugins/` | 10 installed | Managed by Claude Code |
| Project memories | `~/.claude/projects/` | 27 dirs | Managed by Claude Code |
| App state | `~/.claude.json` (other keys) | ~60 keys | Managed by Claude Code |

## 5. Target State

### 5.1 Directory Structure

```
mahavishnu/
├── .claude/
│   ├── agents/                     # 101 agent .md files (moved from ~/.claude/agents/)
│   ├── skills/                     # 27 skill directories (moved from ~/.claude/skills/)
│   │   ├── task-orchestration-review/  # Already existed locally — preserved
│   │   ├── manage-pools/
│   │   │   └── SKILL.md
│   │   └── ...
│   ├── commands/                   # Slash commands (moved from ~/.claude/commands/)
│   │   ├── start.md
│   │   ├── end.md
│   │   ├── checkpoint.md
│   │   ├── run.md
│   │   ├── toggle-verbose.md
│   │   ├── verbose-on.md
│   │   ├── verbose-off.md
│   │   ├── verbose-status.md
│   │   ├── tools/                  # 6 tool commands
│   │   └── workflows/              # 8 workflow commands
│   ├── hooks/                      # Hook configuration (moved from ~/.claude/hooks/)
│   │   └── mcp-hooks.json
│   ├── settings.local.json         # Project-scoped permissions
│   └── CLAUDE.md                   # Ecosystem manifest (moved from ~/.claude/CLAUDE.md)
├── .mcp.json                       # 33 MCP server definitions (extracted from ~/.claude.json)
├── CLAUDE.md                       # Repo-level instructions (existing, unchanged)
├── AGENTS.md                       # Existing, unchanged
├── scripts/
│   └── migrate_config_to_project.py  # Migration script
└── ...
```

### 5.2 What Stays Global

| Item | Reason |
|------|--------|
| `~/.claude/settings.json` | Contains secrets (ANTHROPIC_AUTH_TOKEN), env vars, plugin toggles, theme |
| `~/.claude.json` | Claude Code app state (startups, tips, subscription, feature flags) |
| `~/.claude/plugins/` | Plugin cache managed by Claude Code's marketplace |
| `~/.claude/projects/` | Per-project memory directories auto-managed by Claude Code |
| `~/.claude/scripts/` | Hook shell scripts (hardcoded paths, runtime state) |

### 5.3 What Happens to `~/.claude/` After Migration

After migration, `~/.claude/` retains only:
- `settings.json` (secrets, env, plugins — unchanged)
- `settings.local.json` (existing project-scoped permissions — unchanged)
- `CLAUDE.md` — replaced with a thin stub:
  ```
  # Global Claude Code Configuration
  # Primary configuration lives in the Mahavishnu project.
  # See: /Users/les/Projects/mahavishnu/.claude/CLAUDE.md
  ```
- `plugins/` — unchanged (managed by Claude Code)
- `projects/` — unchanged (managed by Claude Code)
- `scripts/` — unchanged (hook shell scripts)
- `hooks/mcp-hooks.json` — stays in place (referenced by path in settings.json)

The `agents/`, `skills/`, and `commands/` directories become empty and can be removed.

## 6. Migration Strategy

### 6.1 Migration Script: `scripts/migrate_config_to_project.py`

A Python script with three phases:

**Phase 1: Copy files into Mahavishnu's `.claude/`**

| Source | Destination | Notes |
|--------|-------------|-------|
| `~/.claude/agents/*.md` | `mahavishnu/.claude/agents/` | Skip `.backup` files |
| `~/.claude/skills/*/SKILL.md` | `mahavishnu/.claude/skills/*/SKILL.md` | Follow symlinks (5 link to `~/.agents/skills/`), preserve existing local skills |
| `~/.claude/commands/*.md` | `mahavishnu/.claude/commands/` | Recursive (includes tools/ and workflows/) |
| `~/.claude/hooks/mcp-hooks.json` | `mahavishnu/.claude/hooks/mcp-hooks.json` | JSON config only |
| `~/.claude/CLAUDE.md` | `mahavishnu/.claude/CLAUDE.md` | Full 260-line ecosystem manifest |

**Phase 2: Extract MCP servers**

Extract the `mcpServers` key from `~/.claude.json` and write it as `mahavishnu/.mcp.json`:

```python
# Pseudocode
claude_json = load("~/.claude.json")
mcp_servers = claude_json.pop("mcpServers", {})
write("mahavishnu/.mcp.json", {"mcpServers": mcp_servers})
save("~/.claude.json", claude_json)  # Remove mcpServers from global
```

Claude Code will repopulate app-state keys in `~/.claude.json` on next launch.

**Phase 3: Update project config**

1. Remove `~/.claude` from `mahavishnu/.claude/settings.local.json` `additionalDirectories`
2. Keep `mcp-common`, `crackerjack`, `session-buddy` in `additionalDirectories`
3. Replace `~/.claude/CLAUDE.md` with thin stub
4. Delete `claude-island-state.py` (removed per user decision)

### 6.2 Safety Features

- `--dry-run` flag: prints all planned operations without executing
- `--backup` flag: creates timestamped backup of `~/.claude/CLAUDE.md` before overwriting
- `--rollback` flag: reverses the migration (copies files back to `~/.claude/`, restores `~/.claude.json`)
- Validation step: after copy, verifies all expected files exist in new locations
- Idempotent: running twice is safe (skips existing files)

### 6.3 Post-Migration Verification

```bash
# Verify agents are discoverable
ls mahavishnu/.claude/agents/ | wc -l  # Expect ~101

# Verify skills are discoverable
ls -d mahavishnu/.claude/skills/*/SKILL.md | wc -l  # Expect ~27 (22 native + 5 from ~/.agents/)

# Verify MCP servers are defined
python3 -c "import json; d=json.load(open('mahavishnu/.mcp.json')); print(len(d['mcpServers']))"  # Expect 33

# Verify CLAUDE.md exists
wc -l mahavishnu/.claude/CLAUDE.md  # Expect ~260

# Start Claude Code and verify
claude  # Should discover all agents, skills, MCP servers from project config
```

## 7. Multi-Tool Access & CLI Integration

### 7.1 Config Formats Are Tool-Agnostic

All config files use standard formats that any tool can parse:

| Config | Format | Consumable by |
|--------|--------|---------------|
| Agents | Markdown + YAML frontmatter | Claude Code, Mahavishnu CLI, any markdown parser |
| Skills | Markdown + YAML frontmatter | Claude Code, Mahavishnu CLI, any markdown parser |
| MCP Servers | `.mcp.json` (JSON) | Claude Code, Mahavishnu CLI, any JSON parser |
| Commands | Markdown | Claude Code, Mahavishnu CLI |

### 7.2 Mahavishnu CLI Commands

```bash
# Show current config inventory
mahavishnu config show

# List agents with metadata
mahavishnu config list-agents [--role <role>] [--tag <tag>]

# List skills
mahavishnu config list-skills

# List MCP servers with status
mahavishnu config list-mcp-servers

# Validate config integrity
mahavishnu config validate

# Re-import from global (if new agents/skills were added to ~/.claude/)
mahavishnu config sync-from-global
```

These commands read from the local `.claude/` and `.mcp.json` — no dependency on `~/.claude/`.

## 8. Git Strategy

### 8.1 Committed (canonical product config)

- `.claude/agents/*.md` — agent definitions (no secrets)
- `.claude/skills/*/SKILL.md` — skill definitions
- `.claude/commands/*.md` — command definitions
- `.claude/hooks/mcp-hooks.json` — hook configuration
- `.claude/CLAUDE.md` — ecosystem manifest
- `.claude/settings.local.json` — project permissions
- `.mcp.json` — MCP server definitions (localhost URLs, no secrets)
- `scripts/migrate_config_to_project.py` — migration script

### 8.2 Gitignored

- `.claude/hooks/scripts/` — shell scripts with hardcoded personal paths
- `.claude/skills/*/.archive/` — archived skill versions

### 8.3 `.mcp.json` Security

All 33 MCP servers use either `http` transport to `localhost:8xxx` or local command execution. No API keys are stored in `.mcp.json`. Secrets remain in `~/.claude/settings.json`.

## 9. Edge Cases

| Edge Case | Handling |
|-----------|----------|
| **Plugins** | Stay in `~/.claude/plugins/`. Managed by Claude Code's plugin system. `enabledPlugins` map in `~/.claude/settings.json` stays global. |
| **Project memories** | `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/` stays in place. Claude Code manages these by project path. |
| **additionalDirectories** | Remove `~/.claude` from the list. Keep `mcp-common`, `crackerjack`, `session-buddy`. |
| **Existing local skill** | `.claude/skills/task-orchestration-review/` already exists — migration skips it (no overwrite). |
| **Symlinks in skills/** | 5 symlinks in `~/.claude/skills/` point to `~/.agents/skills/`. Migration follows symlinks (copies actual content). Source `~/.agents/` directory is separate and not part of this migration. |
| **claude-island-state.py** | Removed entirely (not migrated, not gitignored). |
| **Hook scripts** | `~/.claude/scripts/` stays global (hardcoded paths). Only `mcp-hooks.json` config moves. The JSON references scripts at `~/.claude/scripts/*` by absolute path — these continue to work since the scripts don't move. |
| **Other project sessions** | Non-Mahavishnu sessions won't see these configs. They can add Mahavishnu to their `additionalDirectories` if needed. |

## 10. Acceptance Criteria

1. All 101 agents are present in `mahavishnu/.claude/agents/` and discoverable by Claude Code
2. All 27 skills (22 native + 5 from `~/.agents/` symlinks) are present in `mahavishnu/.claude/skills/` and discoverable by Claude Code
3. All 33 MCP servers are defined in `mahavishnu/.mcp.json` and connectable
4. `mahavishnu/.claude/CLAUDE.md` contains the full ecosystem manifest
5. `~/.claude/CLAUDE.md` is a thin stub pointing to Mahavishnu
6. `~/.claude.json` no longer contains `mcpServers` key
7. `~/.claude` is removed from `additionalDirectories`
8. `mahavishnu config validate` passes with no errors
9. No symlinks in the new `.claude/skills/` directory (all resolved to real content)
10. Migration script runs successfully with `--dry-run` (no changes made)
11. Migration script runs successfully without `--dry-run` (files moved)
12. `mahavishnu config rollback` successfully reverses the migration
13. A fresh Claude Code session from Mahavishnu discovers all agents, skills, and MCP servers
14. `.gitignore` correctly excludes runtime-only files while including canonical configs
15. All committed files contain no secrets (API keys, tokens)

## 11. ADR Reference

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Config location | Native project `.claude/` | Claude Code's built-in project-scoped config. No symlinks or sync needed. |
| MCP server format | `.mcp.json` | Standard Claude Code project format. Extracted from `~/.claude.json`. |
| Global stub | Thin pointer in `~/.claude/CLAUDE.md` | Non-Mahavishnu sessions get a helpful redirect. |
| Hooks | Config moves, scripts stay | JSON config is portable; shell scripts have hardcoded personal paths. |
| Plugins | Stay global | Managed by Claude Code's plugin marketplace system. |
| Secrets | Stay global in `settings.json` | Never version-controlled. Auth tokens, API keys stay in `~/.claude/`. |
| Migration | Scripted with dry-run + rollback | Safe, repeatable, verifiable. |
| Multi-tool access | Shared formats + CLI commands | Markdown + JSON are universally parseable. CLI provides management interface. |

## 12. Delivery Order

| # | Item | Dependencies |
|---|------|-------------|
| 1 | Write migration script (`scripts/migrate_config_to_project.py`) | None |
| 2 | Run migration with `--dry-run` to validate | 1 |
| 3 | Run migration (full) | 2 |
| 4 | Verify with fresh Claude Code session | 3 |
| 5 | Add `mahavishnu config` CLI commands | 3 |
| 6 | Update `.gitignore` | 3 |
| 7 | Commit and push | 4, 5, 6 |
