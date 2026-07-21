---
status: draft
role: canonical
topic: plugin-standardization
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Bodai Plugin Standardization — Design Spec

**Date:** 2026-07-16
**Status:** Draft (pending user review)
**Author:** Brainstorming session (Claude + Les)

## Context

The Bodai ecosystem ships five MCP servers — `mahavishnu`, `akosha`, `crackerjack`, `dhara`, `session-buddy` — plus several third-party utility MCPs in `~/.mcp.json`. Today:

- **None of the five Bodai MCP repos ship as Claude Code plugins.** Crackerjack has a `crackerjack/slash_commands/` directory of Markdown files (not a plugin manifest); the other four have neither.
- **Slash commands are inconsistently named.** Mahavishnu exposes unprefixed `/vishnu-status` and `/bodai-status`; crackerjack's would be `/crackerjack:status` if the slash_commands directory were ever picked up; session-buddy's commands live in mahavishnu's `.claude/commands/` and call `mcp__session-buddy__*` tools but have no `session-buddy:` prefix.
- **Nine wave `.js` workflow scripts** sit at `mahavishnu/.claude/workflows/` with no lifecycle policy. They are auto-registered as slash commands and remain runnable indefinitely even after their referenced state is gone.
- **`.claude/decisions/` has a documented lifecycle** (Active / Superseded / Archived tracked in the README index), but `.claude/workflows/` does not. `docs/followups/` is being migrated to match `.claude/decisions/`.
  The user's stated goals:

1. All five Bodai MCP servers ship as Claude Code plugins for consistency and (eventual) cross-harness distribution.
1. Slash commands are namespaced: `/mahavishnu:status`, `/akosha:search`, `/dhara:adapter-list`, `/session-buddy:checkpoint`, `/crackerjack:status`. Exception: cross-component commands keep the `bodai:` namespace.
1. Workflows follow the same lifecycle as `.claude/decisions/`.
1. Hard cutover: no aliases, no dual registration.

## Approach (chosen)

**Five self-contained plugins + a dedicated `bodai-plugins` marketplace + a scaffold-first rollout.**

- Each plugin lives in its own repo at `<repo>/.claude-plugin/plugin.json` and self-declares its MCP server in `<repo>/.mcp.json`.
- A new `bodai-plugins` repo holds only a thin marketplace manifest (`.claude-plugin/marketplace.json`) indexing the five plugin repos by git URL. No Python runtime here except for the scaffold CLI.
- A scaffold tool — `bodai-plugins` Typer CLI wrapping `scripts/init_bodai_plugin.py` — generates the canonical plugin layout in any target directory. The same tool's `validate` subcommand enforces schema and consistency.
- Pilot migration on `mahavishnu` first, then the other four in priority order.
- Wave workflows move to `.claude/workflows/.archive/` (Superseded) or stay in `.claude/workflows/` (Active), with paired `.claude/decisions/workflows/YYYY-MM-DD-<name>.md` lifecycle files.
  This approach encodes consistency in code (the scaffold), avoids the Anthropic review gate (self-hosted marketplace), and survives future plugin additions (fastblocks, splashstand, etc. drop in trivially).

## Repository Layout

### Per-plugin-repo layout (each of the five MCP repos)

```
<repo>/
├── .claude-plugin/
│   └── plugin.json                       # plugin manifest (schema below)
├── commands/                              # flat directory of slash-command .md files
│   ├── <name>.md                          # → /<server>:<name>
│   └── <name>.md
├── agents/                                # optional
├── skills/                                # optional
├── hooks/                                 # optional
├── .mcp.json                              # plugin-scoped MCP server declaration
└── pyproject.toml                         # unchanged
```

### `bodai-plugins` (new repo) layout

```
bodai-plugins/
├── .claude-plugin/
│   └── marketplace.json                   # indexes the five plugin repos
├── bodai_plugins/                         # Python package for the scaffold CLI
│   ├── __init__.py
│   ├── cli.py                             # Typer app
│   └── scripts/
│       ├── __init__.py
│       └── init_bodai_plugin.py          # init_plugin() + validate_plugin() functions
├── tests/
│   ├── test_init_bodai_plugin.py
│   └── test_marketplace_schema.py
├── pyproject.toml                         # [project.scripts] bodai-plugins = "bodai_plugins.cli:app"
├── README.md
└── CHANGELOG.md
```

### Workflow layout (per-repo)

```
.claude/
├── workflows/                              # active wave scripts (.js) — appear in slash menu
├── workflows/.archive/                    # superseded wave scripts (.js) — on disk but not registered
└── decisions/
    ├── README.md                          # existing index with Status column
    ├── <existing-decision>.md             # existing files unchanged
    └── workflows/                         # NEW: paired lifecycle file per workflow
        ├── YYYY-MM-DD-<workflow-name>.md
        └── YYYY-MM-DD-<workflow-name>.md
```

Wave `.js` naming post-archive: only `.claude/workflows/*.js` files (not `.archive/*.js`) appear in the Claude Code slash menu. The lifecycle `.md` is the canonical record of why a wave was archived.

## Plugin Manifest Schema

`<repo>/.claude-plugin/plugin.json`:

```json
{
  "name": "mahavishnu",
  "version": "0.9.0",
  "description": "Mahavishnu — The Orchestrator. Multi-engine workflow orchestration and pool management.",
  "author": {
    "name": "Les Leslie",
    "email": "les@wedgwoodwebworks.com"
  },
  "homepage": "https://github.com/lesleslie/mahavishnu",
  "repository": "https://github.com/lesleslie/mahavishnu",
  "license": "BSD-3-CLAUSE",
  "keywords": ["bodai", "orchestration", "mcp", "pool"],
  "commands": "./commands/",
  "agents": "./agents/",
  "skills": "./skills/",
  "hooks": "./hooks/",
  "mcpServers": "./.mcp.json"
}
```

Field semantics:
| Field | Source of truth | Bump policy |
|---|---|---|
| `name` | matches MCP server name in `.mcp.json` | never changes |
| `version` | tracks the repo's git tag | bumps with every release |
| `description` | mirrors the repo README lead paragraph | bumps when role changes |
| `commands`/`agents`/`skills`/`hooks` | path relative to plugin root | optional; omit if absent |
| `mcpServers` | path to the plugin's own `.mcp.json` | required |
Plugin `.mcp.json` follows the standard MCP config schema:

```json
{
  "mcpServers": {
    "mahavishnu": {
      "type": "http",
      "url": "http://localhost:8680/mcp"
    }
  }
}
```

The MCP server key (`"mahavishnu"`) **must** match `plugin.name` and the slash-command namespace prefix. A CI guard (`validate` subcommand) enforces this.

## Marketplace Manifest Schema

`bodai-plugins/.claude-plugin/marketplace.json`:

```json
{
  "name": "bodai-plugins",
  "owner": {
    "name": "Les Leslie",
    "email": "les@wedgwoodwebworks.com"
  },
  "metadata": {
    "description": "Bodai ecosystem plugin marketplace — indexes the five core Bodai MCP plugins.",
    "version": "1.0.0",
    "homepage": "https://github.com/lesleslie/bodai-plugins"
  },
  "plugins": [
    {
      "name": "mahavishnu",
      "source": {
        "source": "github",
        "repo": "lesleslie/mahavishnu",
        "ref": "main"
      },
      "description": "Mahavishnu — The Orchestrator.",
      "version": "0.9.0",
      "keywords": ["bodai", "orchestration", "mcp", "pool"]
    }
    // akosha, crackerjack, dhara, session-buddy — same shape
  ]
}
```

Validation rules enforced by `tests/test_marketplace_schema.py`:

1. Every `plugin.name` is unique within `plugins[]`.
1. Every `plugin.name` matches `[a-z][a-z0-9-]*`.
1. Every `plugin.source.repo` is reachable via `gh repo view <repo>` (skipped if `gh` unavailable; CI-required).
1. `metadata.version` is semver.
1. `plugins[]` is non-empty.

## Scaffold Script Behavior

Lives at `bodai-plugins/bodai_plugins/scripts/init_bodai_plugin.py`, exposed via `bodai_plugins/cli.py` Typer app as the `bodai-plugins` command:

```
bodai-plugins init    <name> [options]    # generate plugin layout
bodai-plugins validate <path-to-plugin>   # check existing plugin
```

### `init <name>`

**Arguments:**
| Flag | Default | Purpose |
|---|---|---|
| `name` (positional) | required | Plugin name, e.g. `mahavishnu` |
| `--repo-url` | (prompts) | GitHub repo URL, used in `plugin.json` |
| `--description` | (prompts) | One-line description |
| `--target-dir` | `.` | Directory to write the plugin files into |
| `--port` | (prompts) | MCP server port |
| `--mcp-transport` | `http` | `http` or `stdio` |
| `--mcp-command` | (transport-specific) | For stdio |
| `--mcp-url` | (transport-specific) | For http |
| `--author-name` | `git config user.name` | Plugin author |
| `--author-email` | `git config user.email` | Plugin author email |
| `--license` | `BSD-3-CLAUSE` | SPDX license identifier |
| `--force` | `False` | Overwrite existing `.claude-plugin/` if present |
**Pre-flight checks (refuses to run if any fail):**

1. `name` matches `[a-z][a-z0-9-]*`.
1. `<target-dir>/.claude-plugin/plugin.json` does not already exist (unless `--force`).
1. `<name>` is not already in `bodai-plugins/.claude-plugin/marketplace.json` (warns, proceeds).
1. MCP server config is plausible (port is int in 1–65535, or command exists on PATH).
   **What it generates:** the per-plugin-repo layout (see above) populated from the flags.
   **Post-flight actions:** runs `validate <target-dir>` and prints next steps.

### `validate <path>`

Runs all of:

1. `.claude-plugin/plugin.json` is valid JSON, has all required fields.
1. `plugin.name` matches the MCP server key in `.mcp.json`.
1. `plugin.name` matches `[a-z][a-z0-9-]*`.
1. `plugin.version` is semver.
1. Each `commands/*.md` file has valid frontmatter (`name`, `description`, both non-empty).
1. `commands/`, `agents/`, `skills/`, `hooks/` paths declared in the manifest exist as directories (or are absent if not declared).
1. `.mcp.json` is valid and has at least one server.
   Exit codes: `0` on success, `1` on any failure. All failures printed to stderr with `file:line` references. A `--verbose` flag shows every check (passed + failed). A `--json` flag outputs a JSON report.

### `validate --fix`

Auto-corrects simple cases; refuses to touch anything unsafe:
| Auto-fixable | Action |
|---|---|
| Missing `---` frontmatter in `commands/*.md` | Add a frontmatter block with placeholder `name` (filename) and `description` (empty, requires manual edit) |
| Missing `name` or `description` in frontmatter | Add placeholder, mark as `// TODO: edit` |
| Orphan path declared in `plugin.json` but directory missing | Create empty directory with a `README.md` explaining its purpose |
| `plugin.name` ≠ MCP server key | Sync `.mcp.json` server key to match `plugin.name` (one-way; never renames the plugin) |
| NOT auto-fixable | Why |
|---|---|
| Invalid name format (e.g., uppercase) | Renaming could break callers; require manual |
| Invalid semver | Could silently change meaning |
| Malformed JSON | Can't safely repair |
| Name collisions with existing marketplace entry | Cross-repo decision |
| Missing required fields beyond name/description | Require deliberate values |
`--fix` prints each fix it applied and exits `0` after running. Run `validate` again after `--fix` to confirm clean state.

## Naming Conventions

| Surface | Convention | Example |
|---|---|---|
| Plugin manifest `name` | full server name, kebab-case, lowercase | `mahavishnu`, `session-buddy` |
| Slash command namespace | matches plugin `name` | `/mahavishnu:status` |
| Slash command verb | lowercase, hyphenated | `pool-route`, `workflow-list` |
| Workflow name | `<descriptive-name>-wave<N>` or `<descriptive-name>-<YYYY-MM-DD>` | `crackerjack-coverage-fanout-wave4` |
| Workflow decision file | `YYYY-MM-DD-<workflow-name>.md` | `2026-07-16-crackerjack-coverage-fanout-wave4.md` |
| Marketplace name | `bodai-plugins` | — |
Exception: cross-component commands keep the `bodai:` namespace (`/bodai:status`).

## Workflow Lifecycle

Each wave `.js` file gets a paired `.md` decision file under `.claude/decisions/workflows/`. The decision file is the canonical lifecycle record; the `.js` is the executable artifact.
**Decision file schema:**

```markdown
---

## Workflow: <workflow-name>
## Created: YYYY-MM-DD
## Status: Active | Superseded | Archived
## Source: .claude/workflows/<workflow-name>.js

### Purpose
<one-paragraph summary>

### Phases
<list of phases from the .js meta block>

### Outcome
<what was achieved, or "in progress" if Active>

### Supersedes
<optional link to the .md of the wave this one replaces>

### Superseded by
<optional link to the .md of the wave that replaces this one>
```

**Status semantics:**

| Status | `.js` location | Slash menu | When to use |
|---|---|---|---|
| `Active` | `.claude/workflows/` | yes | Work is ongoing; re-runs expected |
| `Superseded` | `.claude/workflows/.archive/` | no | A newer wave replaces this one |
| `Archived` | `.claude/workflows/.archive/` | no | Work is done and merged; kept for audit trail only |

`.claude/decisions/README.md` gets a new section `## Workflows` listing every decision file with its Status. CI guard lives at `mahavishnu/scripts/audit_workflow_lifecycle.py` (since mahavishnu currently owns all wave workflows; if other plugin repos later gain waves, they each get their own audit script), run from `mahavishnu/.github/workflows/audit-workflows.yml`. It checks:

1. Every `.claude/workflows/*.js` (excluding `.archive/`) has a paired `.md` in `.claude/decisions/workflows/` with `Status: Active`.
1. Every `.claude/workflows/.archive/*.js` has a paired `.md` with `Status: Superseded` or `Archived`.
1. The decisions README's `## Workflows` table is in sync with the actual files.

## Migration Plan

### Phase 1: Build `bodai-plugins` skeleton

| Step | What | Deliverable |
|---|---|---|
| 1.1 | Create new GitHub repo `lesleslie/bodai-plugins` | empty repo |
| 1.2 | Write `pyproject.toml` with `[project.scripts] bodai-plugins = "bodai_plugins.cli:app"` | CLI entry point |
| 1.3 | Write `bodai_plugins/cli.py` (Typer app) wrapping `scripts/init_bodai_plugin.py` | Typer CLI |
| 1.4 | Write `scripts/init_bodai_plugin.py` with `init_plugin()`, `validate_plugin()`, `--fix` support | scaffold |
| 1.5 | Write `.claude-plugin/marketplace.json` with empty `plugins: []` | marketplace skeleton |
| 1.6 | Write `tests/test_init_bodai_plugin.py` (covers init + validate + --fix) | tests |
| 1.7 | Write `tests/test_marketplace_schema.py` | tests |
| 1.8 | Write `README.md` with install instructions | docs |

### Phase 2: Pilot migrate `mahavishnu`

| Step | What | Deliverable |
|---|---|---|
| 2.1 | `bodai-plugins init mahavishnu --repo-url https://github.com/lesleslie/mahavishnu --port 8680 --mcp-transport http --mcp-url http://localhost:8680/mcp --target-dir /Users/les/Projects/mahavishnu` | scaffold into mahavishnu |
| 2.2 | Move each existing `.claude/commands/*.md` to `commands/<same-name>.md`; normalize frontmatter delimiter to `---` and ensure `name` + `description` are non-empty | commands moved |
| 2.3 | Copy the MCP server entry from user-level `~/.mcp.json` into `mahavishnu/.mcp.json` | plugin-scoped MCP |
| 2.4 | Update `mahavishnu/CLAUDE.md` and `mahavishnu/README.md` to document `/mahavishnu:*` commands | docs |
| 2.5 | Add `mahavishnu` to `bodai-plugins/.claude-plugin/marketplace.json` (separate PR) | marketplace entry |
| 2.6 | Run `bodai-plugins validate /Users/les/Projects/mahavishnu` (must pass) | validation |
| 2.7 | **Phase A commit** (additive): add `.claude-plugin/`, `commands/`, `.mcp.json`; old `.claude/commands/*.md` still present | commit |
| 2.8 | **Phase B commit** (destructive): delete the old `.claude/commands/*.md` files | commit |

### Phase 3: Migrate the remaining four

Repeat Phase 2 steps 2.1–2.8 for each, in priority order: `session-buddy`, `crackerjack`, `akosha`, `dhara`.

### Phase 4: Workflow lifecycle migration

| Step | What | Deliverable |
|---|---|---|
| 4.1 | Inventory existing `.claude/workflows/*.js` (9 files) | inventory |
| 4.2 | For each wave `.js`, write a paired `.claude/decisions/workflows/YYYY-MM-DD-<name>.md` with status, what-it-does, outcome | decision files |
| 4.3 | Move executed waves (`crackerjack-coverage-fanout*.js`, `crackerjack-cleanup-wave7.js`) to `.claude/workflows/.archive/` with `Status: Superseded` | archived |
| 4.4 | Evaluate `mahavishnu-coverage-fanout-wave-2026-06-12*.js` case-by-case before deciding Active vs. archived | per-file decision |
| 4.5 | Add `## Workflows` section to `.claude/decisions/README.md` with status table | index updated |
| 4.6 | Write `scripts/audit_workflow_lifecycle.py` and the CI workflow that runs it | audit + CI |

### Phase 5: Publish + announce

| Step | What | Deliverable |
|---|---|---|
| 5.1 | Tag `bodai-plugins` v1.0.0 | release |
| 5.2 | Update `bodai/README.md` to mention the marketplace | docs |
| 5.3 | One announcement: install via `claude plugin marketplace add lesleslie/bodai-plugins`, then `claude plugin install <name>` | announcement |

## Testing Strategy

### Layer 1: Scaffold unit tests (`tests/test_init_bodai_plugin.py`)

| Test | Asserts |
|---|---|
| `test_init_creates_canonical_layout` | After `init_plugin`, the 5 directories + `plugin.json` + `.mcp.json` + `README.md` exist with the right content |
| `test_init_refuses_invalid_name` | Names like `Mahavishnu`, `mahavishnu_v2`, `123-mahavishnu` are rejected |
| `test_init_refuses_to_overwrite` | Running `init` in a directory with existing `.claude-plugin/` aborts unless `--force` |
| `test_init_warns_on_marketplace_collision` | Existing name in `marketplace.json` prints a warning but proceeds |
| `test_validate_catches_missing_plugin_name` | Reports `plugin.json: missing required field 'name'` |
| `test_validate_catches_name_mismatch` | Reports mismatch between `plugin.name` and MCP server key |
| `test_validate_catches_invalid_semver` | Reports semver violation |
| `test_validate_catches_missing_frontmatter` | Reports `commands/foo.md: missing frontmatter` |
| `test_validate_catches_orphan_paths` | Reports directory declared in `plugin.json` but missing on disk |
| `test_fix_adds_missing_frontmatter` | `validate --fix` adds `---` block with placeholder values |
| `test_fix_creates_orphan_directories` | `validate --fix` creates missing directories with `README.md` |
| `test_fix_does_not_rename_plugin` | `validate --fix` refuses to rename; only syncs MCP key to plugin name |
| `test_validate_json_output` | `--json` flag emits a JSON report consumable by CI |

### Layer 2: Marketplace schema tests (`tests/test_marketplace_schema.py`)

| Test | Asserts |
|---|---|
| `test_marketplace_is_valid_json` | parses |
| `test_plugin_names_unique` | no duplicates |
| `test_plugin_names_match_pattern` | `[a-z][a-z0-9-]*` |
| `test_plugin_metadata_version_semver` | semver |
| `test_plugins_array_non_empty` | at least one entry |
| `test_plugin_sources_resolvable` | `gh repo view` succeeds (skipped if `gh` unavailable; CI-required) |

### Layer 3: CI guards in each plugin repo (maintainers create their own `.github/workflows/plugin-validate.yml`)

```yaml
name: Plugin Validate
on: [pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install bodai-plugins
      - run: bodai-plugins validate .
```

Failure blocks merge.

### Layer 4: Manual smoke test (documented in `bodai-plugins/README.md`, not automated)

```bash
claude plugin marketplace add lesleslie/bodai-plugins
claude plugin install mahavishnu
# in a fresh Claude Code session:
> /mahavishnu:status
# expected: same output as the old /vishnu-status
```

## Error Handling Matrix

| Failure | User-visible behavior | Exit code |
|---|---|---|
| `init` called with bad name | `Error: name 'Mahavishnu' must match [a-z][a-z0-9-]*` | 1 |
| `init` over existing layout | `Error: .claude-plugin/plugin.json already exists. Use --force to overwrite.` | 1 |
| `init` with invalid MCP transport | `Error: --mcp-transport must be 'http' or 'stdio'` | 1 |
| `validate` with malformed JSON | `Error: .claude-plugin/plugin.json: invalid JSON (line 12)` | 1 |
| `validate` missing field | `Error: .claude-plugin/plugin.json: missing required field 'version'` | 1 |
| `validate` name mismatch | `Error: plugin name 'vishnu' does not match MCP server key 'mahavishnu'` | 1 |
| `validate` orphan path | `Error: plugin.json declares 'agents: ./agents/' but ./agents does not exist` | 1 |
| `validate --fix` applies 3 fixes | prints `Applied 3 fixes: ...` and exits 0 | 0 |

## Integration Contract

| Field | Value |
|---|---|
| **Triggered from** | User runs `claude plugin marketplace add lesleslie/bodai-plugins`, then `claude plugin install <name>` |
| **Returns to / updates** | Slash menu gains `<server>:<command>` entries; MCP tools get registered |
| **Demonstrable by** | After installing `mahavishnu`, running `/mahavishnu:status` in a fresh Claude Code session shows the same output as the old `/vishnu-status` did |
| **Rollback signal** | `claude plugin marketplace remove lesleslie/bodai-plugins` reverts; or per-plugin `claude plugin uninstall <name>` |
| **Observability added** | `bodai-plugins` CI badge (`tests/test_marketplace_schema.py`) is the public observability surface; each plugin repo's `plugin-validate.yml` CI badge is per-plugin observability |

## Rollback Plan

The hard cutover is committed in two phases per plugin:

- **Phase A commit** (additive, safe): add `.claude-plugin/plugin.json`, move `.claude/commands/*.md` to `commands/*.md`, add `.mcp.json`. Old commands still work because `.claude/commands/` still exists.
- **Phase B commit** (destructive, the cutover): delete `.claude/commands/*.md`.

Reverting Phase B restores the old commands without touching the plugin scaffold. Reverting Phase A unwinds the move.

For `bodai-plugins` itself: rollback is `git revert` of the offending PR.

For workflow migration: each wave moves in its own commit; per-wave revert is straightforward.

## Open Questions

None. All clarifying questions resolved during brainstorming.
