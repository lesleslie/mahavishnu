# Dynamic Capabilities CLI

User-friendly interface for managing dynamic capabilities in the Mahavishnu ecosystem.

## Overview

The Dynamic Capabilities system provides a plugin-like architecture for loading, managing, and hot-swapping capabilities at runtime without requiring application restarts.

## Installation

The capabilities CLI is included with Mahavishnu:

```bash
pip install mahavishnu[capabilities]
```

## Quick Start

```bash
# List all capabilities
mahavishnu capabilities list

# Load a capability
mahavishnu capabilities load --name sentiment-analysis --source /path/to/capability

# Check health
mahavishnu capabilities health --all

# Monitor in real-time
mahavishnu capabilities watch
```

## Commands

### `list`

List all capabilities with filtering options.

**Usage:**
```bash
mahavishnu capabilities list [OPTIONS]
```

**Options:**
- `--loaded-only`: Show only loaded capabilities
- `--available-only`: Show only available (not loaded) capabilities
- `--format, -f`: Output format (table, json, yaml, markdown)

**Examples:**
```bash
# List all capabilities
mahavishnu capabilities list

# List only loaded capabilities
mahavishnu capabilities list --loaded-only

# List available capabilities as JSON
mahavishnu capabilities list --available-only --format json

# Export as Markdown
mahavishnu capabilities list --format markdown > capabilities.md
```

**Output (Table Format):**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Name                         ┃ Version    ┃ Status     ┃ Health     ┃ Description                                  ┃ Author             ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ ✓ sentiment-analysis         │ 1.0.0      │ loaded     │ healthy    │ Analyze sentiment from event text            │ Ecosystem Team     │
│ ⟳ text-processor             │ 2.1.0      │ loading    │ unknown    │ Process and normalize text data              │ Data Team          │
│ - anomaly-detection          │ 1.2.3      │ unloaded   │ unknown    │ Detect anomalies in time series data         │ ML Team            │
└──────────────────────────────┴────────────┴────────────┴────────────┴──────────────────────────────────────────────┴────────────────────┘
```

### `get`

Get detailed information about a specific capability.

**Usage:**
```bash
mahavishnu capabilities get NAME [OPTIONS]
```

**Options:**
- `--format, -f`: Output format (table, json, yaml, markdown)

**Examples:**
```bash
# Get capability details
mahavishnu capabilities get sentiment-analysis

# Export as JSON
mahavishnu capabilities get sentiment-analysis --format json

# Export descriptor as YAML
mahavishnu capabilities get sentiment-analysis --format yaml > descriptor.yaml

# Generate documentation
mahavishnu capabilities get sentiment-analysis --format markdown > README.md
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Capability: sentiment-analysis                                       ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Field                      │ Value                                  │
├────────────────────────────┼────────────────────────────────────────┤
│ Name                       │ sentiment-analysis                     │
│ Version                    │ 1.0.0                                  │
│ Description                │ Analyze sentiment from event text      │
│ Author                     │ Ecosystem Team                         │
│ Status                     │ loaded                                 │
│ Health                     │ healthy                                │
│ Loaded At                  │ 2025-02-05 15:30:45 UTC               │
│ Last Health Check          │ 2025-02-05 15:35:12 UTC               │
│ Dependencies               │ event_collector, python:nltk           │
│ Provides                   │ sentiment_analysis, text_processing    │
│ Implementation             │ capabilities.sentiment.SentimentAnalyzer│
│ Interface                  │ SentimentAnalyzer                      │
│ Health Check               │ capabilities.sentiment:health          │
│ Priority                   │ 10                                     │
│ Auto Load                  │ Yes                                    │
└────────────────────────────┴────────────────────────────────────────┘
```

### `load`

Load a capability from various sources.

**Usage:**
```bash
mahavishnu capabilities load [OPTIONS]
```

**Options:**
- `--name, -n`: Capability name
- `--source, -s`: Path to capability descriptor or directory
- `--auto-enable`: Automatically enable after loading
- `--from-github`: Load from GitHub repository
- `--repo`: GitHub repo (org/repo)
- `--capability`: Capability name in repo
- `--config, -c`: JSON configuration string

**Examples:**
```bash
# Load from descriptor file
mahavishnu capabilities load \
    --name sentiment-analysis \
    --source /path/to/capability/descriptor.yaml

# Load from directory (auto-discovers descriptor)
mahavishnu capabilities load --source /path/to/capabilities

# Load from GitHub
mahavishnu capabilities load \
    --from-github \
    --repo mahavishnu-ecosystem/capabilities \
    --capability sentiment-analysis

# Load with custom configuration
mahavishnu capabilities load \
    --name sentiment-analysis \
    --config '{"model": "gpt-4", "language": "en", "threshold": 0.7}'

# Discover and load first capability
mahavishnu capabilities load --source /path/to/capabilities
```

**Output:**
```
Loading capability: sentiment-analysis...
✓ Loaded capability: sentiment-analysis v1.0.0
  Status: loaded
  Health: healthy
```

### `unload`

Unload a currently loaded capability.

**Usage:**
```bash
mahavishnu capabilities unload NAME
```

**Examples:**
```bash
mahavishnu capabilities unload sentiment-analysis
```

**Output:**
```
Unloading capability: sentiment-analysis...
✓ Unloaded capability: sentiment-analysis
```

### `reload`

Hot-reload a capability without downtime.

**Usage:**
```bash
mahavishnu capabilities reload NAME [OPTIONS]
```

**Options:**
- `--config, -c`: New JSON configuration string

**Examples:**
```bash
# Reload with existing configuration
mahavishnu capabilities reload sentiment-analysis

# Reload with new configuration
mahavishnu capabilities reload sentiment-analysis \
    --config '{"model": "gpt-4-turbo", "threshold": 0.8}'
```

**Output:**
```
Reloading capability: sentiment-analysis...
✓ Reloaded capability: sentiment-analysis v1.0.0
  Status: loaded
  Health: healthy
```

### `hotswap`

Hot-swap one capability for another with zero downtime.

**Usage:**
```bash
mahavishnu capabilities hotswap [OPTIONS]
```

**Options:**
- `--old, -o`: Old capability name (required)
- `--new, -n`: New capability name (required)
- `--migrate-state/--no-migrate-state`: Migrate state (default: true)

**Examples:**
```bash
# Swap with state migration
mahavishnu capabilities hotswap \
    --old sentiment-analysis \
    --new sentiment-analysis-v2

# Swap without state migration
mahavishnu capabilities hotswap \
    --old analyzer \
    --new new-analyzer \
    --no-migrate-state
```

**Output:**
```
Hot-swapping: sentiment-analysis → sentiment-analysis-v2
✓ Swapped to: sentiment-analysis-v2 v2.0.0
  Status: loaded
  Health: healthy
```

### `discover`

Discover capabilities from filesystem or GitHub.

**Usage:**
```bash
mahavishnu capabilities discover [OPTIONS]
```

**Options:**
- `--from-filesystem`: Path to search for capabilities
- `--from-github`: GitHub repo (org/repo)
- `--register, -r`: Register discovered capabilities

**Examples:**
```bash
# Discover from filesystem
mahavishnu capabilities discover --from-filesystem /path/to/capabilities

# Discover and register from filesystem
mahavishnu capabilities discover \
    --from-filesystem /path/to/capabilities \
    --register

# Discover from GitHub
mahavishnu capabilities discover --from-github mahavishnu-ecosystem/capabilities

# Discover and register from GitHub
mahavishnu capabilities discover \
    --from-github mahavishnu-ecosystem/capabilities \
    --register
```

**Output:**
```
Discovering capabilities in: /path/to/capabilities
Discovered 3 capabilities:
  - sentiment-analysis v1.0.0
    Analyze sentiment from event text
    ✓ Registered
  - anomaly-detection v1.2.3
    Detect anomalies in time series data
    ✓ Registered
  - text-processor v2.1.0
    Process and normalize text data
    ✓ Registered
```

### `health`

Check health of capabilities.

**Usage:**
```bash
mahavishnu capabilities health [OPTIONS]
```

**Options:**
- `--name, -n`: Specific capability name
- `--all, -a`: Check all capabilities

**Examples:**
```bash
# Check all capabilities
mahavishnu capabilities health --all

# Check specific capability
mahavishnu capabilities health --name sentiment-analysis
```

**Output (All):**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Capability                   ┃ Status     ┃ Message                                          ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ sentiment-analysis           │ ● healthy  │ All systems operational                         │
│ anomaly-detection            │ ○ degraded │ High memory usage (85%)                         │
│ text-processor               │ ● unhealthy│ Connection timeout to upstream service          │
└──────────────────────────────┴────────────┴──────────────────────────────────────────────────┘
```

**Output (Single):**
```bash
$ mahavishnu capabilities health --name sentiment-analysis
✅ sentiment-analysis: healthy
   All systems operational
```

### `watch`

Monitor capabilities in real-time.

**Usage:**
```bash
mahavishnu capabilities watch [OPTIONS]
```

**Options:**
- `--interval, -i`: Update interval in seconds (default: 2.0)

**Examples:**
```bash
# Watch with default interval
mahavishnu capabilities watch

# Watch with 5 second interval
mahavishnu capabilities watch --interval 5
```

**Output:**
```
Live-updating table showing all capabilities with real-time status updates.
Press Ctrl+C to stop.
```

### `add`

Add a custom capability descriptor to the registry.

**Usage:**
```bash
mahavishnu capabilities add [OPTIONS]
```

**Options:**
- `--name, -n`: Capability name (required)
- `--descriptor, -d`: Path to descriptor file (required)

**Examples:**
```bash
mahavishnu capabilities add \
    --name custom-analysis \
    --descriptor /path/to/descriptor.yaml
```

**Output:**
```
✓ Added capability: custom-analysis
  Version: 1.0.0
  Description: Custom analysis implementation
```

### `validate`

Validate a capability descriptor before loading.

**Usage:**
```bash
mahavishnu capabilities validate [OPTIONS]
```

**Options:**
- `--descriptor, -d`: Path to descriptor file (required)

**Examples:**
```bash
mahavishnu capabilities validate \
    --descriptor /path/to/descriptor.yaml
```

**Output (Valid):**
```
✓ Descriptor is valid: sentiment-analysis
  Version: 1.0.0
  Description: Analyze sentiment from event text
```

**Output (Invalid):**
```
✗ Descriptor validation failed: sentiment-analysis
  - Invalid implementation path: Module 'capabilities.sentiment' not found
  - Unknown dependency: missing-capability
```

## Descriptor Schema

Capability descriptors are defined in YAML format:

```yaml
name: sentiment-analysis
version: "1.0.0"
description: Analyze sentiment from event text
author: "Ecosystem Team"

# Dependencies (capabilities or Python packages)
dependencies:
  - event_collector        # Capability dependency
  - python:nltk            # Python package
  - python:textblob

# Capabilities this provides
provides:
  - sentiment_analysis
  - text_processing

# Interface and implementation
interface: "SentimentAnalyzer"
implementation: "capabilities.sentiment_analyzer.SentimentAnalyzer"

# Configuration schema
config_schema:
  model: str
  language: str
  threshold: float

# Health check function (module:function)
health_check: "capabilities.sentiment_analyzer:health"

# Load on startup
auto_load: false

# Loading priority (higher loads first)
priority: 10
```

### Descriptor Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique capability identifier |
| `version` | string | Yes | Semantic version (e.g., "1.0.0") |
| `description` | string | Yes | Human-readable description |
| `author` | string | No | Author or team (default: "Unknown") |
| `dependencies` | list | No | Required capabilities/packages |
| `provides` | list | No | Capabilities this provides |
| `interface` | string | No | Interface class name |
| `implementation` | string | No | Implementation path |
| `config_schema` | dict | No | Configuration schema |
| `health_check` | string | No | Health check function path |
| `auto_load` | boolean | No | Load on startup (default: false) |
| `priority` | integer | No | Loading priority (default: 0) |

## Output Formats

The CLI supports multiple output formats:

### Table (default)
Human-readable table with colors and formatting:
```bash
mahavishnu capabilities list --format table
```

### JSON
Machine-readable JSON format:
```bash
mahavishnu capabilities list --format json
```

Output:
```json
[
  {
    "name": "sentiment-analysis",
    "version": "1.0.0",
    "status": "loaded",
    "health": "healthy",
    "description": "Analyze sentiment from event text",
    "author": "Ecosystem Team"
  }
]
```

### YAML
Configuration file format:
```bash
mahavishnu capabilities list --format yaml
```

Output:
```yaml
- name: sentiment-analysis
  version: 1.0.0
  status: loaded
  health: healthy
  description: Analyze sentiment from event text
  author: Ecosystem Team
```

### Markdown
Documentation format:
```bash
mahavishnu capabilities list --format markdown
```

Output:
```markdown
# Capabilities

## Overview

Total capabilities: 3

| Name | Version | Status | Health | Description |
|------|---------|--------|--------|-------------|
| sentiment-analysis | 1.0.0 | 🟢 loaded | ✅ healthy | Analyze sentiment from event text |
```

## Advanced Usage

### Batch Loading

Load multiple capabilities from a directory:

```bash
# Discover and load all
for descriptor in /path/to/capabilities/*.yaml; do
    mahavishnu capabilities load --source "$descriptor"
done

# Or use discover with register
mahavishnu capabilities discover \
    --from-filesystem /path/to/capabilities \
    --register
```

### Configuration Management

Create capability configurations:

```bash
# Create config file
cat > sentiment-config.json << EOF
{
  "model": "gpt-4",
  "language": "en",
  "threshold": 0.7
}
EOF

# Load with config
mahavishnu capabilities load \
    --name sentiment-analysis \
    --config "$(cat sentiment-config.json)"
```

### Health Monitoring

Set up automated health checks:

```bash
# Watch mode
mahavishnu capabilities watch --interval 10

# Cron job
*/5 * * * * mahavishnu capabilities health --all > /var/log/capability-health.log
```

### Zero-Downtime Updates

Perform capability updates without service interruption:

```bash
# Load new version
mahavishnu capabilities load --name sentiment-v2 --source /path/to/v2

# Hot-swap
mahavishnu capabilities hotswap \
    --old sentiment-analysis \
    --new sentiment-v2 \
    --migrate-state

# Verify health
mahavishnu capabilities health --name sentiment-v2
```

## Error Handling

The CLI provides clear error messages for common issues:

### Capability Not Found
```bash
$ mahavishnu capabilities get missing
Error: Capability not found: missing
```

### Invalid Descriptor
```bash
$ mahavishnu capabilities validate --descriptor bad.yaml
✗ Descriptor validation failed: bad-capability
  - Invalid implementation path: Module 'bad.module' not found
  - Unknown dependency: missing-dependency
```

### Load Failure
```bash
$ mahavishnu capabilities load --name bad-cap
Loading capability: bad-cap...
✗ Failed to load capability: ImportError: No module named 'bad_module'
```

## Integration with Mahavishnu

The capabilities CLI integrates with the Mahavishnu ecosystem:

### MCP Integration

```python
# Use capabilities via MCP
await mcp.call_tool("load_capability", {
    "name": "sentiment-analysis",
    "config": {"model": "gpt-4"}
})

# Check health
await mcp.call_tool("capability_health", {
    "name": "sentiment-analysis"
})
```

### Configuration

Enable capabilities in `settings/mahavishnu.yaml`:

```yaml
# Capability management
capabilities:
  enabled: true
  auto_load: true
  discovery_paths:
    - /path/to/capabilities
    - /usr/local/share/mahavishnu/capabilities

# Individual capability configuration
capability_configs:
  sentiment-analysis:
    model: gpt-4
    language: en
    threshold: 0.7
```

## Best Practices

### 1. Descriptor Management
- Keep descriptors in version control
- Use semantic versioning
- Document dependencies clearly

### 2. Loading Strategy
- Set appropriate priorities
- Use `auto_load: true` for core capabilities
- Load optional capabilities on demand

### 3. Health Checks
- Implement health check functions
- Monitor health regularly
- Set up alerts for unhealthy capabilities

### 4. Zero-Downtime Updates
- Test new versions before hot-swapping
- Implement state migration carefully
- Verify health after updates

### 5. Error Handling
- Handle import errors gracefully
- Provide clear error messages
- Implement fallback mechanisms

## Troubleshooting

### Capability Won't Load

1. Check descriptor validity:
   ```bash
   mahavishnu capabilities validate --descriptor descriptor.yaml
   ```

2. Verify dependencies:
   ```bash
   mahavishnu capabilities get capability-name
   ```

3. Check Python path and package installation

### Health Checks Failing

1. Check capability logs
2. Verify health check function implementation
3. Test health check manually:
   ```bash
   mahavishnu capabilities health --name capability-name
   ```

### Hot-Swap Issues

1. Ensure state migration is implemented
2. Check for breaking API changes
3. Test in non-production environment first

## Examples

### Complete Workflow

```bash
# 1. Discover capabilities
mahavishnu capabilities discover --from-filesystem ./capabilities --register

# 2. List available
mahavishnu capabilities list --available-only

# 3. Validate before loading
mahavishnu capabilities validate --descriptor ./capabilities/sentiment.yaml

# 4. Load with config
mahavishnu capabilities load \
    --name sentiment-analysis \
    --source ./capabilities/sentiment.yaml \
    --config '{"model": "gpt-4"}'

# 5. Check health
mahavishnu capabilities health --name sentiment-analysis

# 6. Monitor
mahavishnu capabilities watch --interval 5
```

### Production Deployment

```bash
# 1. Register all capabilities
mahavishnu capabilities discover \
    --from-filesystem /opt/mahavishnu/capabilities \
    --register

# 2. Load core capabilities
mahavishnu capabilities load --name core-pipeline
mahavishnu capabilities load --name event-collector

# 3. Verify health
mahavishnu capabilities health --all

# 4. Set up monitoring
nohup mahavishnu capabilities watch --interval 30 > /var/log/capability-monitor.log 2>&1 &
```

## API Reference

See [MCP Tools Specification](./MCP_TOOLS_SPECIFICATION.md) for complete API documentation.

## See Also

- [Capability Architecture](./CAPABILITY_ARCHITECTURE.md)
- [MCP Tools Specification](./MCP_TOOLS_SPECIFICATION.md)
- [Production Readiness](./PRODUCTION_READINESS_REPORT.md)
