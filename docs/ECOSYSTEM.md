# Mahavishnu Ecosystem Management Guide

## Overview

The `ecosystem.yaml` file is the **single source of truth** for your entire development ecosystem. It tracks:

- **24 git repositories** with roles, tags, and audit timestamps
- **14 MCP servers** with ports, commands, health checks, and dependencies
- **83 Claude agents** with categorization and relevance tracking
- **18 workflows** with validation timestamps
- **64 skills** with usage tracking
- **49 tools** with maintenance tracking
- **12 role definitions** for repository classification

## Quick Start

```bash
# Validate all configurations
mahavishnu ecosystem validate

# List all enabled MCP servers
mahavishnu ecosystem list

# Generate ~/.claude.json from ecosystem.yaml
mahavishnu ecosystem generate-claude-config

# Show audit info for a specific server
mahavishnu ecosystem audit mahavishnu

# Update audit timestamp
mahavishnu ecosystem update-audit crackerjack last_validated "2026-01-29" --notes "Tested all quality checks"
```

## Architecture

### File Structure

```
mahavishnu/
├── settings/
│   ├── mahavishnu.yaml       # Runtime configuration (Oneiric)
│   ├── repos.yaml            # Repository manifest (legacy, being migrated)
│   └── ecosystem.yaml         # ⭐ ECOSYSTEM CATALOG (this file)
├── core/
│   ├── ecosystem.py          # Config loader and manager
│   └── ...
└── ecosystem_cli.py           # CLI commands
```

### Relationship to repos.yaml

The `repos.yaml` file is being **migrated into** `ecosystem.yaml`. The `repos` section in `ecosystem.yaml` now contains all 24 repositories with enhanced audit tracking:

**Before** (repos.yaml only):
- name, path, role, tags, description, mcp

**After** (ecosystem.yaml):
- All of the above **PLUS**
- `audit.last_reviewed` - When the repo was last reviewed
- `audit.last_cleaned` - When the repo was last cleaned up
- `audit.notes` - Freeform notes about the repo's status

## Adding New MCP Servers

### 1. Add to ecosystem.yaml

Edit `settings/ecosystem.yaml` and add a new entry to the `mcp_servers` section:

```yaml
mcp_servers:
  - name: "my-server"
    type: "http"              # or "stdio"
    port: 3040                # Required for http, null for stdio
    path: "/Users/les/Projects/my-project"
    package: "my_project"
    category: "tool"          # See role taxonomy below
    function: "Brief description"
    command: ".venv/bin/python -m my_package.mcp.server --host 127.0.0.1 --port {port}"
    description: "Full description of what this server does"
    health_check: "http://127.0.0.1:{port}/health"  # For http servers only
    status: "enabled"         # or "disabled"
    tags: ["tool", "api", "integration"]
    dependencies: []
    maintainer: "les"
    audit:
      last_validated: "2026-01-29"
      last_tested: "2026-01-29"
      notes: "Initial setup"
```

### 2. Field Descriptions

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Unique identifier for the server (used in ~/.claude.json) |
| `type` | ✅ | "http" or "stdio" |
| `port` | Conditional | Port number (required for http, must be null for stdio) |
| `path` | ✅ | Where the code/binary lives |
| `package` | | Python package name (null for binaries/external tools) |
| `category` | ✅ | Matches role taxonomy (see below) |
| `function` | ✅ | Short description of what it does |
| `command` | ✅ | Command to start the server (use `{port}` for http servers) |
| `description` | ✅ | Detailed description |
| `health_check` | | HTTP endpoint for health checks (http only) |
| `status` | ✅ | "enabled" or "disabled" |
| `tags` | | List of tags for filtering/grouping |
| `dependencies` | | List of server names this server depends on |
| `maintainer` | | "les" (internal) or "external" (third-party) |
| `repo_url` | | Source code repository URL (GitHub, GitLab, etc.) |
| `homepage_url` | | Project homepage URL |
| `docs_url` | | Documentation URL |
| `urls` | | Additional categorized URLs (e.g., issues, examples, api) |
| `audit` | | Audit tracking (see below) |

### 3. Port Allocation

Follow these guidelines:

**Infrastructure (8676-8682)**:
- 8676: crackerjack (inspector)
- 8678: session-buddy (manager)
- 8680: mahavishnu (orchestrator)
- 8681: oneiric (resolver)
- 8682: akosha (aggregator)

**Tools & Integrations (3032-3039)**:
- 3032: excalidraw (visualizer)
- 3033: mermaid (visualizer)
- 3034: raindropio (tool)
- 3038: unifi (tool)
- 3039: mailgun (tool)

**STDIO servers**: No port needed (managed by Claude Code)

## Updating Audit Timestamps

### Manual Updates

```bash
# Update audit info for a server
mahavishnu ecosystem update-audit mahavishnu last_tested "2026-01-29" \
  --notes "Verified all workflow adapters working"
```

### Audit Fields

| Field | Usage |
|-------|-------|
| `last_validated` | Configuration is correct and valid |
| `last_tested` | Server was tested and working |
| `last_reviewed` | Code was reviewed for updates/relevance |
| `last_cleaned` | Directory was cleaned up (old files removed) |

### Automated Audit Tracking

The ecosystem.yaml file is backed up to GitLab:
- **Repo**: `git@gitlab.com:lesleslie/dot-claude.git`
- **Path**: `/Users/les/.claude`
- **Schedule**: Daily (automatic)

This ensures all audit information is preserved.

## Role Taxonomy

Categories for MCP servers and repositories:

| Role | Description | Capabilities |
|------|-------------|-------------|
| `orchestrator` | Coordinates workflows and manages cross-repository operations | sweep, schedule, monitor, route, coordinate |
| `resolver` | Resolves components, dependencies, and lifecycle management | resolve, activate, swap, explain, watch |
| `manager` | Manages state, sessions, and knowledge across the ecosystem | capture, search, restore, track, analyze |
| `inspector` | Validates code quality and enforces development standards | test, lint, scan, report, validate |
| `builder` | Builds applications and web interfaces | render, route, authenticate, build |
| `aggregator` | Aggregates data and analytics across distributed systems | aggregate, search, detect, correlate, graph |
| `app` | End-user applications with graphical interfaces | interface, automate, serve-users, integrate |
| `asset` | UI libraries, component collections, and style guides | style, theme, componentize, design |
| `foundation` | Foundational utilities, libraries, and shared code | share, standardize, abstract, build-upon |
| `visualizer` | Creates visual diagrams and documentation | draw, render, visualize, document |
| `extension` | Extends framework capabilities with pluggable modules | extend, filter, enhance, plug-in |
| `tool` | Specialized tools and integrations via MCP protocol | connect, expose, integrate |
| `database` | Databases and data storage systems | query, persist, index, search |

## Repository Management

### Adding a New Repository

1. Create the repository
2. Add it to `repos.yaml` (for now)
3. Add it to `ecosystem.yaml` in the appropriate role section
4. Include audit timestamps

### Repository Audit Fields

```yaml
repos:
  - name: "my-repo"
    package: "my_repo"
    path: "/Users/les/Projects/my-repo"
    role: "tool"
    tags: ["python", "api", "integration"]
    description: "My awesome repository"
    mcp: null  # or "native" if it has an MCP server
    audit:
      last_reviewed: "2026-01-29"
      last_cleaned: "2026-01-28"
      notes: "Initial setup, actively developing"
```

## CLI Commands Reference

### `ecosystem validate`

Validate all MCP server configurations:
```bash
mahavishnu ecosystem validate
```

Checks for:
- Port conflicts
- Missing paths
- Missing packages
- Dependency issues
- Health check configuration

### `ecosystem list`

List MCP servers with filtering:
```bash
# List all enabled servers
mahavishnu ecosystem list

# List only visualizers
mahavishnu ecosystem list --category visualizer

# List only disabled servers
mahavishnu ecosystem list --status disabled
```

### `ecosystem generate-claude-config`

Generate or update ~/.claude.json:
```bash
# Dry run (print to console)
mahavishnu ecosystem generate-claude-config --dry-run

# Actually write to ~/.claude.json
mahavishnu ecosystem generate-claude-config

# Specify different output path
mahavishnu ecosystem generate-claude-config --output ~/test-claude.json
```

### `ecosystem audit`

Show audit information:
```bash
# Show all servers
mahavishnu ecosystem audit

# Show specific server
mahavishnu ecosystem audit crackerjack
```

### `ecosystem update-audit`

Update audit timestamps:
```bash
mahavishnu ecosystem update-audit <server_name> <field> <timestamp> [--notes <notes>]

# Examples
mahavishnu ecosystem update-audit crackerjack last_validated "2026-01-29"
mahavishnu ecosystem update-audit oneiric last_tested "2026-01-29" --notes "Fixed import path"
```

### `ecosystem urls`

Show all URLs for an MCP server:
```bash
mahavishnu ecosystem urls <server_name>

# Example
mahavishnu ecosystem urls mahavishnu
```

Output includes:
- 📦 Repository URL
- 🏠 Homepage URL
- 📚 Documentation URL
- 📎 Additional URLs (issues, examples, api, etc.)

### `ecosystem repo-urls`

Show all URLs for a repository:
```bash
mahavishnu ecosystem repo-urls <repo_name>

# Example
mahavishnu ecosystem repo-urls mahavishnu
```

Output format is identical to `ecosystem urls` but for repositories.

## Best Practices

### 1. Keep ecosystem.yaml as Single Source of Truth

- **DO** add MCP servers to ecosystem.yaml first
- **DO** use `mahavishnu ecosystem generate-claude-config` to update ~/.claude.json
- **DON'T** manually edit ~/.claude.json MCP server configurations

### 2. Audit Regularly

```bash
# Weekly: Validate all configurations
mahavishnu ecosystem validate

# Monthly: Review all repos and servers
mahavishnu ecosystem audit

# Quarterly: Clean up directories
mahavishnu ecosystem cleanup
```

### 3. Document Changes

When adding or updating servers:
1. Update `last_validated` timestamp
2. Add meaningful notes in `audit.notes`
3. Include dependencies if applicable
4. Set correct category and tags

### 4. Port Allocation

- Use 8676-8682 for infrastructure/orchestration
- Use 3032-3039 for tools and integrations
- Document port conflicts in notes
- Keep stdio servers together (no ports)

### 5. Dependency Management

- List all dependencies in the `dependencies` field
- Mahavishnu will use this for dependency-ordered startup
- Validate dependencies before committing

## Migration from repos.yaml

The `repos.yaml` file is being migrated into `ecosystem.yaml`. Key differences:

| repos.yaml | ecosystem.yaml |
|------------|----------------|
| Basic metadata | Enhanced metadata + audit tracking |
| No timestamps | Full audit history |
| Separate file | Integrated with ecosystem catalog |

**Migration plan**:
1. ✅ All repos are now in ecosystem.yaml
2. ⏳ Update tools to read from ecosystem.yaml instead of repos.yaml
3. ⏳ Deprecate repos.yaml (add migration warning)
4. ⏳ Eventually remove repos.yaml

## Troubleshooting

### Validation Errors

**Port conflict**:
```
❌ mahavishnu: Port 8680 conflicts with: oneiric
```
**Solution**: Change port in ecosystem.yaml

**Missing path**:
```
❌ my-server: Path does not exist: /Users/les/Projects/missing
```
**Solution**: Verify path or update path in ecosystem.yaml

**Missing package**:
```
❌ my-server: Package 'my_package' not installed
```
**Solution**: Install the package or fix package name

### Generation Issues

If `generate-claude-config` fails:
1. Check file permissions on ~/.claude.json
2. Validate ecosystem.yaml first: `mahavishnu ecosystem validate`
3. Check JSON syntax in existing ~/.claude.json

## Related Documentation

- **CLAUDE.md**: Project-specific instructions
- **README.md**: General project documentation
- **docs/architecture/**: Architecture Decision Records
- **settings/mahavishnu.yaml**: Runtime configuration
- **settings/repos.yaml**: Legacy repository manifest

## Getting Help

```bash
# Show help for ecosystem commands
mahavishnu ecosystem --help

# Show help for specific command
mahavishnu ecosystem validate --help

# Check ecosystem configuration status
mahavishnu ecosystem status
```
