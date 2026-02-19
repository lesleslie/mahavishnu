# Mahavishnu Quick Start Guide

Get up and running with Mahavishnu in 5 minutes!

## What is Mahavishnu?

Mahavishnu is a multi-engine orchestration platform that helps you:
- **Manage tasks** across multiple repositories
- **Search semantically** to find related work
- **Track progress** with status and priority management
- **Coordinate work** across distributed systems

## Installation

```bash
# Using uv (recommended)
uv pip install mahavishnu

# Or with pip
pip install mahavishnu
```

## First-Time Setup

### 1. Initialize Configuration

```bash
# Create default configuration
mahavishnu init

# Or manually create settings/repos.yaml
```

### 2. Configure Your Repositories

Edit `settings/repos.yaml`:

```yaml
repos:
  - name: my-project
    path: /path/to/my/project
    role: tool
    tags: [python, api]
    description: My awesome project
```

### 3. Verify Setup

```bash
# Check system health
mahavishnu health

# List configured repositories
mahavishnu list-repos
```

## Basic Usage

### Creating Tasks

```bash
# Create a simple task
mahavishnu task create "Fix login bug" -r my-project

# Create with priority and tags
mahavishnu task create "Add new feature" -r my-project -p high -t feature -t backend

# Shorthand version
mhv tc "Quick fix" -r my-project
```

### Listing Tasks

```bash
# List all tasks
mahavishnu task list

# Filter by repository
mahavishnu task list -r my-project

# Filter by status
mahavishnu task list -s in_progress

# Filter by priority
mahavishnu task list -p high

# Shorthand
mhv tl -r my-project -s pending
```

### Updating Tasks

```bash
# Update status
mahavishnu task update task-123 -s completed

# Update priority
mahavishnu task update task-123 -p critical

# Quick status change
mahv ts task-123 completed

# Shorthand
mhv tu task-123 -s in_progress -p high
```

### Deleting Tasks

```bash
# Delete with confirmation
mahavishnu task delete task-123

# Force delete without confirmation
mahv td task-123 -f
```

## Semantic Search

Search for tasks using natural language:

```bash
# Semantic search
mahavishnu search tasks "bug fix authentication"

# Find similar tasks
mahavishnu search similar task-123
```

## Command Reference

### Task Commands

| Command | Shorthand | Description |
|---------|-----------|-------------|
| `task create` | `tc` | Create a new task |
| `task list` | `tl` | List tasks with filters |
| `task update` | `tu` | Update a task |
| `task delete` | `td` | Delete a task |
| `task status` | `ts` | Quick status update |

### Repository Commands

| Command | Description |
|---------|-------------|
| `list-repos` | List all repositories |
| `list-repos --tag backend` | Filter by tag |
| `list-repos --role tool` | Filter by role |
| `list-roles` | List available roles |
| `show-role <role>` | Show role details |

### System Commands

| Command | Description |
|---------|-------------|
| `health` | Check system health |
| `mcp start` | Start MCP server |
| `mcp status` | Check MCP server status |

## Task Properties

### Status Values

- `pending` - Not started
- `in_progress` - Currently working
- `completed` - Finished successfully
- `failed` - Did not complete
- `cancelled` - Cancelled by user
- `blocked` - Waiting on dependency

### Priority Levels

- `low` - Low priority
- `medium` - Default priority
- `high` - High priority
- `critical` - Urgent/critical

### Due Dates

Supports natural language parsing:

```bash
--due today
--due tomorrow
--due "next week"
--due "in 5 days"
--due "2024-12-31"
```

## Configuration

### repos.yaml Structure

```yaml
repos:
  - name: repo-name           # Required: lowercase with hyphens
    path: /path/to/repo       # Required: filesystem path
    package: python_pkg       # Optional: Python package name
    nickname: short           # Optional: short alias
    role: tool                # Optional: repository role
    tags: [python, api]       # Optional: categorization tags
    description: "Description" # Optional: human-readable description
    mcp: native               # Optional: native or 3rd-party
```

### Available Roles

| Role | Description |
|------|-------------|
| `orchestrator` | Coordinates workflows |
| `resolver` | Resolves components |
| `manager` | Manages state/sessions |
| `inspector` | Validates code quality |
| `builder` | Builds applications |
| `soothsayer` | Reveals patterns |
| `app` | End-user applications |
| `asset` | UI libraries |
| `foundation` | Shared utilities |
| `visualizer` | Creates diagrams |
| `extension` | Pluggable modules |
| `tool` | MCP tool integrations |

## Shell Completion

Enable shell completion for faster command entry:

### Bash

```bash
# Add to ~/.bashrc
source <(mahavishnu --show-completion bash)
```

### Zsh

```bash
# Add to ~/.zshrc
autoload -U +X compinit && compinit
autoload -U +X bashcompinit && bashcompinit
source <(mahavishnu --show-completion bash)
```

### Fish

```fish
# Add to ~/.config/fish/config.fish
mahavishnu --show-completion fish | source
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MAHAVISHNU_REPOS` | Comma-separated list of repository names |
| `MAHAVISHNU_DEBUG` | Enable debug logging |
| `MAHAVISHNU_CONFIG_DIR` | Custom configuration directory |

## Next Steps

- Run the interactive tutorial: `mahavishnu tutorial`
- Explore all commands: `mahavishnu --help`
- Read the full documentation: `docs/`
- Join the community: `https://github.com/yourorg/mahavishnu`

## Getting Help

```bash
# General help
mahavishnu --help

# Command-specific help
mahavishnu task create --help
mahavishnu task list --help

# System information
mahavishnu version
mahavishnu health
```

## Common Issues

### Configuration not found

```bash
# Create default configuration
mahavishnu init
```

### Repository path not found

```bash
# Verify path in repos.yaml
ls /path/to/your/repo

# Update configuration
mahavishnu config validate
```

### Database connection error

```bash
# Check PostgreSQL is running
docker-compose up -d postgres

# Verify connection
mahavishnu health
```

---

**Need more help?** Check the [full documentation](docs/) or open an issue on GitHub.
