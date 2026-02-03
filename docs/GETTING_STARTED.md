# Getting Started with Mahavishnu

Welcome to Mahavishnu, a multi-engine orchestration platform for managing workflows across multiple repositories. This guide will help you get up and running quickly.

## Table of Contents

- [Visual Learning](#visual-learning) ⭐ **Start here if you're a visual learner!**
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [First Run](#first-run)
- [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)
- [Next Steps](#next-steps)

## Visual Learning

**Prefer diagrams over text? You're in luck!** 🎨

Mahavishnu includes comprehensive visual documentation with **50+ diagrams** covering every aspect of the system:

### 🎯 **Essential Diagrams**

1. **[Visual Guide](VISUAL_GUIDE.md)** - Master collection of all diagrams
   - Overall system architecture with all components
   - Pool management system with scaling strategies
   - Memory aggregation flow (concurrent collection)
   - Authentication architecture (multi-method security)
   - Performance before/after comparisons (10-50x improvements!)
   - Testing coverage pyramid
   - Dead letter queue flow
   - Quality metrics timeline

2. **[Workflow Diagrams](WORKFLOW_DIAGRAMS.md)** - Step-by-step operational procedures
   - Quick start setup flow
   - Pool spawn and execute sequences
   - Repository sweep operations
   - Memory search with caching
   - Quality control pipeline
   - Error recovery patterns
   - MCP tool execution flow

### 📊 **Key Visual Aids**

**Architecture Overview:**
```mermaid
graph TB
    User([User]) --> CLI[CLI]
    User --> MCP[MCP Server]
    CLI --> App[MahavishnuApp]
    MCP --> App
    App --> Pools[Pool Manager]
    App --> Adapters[Adapters]
    App --> Workers[Workers]
```

**Performance Improvements:**
| Operation | Before | After | Improvement |
|-----------|--------|-------|-------------|
| Memory Aggregation | 50s | 2s | **25x faster** ⚡ |
| Pool Collection | 10s | 1s | **10x faster** ⚡ |
| Cross-Pool Search | 1-2s | 0.1s | **10-20x faster** ⚡ |

### 💡 **How to Use These Visuals**

- **New to Mahavishnu?** Start with the [Quick Start Workflow](WORKFLOW_DIAGRAMS.md#1-quick-start-workflow)
- **Understanding architecture?** See [Overall Architecture](VISUAL_GUIDE.md#1-overall-architecture)
- **Setting up pools?** Follow [Pool Spawn and Execute](WORKFLOW_DIAGRAMS.md#2-pool-spawn-and-execute)
- **Troubleshooting?** Check [Error Recovery](WORKFLOW_DIAGRAMS.md#6-error-recovery)
- **Curious about performance?** View [Performance Optimizations](VISUAL_GUIDE.md#6-performance-optimizations)

---

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.11+** - Mahavishnu requires Python 3.11 or later
- **uv** (recommended) or **pip** - For package management
- **git** - For repository operations
- **Optional dependencies**:
  - **Ollama** - For local LLM embeddings (LlamaIndex adapter)
  - **OpenSearch** - For vector storage and observability
  - **PostgreSQL + pgvector** - For OTel trace storage (optional)

### Check Your Prerequisites

```bash
# Check Python version
python --version  # Should be 3.11+

# Check if uv is installed (recommended)
uv --version

# Or check pip
pip --version

# Check git
git --version
```

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/mahavishnu.git
cd mahavishnu
```

### Step 2: Create Virtual Environment

**Using uv (recommended):**

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

**Using pip:**

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Step 3: Install Dependencies

**With uv:**

```bash
uv pip install -e ".[dev]"
```

**With pip:**

```bash
pip install -e ".[dev]"
```

The `[dev]` extra includes development tools like pytest, ruff, and mypy.

### Step 4: Verify Installation

```bash
mahavishnu --help
```

You should see the Mahavishnu CLI help message with all available commands.

## Configuration

Mahavishnu uses a layered configuration system:

1. **Default values** in Pydantic models
2. **`settings/mahavishnu.yaml`** (committed to git)
3. **`settings/local.yaml`** (gitignored, for local development)
4. **Environment variables** (`MAHAVISHNU_{GROUP}__{FIELD}`)

### Step 1: Review Default Configuration

The default configuration is in `settings/mahavishnu.yaml`:

```yaml
# Server settings
server_name: "Mahavishnu Orchestrator"
log_level: INFO

# Repository manifest
repos_path: settings/repos.yaml

# Adapters (currently stub implementations)
adapters:
  prefect_enabled: true
  llamaindex_enabled: false
  agno_enabled: true

# LLM configuration
llm:
  model: nomic-embed-text
  ollama_base_url: http://localhost:11434

# Pool management
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"

# Worker orchestration
workers:
  enabled: true
  max_concurrent: 10
  default_type: "terminal-qwen"

# Quality control
qc:
  enabled: true
  min_score: 80
```

### Step 2: Create Local Configuration (Optional)

For local development, create `settings/local.yaml`:

```yaml
# Local development overrides
server_name: "Mahavishnu Local Dev"
log_level: DEBUG

# Enable terminal management
terminal:
  enabled: true
  max_concurrent_sessions: 20
```

### Step 3: Configure Repositories

Edit `settings/repos.yaml` to add your repositories:

```yaml
repos:
  - name: "my-project"
    package: "my_project"
    path: "/path/to/my-project"
    nickname: "myproj"
    role: "app"
    tags: ["backend", "python"]
    description: "My backend application"
    mcp: "native"
```

See [Repository Roles](#repository-roles) below for available role types.

### Step 4: Set Environment Variables (Optional)

For sensitive configuration, use environment variables:

```bash
# Authentication secret (if auth enabled)
export MAHAVISHNU_AUTH__SECRET="your-32-character-secret-key-here"

# OTel storage connection (if enabled)
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://user:pass@host/db"

# Cross-project auth
export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="shared-secret-key"
```

## First Run

### List All Repositories

```bash
mahavishnu list-repos
```

**Example output:**

```
All repositories:
  - /Users/les/Projects/crackerjack (inspector)
  - /Users/les/Projects/session-buddy (manager)
  - /Users/les/Projects/mahavishnu (orchestrator)
```

### Filter by Tag

```bash
mahavishnu list-repos --tag python
```

### Filter by Role

```bash
mahavishnu list-repos --role tool
```

### List Available Roles

```bash
mahavishnu list-roles
```

**Example output:**

```
Available roles (12):

  ORCHESTRATOR
  Description: Coordinates workflows and manages cross-repository operations
  Capabilities: sweep, schedule, monitor, route, coordinate

  MANAGER
  Description: Manages state, sessions, and knowledge across the ecosystem
  Capabilities: capture, search, restore, track, analyze
  ...
```

### Start the MCP Server

```bash
mahavishnu mcp start
```

The MCP server will start on `http://127.0.0.1:3000` by default.

**Output:**

```
MCP Server: Authentication not configured
MCP Server: Terminal management disabled
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:3000
```

### Start the Admin Shell

```bash
mahavishnu shell
```

This launches an interactive IPython shell for debugging and monitoring.

**Available shell commands:**

- `ps()` - Show all workflows
- `top()` - Show active workflows with progress
- `errors(n=10)` - Show recent errors
- `%repos` - List repositories
- `%workflow <id>` - Show workflow details

## Common Workflows

### Workflow 1: Repository Discovery

**Goal:** Find all Python backend repositories in your ecosystem.

```bash
# List by tag
mahavishnu list-repos --tag backend

# List by role
mahavishnu list-repos --role builder

# Show role details
mahavishnu show-role builder
```

### Workflow 2: Spawn a Worker Pool

**Goal:** Create a local worker pool for parallel task execution.

```bash
# Spawn pool with 2-5 workers
mahavishnu pool spawn --type mahavishnu --name local-pool --min 2 --max 5

# List all pools
mahavishnu pool list

# Check pool health
mahavishnu pool health
```

### Workflow 3: Execute Tasks on Workers

**Goal:** Execute AI tasks across worker pools.

```bash
# Execute on specific pool
mahavishnu pool execute pool_abc123 --prompt "Write unit tests for auth.py"

# Auto-route to best pool
mahavishnu pool route --prompt "Refactor database layer" --selector least_loaded

# Scale pool based on load
mahavishnu pool scale pool_abc123 --target 10
```

### Workflow 4: Monitor System Health

**Goal:** Check overall system status and performance.

```bash
# Check MCP server status
mahavishnu mcp status

# Check MCP server health
mahavishnu mcp health

# Monitor metrics
mahavishnu metrics collect

# Show metrics dashboard
mahavishnu metrics dashboard
```

### Workflow 5: Cross-Repository Coordination

**Goal:** Track and coordinate work across multiple repositories.

```bash
# Create coordination ticket
mahavishnu coord create --repo my-project --title "Add authentication" --priority HIGH

# List all tickets
mahavishnu coord list

# Update ticket status
mahavishnu coord update TICKET_123 --status IN_PROGRESS
```

### Workflow 6: Backup and Recovery

**Goal:** Backup configuration and state for disaster recovery.

```bash
# Create backup
mahavishnu backup create --description "Before major refactor"

# List backups
mahavishnu backup list

# Restore from backup
mahavishnu backup restore BACKUP_ID
```

### Workflow 7: Production Readiness

**Goal:** Validate system is ready for production deployment.

```bash
# Run all production checks
mahavishnu production check

# Run security audit
mahavishnu production audit --type security

# Run performance benchmarks
mahavishnu production benchmark
```

## Repository Roles

Mahavishnu uses a role-based taxonomy to organize repositories:

| Role | Description | Example |
|------|-------------|---------|
| `orchestrator` | Coordinates workflows | mahavishnu |
| `resolver` | Resolves components | oneiric |
| `manager` | Manages state | session-buddy |
| `inspector` | Validates quality | crackerjack |
| `builder` | Builds applications | fastblocks |
| `app` | End-user apps | mdinject |
| `asset` | UI libraries | fastbulma |
| `foundation` | Shared utilities | mcp-common |
| `visualizer` | Creates diagrams | excalidraw-mcp |
| `tool` | MCP integrations | mailgun-mcp |

## Troubleshooting

### Issue: "Command not found: mahavishnu"

**Solution:** Make sure your virtual environment is activated and Mahavishnu is installed in editable mode.

```bash
# Activate virtual environment
source .venv/bin/activate

# Reinstall in editable mode
pip install -e .

# Verify installation
which mahavishnu  # Should show path to venv/bin/mahavishnu
```

### Issue: "repos.yaml not found"

**Solution:** Create the repository manifest file.

```bash
# Copy example repos.yaml
cp settings/repos.yaml.example settings/repos.yaml

# Edit with your repositories
nano settings/repos.yaml
```

### Issue: "Authentication failed"

**Solution:** Check your authentication configuration.

```bash
# If using JWT auth
export MAHAVISHNU_AUTH__SECRET="your-32-character-secret"

# If using Claude Code subscription
mahavishnu generate-claude-token

# If using Qwen free service
# No configuration needed, automatically detected
```

### Issue: "MCP server won't start"

**Solution:** Check if the port is already in use.

```bash
# Check what's using port 3000
lsof -i :3000

# Kill the process or use a different port
mahavishnu mcp start --port 3001
```

### Issue: "Pool spawn failed"

**Solution:** Verify pool dependencies are configured.

```bash
# Check pool configuration in settings/mahavishnu.yaml
cat settings/mahavishnu.yaml | grep -A 10 pools:

# Ensure pools are enabled
pools:
  enabled: true  # Must be true

# Check worker configuration
workers:
  enabled: true  # Must be true
```

### Issue: "Worker execution timeout"

**Solution:** Increase timeout or check worker type compatibility.

```bash
# Increase timeout in settings/mahavishnu.yaml
workers:
  timeout_seconds: 600  # Increase from default 300

# Or use timeout parameter
mahavishnu pool execute pool_abc --prompt "..." --timeout 600
```

### Issue: "Terminal management not working"

**Solution:** Ensure terminal management is enabled and you have the required dependencies.

```bash
# Enable terminal management
# In settings/mahavishnu.yaml:
terminal:
  enabled: true
  adapter_preference: "auto"  # or "iterm2" / "mcpretentious"

# Install iTerm2 Python API (if using iTerm2)
pip install iterm2

# Check terminal status
mahavishnu terminal list
```

## Next Steps

### Learn More

- **[Architecture](ARCHITECTURE.md)** - Complete architecture overview
- **[Admin Shell Guide](docs/ADMIN_SHELL.md)** - Interactive debugging and monitoring
- **[Pool Architecture](docs/POOL_ARCHITECTURE.md)** - Multi-pool orchestration details
- **[MCP Tools Reference](docs/MCP_TOOLS_REFERENCE.md)** - Complete MCP tool API documentation
- **[Production Deployment](docs/PRODUCTION_DEPLOYMENT_GUIDE.md)** - Production readiness checklist

### Development

- **[Testing](#testing)** - Run tests and contribute
- **[Configuration Reference](#configuration-reference)** - All configuration options
- **[Security](SECURITY_CHECKLIST.md)** - Security guidelines and best practices

### Advanced Features

- **[OpenTelemetry Integration](docs/NATIVE_OTEL_SETUP_GUIDE.md)** - Distributed tracing setup
- **[Cross-Repository Messaging](docs/CROSS_REPO_COORDINATION_PLAN.md)** - Message passing between repos
- **[Disaster Recovery](docs/MAINTENANCE_PROCEDURES.md)** - Backup and restore procedures

## Testing

Run the test suite to verify your installation:

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run with coverage
pytest --cov=mahavishnu --cov-report=html

# Run specific test file
pytest tests/unit/test_config.py -v
```

## Configuration Reference

### Environment Variables

All configuration can be overridden via environment variables using the pattern `MAHAVISHNU_{GROUP}__{FIELD}`:

```bash
# Top-level settings
export MAHAVISHNU_LOG_LEVEL="DEBUG"
export MAHAVISHNU_SERVER_NAME="My Mahavishnu"

# Nested settings
export MAHAVISHNU_POOLS__ENABLED="true"
export MAHAVISHNU_POOLS__DEFAULT_TYPE="mahavishnu"
export MAHAVISHNU_AUTH__SECRET="my-secret-key"
export MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING="postgresql://..."

# Boolean values
export MAHAVISHNU_DEBUG="true"  # "true" or "false"
```

### Configuration File Priority

Configuration is loaded in this order (later overrides earlier):

1. Default values in Pydantic models
2. `settings/mahavishnu.yaml` (committed)
3. `settings/local.yaml` (gitignored)
4. Environment variables

### Validation

Mahavishnu validates all configuration on startup:

```python
# This will raise an error if connection_string is invalid
# when otel_storage.enabled is true
otel_storage:
  enabled: true
  connection_string: "postgresql://user:password@host/db"  # Must be set
```

## Getting Help

- **Documentation:** See the `docs/` directory for comprehensive guides
- **Issues:** Report bugs on GitHub Issues
- **Discussions:** Ask questions on GitHub Discussions
- **Admin Shell:** Use `mahavishnu shell` for interactive debugging

## Contributing

We welcome contributions! Please see the main README.md for contribution guidelines.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request

**Happy orchestrating!**
