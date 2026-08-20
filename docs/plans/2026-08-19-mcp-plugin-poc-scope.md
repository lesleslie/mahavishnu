# 2-Repo Plugin POC Scope: graphics-mcp + css-mcp

**Status:** Draft for review
**Date:** 2026-08-19
**Author:** mahavishnu session
**Goal:** Validate the bodai plugin conversion pattern by converting two `-mcp` repos (graphics-mcp, css-mcp) into bodai-style plugins. Establish the repeatable pattern for the rest of the `-mcp` fleet.

---

## 1. Background

The Bodai ecosystem has 5 core components packaged as Claude Code plugins (mahavishnu, crackerjack, akosha, dhara, session-buddy). Each is declared in `bodai-plugins/.claude-plugin/marketplace.json` and ships a `.claude-plugin/plugin.json` + colocated `.mcp.json` + 1-3 slash commands.

The 15 standalone `-mcp` repos (graphics-mcp, css-mcp, neo4j-mcp, raindropio-mcp, etc.) are currently loaded via raw `.mcp.json` entries in either `/Users/les/Projects/mahavishnu/.mcp.json` (project-local) or `/Users/les/.claude/mcp.json` (global). They have no plugin manifests, no marketplace registration, no slash commands.

This POC converts two of the highest-value candidates to the plugin shape, mirroring the bodai core pattern. If the conversion is clean and the plugin install works, the same pattern applies to the remaining 13 repos.

## 2. Canonical pattern (from bodai-plugins scaffolding + crackerjack reference)

Each plugin lives in its own repo. Required files:

```
<repo>/
├── .claude-plugin/
│   └── plugin.json          # Manifest
├── .mcp.json                 # Server registration (repo root)
├── commands/
│   └── <plugin-name>-<verb>.md    # 1-3 slash commands
└── README.md                # Existing; add marketplace-install section
```

**Manifest required keys:** `schema_version`, `name`, `version`, `mcpServers` (string path to `.mcp.json`).

**`.mcp.json` shape:** bare-map (NOT wrapped in `mcpServers`):
```json
{
  "<plugin-name>": {
    "type": "http",
    "url": "http://localhost:<port>/mcp"
  }
}
```

**Slash command frontmatter:** real YAML between `---` delimiters, with `description`, `argument-hint`, `allowed-tools` (must include `mcp__<server>__<tool>` for each tool the command invokes).

**Marketplace entry:** add to `bodai-plugins/.claude-plugin/marketplace.json`:
```json
{"name": "<plugin-name>", "source": "../<plugin-name>", "ref": "main"}
```

## 3. Crackerjack's broken patterns to avoid

Crackerjack is the canonical bodai plugin but has known defects. We mirror the structure but fix these:

1. **Broken frontmatter** — mdformat destroyed the `---` YAML markers into underscores. All three slash commands are missing `description`, `argument-hint`, `allowed-tools`. **Fix:** write valid YAML frontmatter and add `commands/*.md` to `[tool.mdformat]` exclude list.
2. **Bare tool names in prose** — crackerjack-run.md says "uses the `get_comprehensive_status` MCP tool" with no `mcp__crackerjack__` prefix. **Fix:** use fully-qualified `mcp__<server>__<tool>` names and declare them in `allowed-tools`.
3. **Hardcoded localhost URL** — `.mcp.json` hardcodes `http://localhost:8676/mcp`. **Fix:** keep the same shape (no env templating needed for local-only servers) but document the port in the plugin README.

## 4. Out of scope (explicitly)

- Removing the existing `.mcp.json` entries from `mahavishnu/.mcp.json` and `~/.claude/mcp.json`. This is the dual-registration transition state; clearing it is a separate cleanup once all repos are converted.
- Converting the remaining 13 `-mcp` repos (separate plan, dependent on POC outcome).
- Adding agents/, skills/, hooks/ to the plugin. Crackerjack ships none; we follow that minimalist pattern.
- Documenting the plugin install workflow in crackerjack's README (crackerjack has zero marketplace install docs — we add them for graphics-mcp and css-mcp).

## 5. Per-repo changes

### 5.1 graphics-mcp

**Repo:** `/Users/les/Projects/graphics-mcp/`
**Version:** 0.2.2 (current)
**Port:** 3040 (HTTP)
**MCP server key (proposed):** `graphics`

**New files:**

1. `.claude-plugin/plugin.json`
   ```json
   {
     "author": {"name": "Bodai"},
     "description": "Bodai plugin for the graphics-mcp image processing server.",
     "keywords": ["bodai", "mcp", "graphics", "image-processing"],
     "mcpServers": "./.mcp.json",
     "name": "graphics",
     "schema_version": "1.0.0",
     "version": "0.1.0"
   }
   ```

2. `.mcp.json` (repo root)
   ```json
   {
     "graphics": {
       "type": "http",
       "url": "http://localhost:3040/mcp"
     }
   }
   ```

3. `commands/graphics-convert.md` — wraps `mcp__graphics__convert_image`
4. `commands/graphics-resize.md` — wraps `mcp__graphics__resize_image`
5. `commands/graphics-thumbnail.md` — wraps `mcp__graphics__create_thumbnail`

**Modified files:**
- `README.md` — add `## Installation via Bodai Marketplace` section.

**Slash command frontmatter example (`graphics-convert.md`):**
```markdown
---
description: Convert an image to JPEG/PNG/GIF/BMP/WEBP/TIFF with optional quality and optimization.
argument-hint: <image-path> <target-format> [--quality N] [--optimize]
allowed-tools: mcp__graphics__convert_image, mcp__graphics__list_supported_formats
---

# /graphics-convert

Convert an image to a different format.

## Usage

`/graphics-convert <image-path> <target-format> [--quality N] [--optimize]`

## What it does

1. Validates the input path against `GRAPHICS_ALLOWED_DIRECTORIES`
2. Calls `mcp__graphics__convert_image` with the requested format and optional quality/optimize flags
3. Returns the output path and size delta

## Example

`/graphics-convert /Users/les/Pictures/photo.png webp --quality 85`
```

### 5.2 css-mcp

**Repo:** `/Users/les/Projects/css-mcp/`
**Version:** 0.3.2 (current)
**Port:** 3050 (HTTP)
**MCP server key (proposed):** `css`

**New files:**

1. `.claude-plugin/plugin.json`
   ```json
   {
     "author": {"name": "Bodai"},
     "description": "Bodai plugin for the css-mcp CSS analysis server.",
     "keywords": ["bodai", "mcp", "css", "analysis", "mdn"],
     "mcpServers": "./.mcp.json",
     "name": "css",
     "schema_version": "1.0.0",
     "version": "0.1.0"
   }
   ```

2. `.mcp.json` (repo root)
   ```json
   {
     "css": {
       "type": "http",
       "url": "http://localhost:3050/mcp"
     }
   }
   ```

3. `commands/css-audit-project.md` — wraps `mcp__css__analyze_project_css`
4. `commands/css-analyze.md` — wraps `mcp__css__analyze_css`
5. `commands/css-check-compat.md` — multi-step orchestration over `mcp__css__get_browser_compatibility` + `mcp__css__get_docs`

**Modified files:**
- `README.md` — add `## Installation via Bodai Marketplace` section.

### 5.3 bodai-plugins marketplace

**File:** `/Users/les/Projects/bodai-plugins/.claude-plugin/marketplace.json`

Add two entries to the `plugins` array:
```json
{"name": "graphics", "source": "../graphics-mcp", "ref": "main"},
{"name": "css", "source": "../css-mcp", "ref": "main"}
```

## 6. Validation steps

1. Run `bodai-plugins validate --path ./graphics-mcp` — must pass with 0 errors.
2. Run `bodai-plugins validate --path ./css-mcp` — must pass with 0 errors.
3. Run `bodai-plugins validate --path ./bodai-plugins` — confirms marketplace.json schema is still valid.
4. Smoke test: from a fresh session, `claude plugin marketplace add /Users/les/Projects/bodai-plugins` then `claude plugin install graphics --marketplace bodai-plugins`. Confirm slash commands appear.
5. Verify the existing `.mcp.json` registrations still work (the dual-registration is intentional during transition).

## 7. Acceptance criteria

- [ ] `graphics-mcp` has all 5 new files; `css-mcp` has all 5 new files.
- [ ] Both `bodai-plugins validate` checks pass.
- [ ] `marketplace.json` parses and includes both new entries.
- [ ] All 6 slash commands have valid YAML frontmatter with `description`, `argument-hint`, `allowed-tools`.
- [ ] All `allowed-tools` lists use fully-qualified `mcp__<server>__<tool>` names.
- [ ] Each repo's README has a new `## Installation via Bodai Marketplace` section.
- [ ] No regression to existing `.mcp.json` registrations.
- [ ] `crackerjack run` (or equivalent quality gate) passes on both repos.

## 8. Decision points

These need user input before implementation:

1. **MCP server key naming** — proposed: `graphics` and `css` (matches the slash command namespace). Alternative: `graphics-mcp` and `css-mcp` (matches the repo name). The bodai "one string, three places" rule means the choice cascades to plugin name, server key, and command namespace.

2. **Frontmatter protection** — should we add `commands/*.md` to `[tool.mdformat]` exclude list in both repos' pyproject.toml? Recommended yes, to prevent the crackerjack bug.

3. **Backend registration** — graphics-mcp uses HTTP transport (already documented). css-mcp also uses HTTP. No stdio cmd is provided. The `.mcp.json` will use the `{type: "http", url: ...}` shape only.

## 9. Effort estimate

- graphics-mcp: scaffold + 3 commands + README = ~1.5 hours
- css-mcp: scaffold + 3 commands + README = ~1.5 hours
- marketplace.json update: ~5 minutes
- Validation + smoke test: ~30 minutes
- **Total: ~3.5 hours**

If the POC passes, the remaining 13 repos can be batched in a single marketplace PR with similar per-repo effort (~1-2 hours each, depending on command complexity).

## 10. Next steps after POC approval

1. Use the writing-plans skill to convert this scope into a detailed implementation plan.
2. Dispatch parallel implementers for graphics-mcp and css-mcp (separate worktrees, no shared state).
3. After both land, do a single-PR marketplace.json update + validation.
4. Smoke test the plugin install end-to-end.
5. If POC passes, write the "convert the remaining 13 repos" plan.
