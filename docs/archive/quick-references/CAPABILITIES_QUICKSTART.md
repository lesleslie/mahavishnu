# Dynamic Capabilities Quick Start

Get started with Dynamic Capabilities in 5 minutes.

## Installation

The capabilities system is included with Mahavishnu:

```bash
pip install mahavishnu[capabilities]
```

## Basic Concepts

**Capabilities** are pluggable components that can be:
- Loaded at runtime without restart
- Hot-swapped for zero-downtime updates
- Monitored for health
- Discovered from filesystem or GitHub

## 5-Minute Quick Start

### 1. List Available Capabilities

```bash
mahavishnu capabilities list
```

Output:
```
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name               ┃ Version┃ Status ┃ Health ┃ Description          ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ - sentiment-analysis│ 1.0.0  │ unloaded│ unknown│ Analyze sentiment     │
│ - anomaly-detection │ 1.2.3  │ unloaded│ unknown│ Detect anomalies      │
└────────────────────┴────────┴────────┴────────┴──────────────────────┘
```

### 2. Load a Capability

```bash
mahavishnu capabilities load --name sentiment-analysis
```

Output:
```
Loading capability: sentiment-analysis...
✓ Loaded capability: sentiment-analysis v1.0.0
  Status: loaded
  Health: healthy
```

### 3. Check Health

```bash
mahavishnu capabilities health --all
```

Output:
```
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Capability         ┃ Status ┃ Message                     ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ sentiment-analysis │ ● healthy│ All systems operational    │
└────────────────────┴────────┴──────────────────────────────┘
```

### 4. Use the Capability

```python
from mahavishnu.integrations.capabilities import CapabilityManager

manager = CapabilityManager()
instance = await manager.load_capability("sentiment-analysis")

# Analyze sentiment
result = instance.instance.analyze("I love this product!")
print(result)
# {'sentiment': 'positive', 'polarity': 0.5, ...}
```

### 5. Monitor in Real-Time

```bash
mahavishnu capabilities watch
```

Press Ctrl+C to stop.

## Common Workflows

### Load with Custom Configuration

```bash
mahavishnu capabilities load \
    --name sentiment-analysis \
    --config '{"model": "nltk", "threshold": 0.7}'
```

### Hot-Reload for Updates

```bash
# Reload with new config
mahavishnu capabilities reload \
    --name sentiment-analysis \
    --config '{"model": "textblob"}'
```

### Hot-Swap to New Version

```bash
# Load new version
mahavishnu capabilities load --name sentiment-v2

# Swap with zero downtime
mahavishnu capabilities hotswap \
    --old sentiment-analysis \
    --new sentiment-v2 \
    --migrate-state
```

### Discover and Register

```bash
# From filesystem
mahavishnu capabilities discover \
    --from-filesystem ./capabilities \
    --register

# From GitHub
mahavishnu capabilities discover \
    --from-github mahavishnu-ecosystem/capabilities \
    --register
```

## Next Steps

1. **Create Your Own Capability**
   - See [Examples](../examples/capabilities/README.md)
   - Follow the step-by-step guide

2. **Advanced Usage**
   - Read [Full Documentation](./DYNAMIC_CAPABILITIES_CLI.md)
   - Learn about state migration, health checks, etc.

3. **Integration**
   - Use via MCP tools
   - Integrate with Mahavishnu workflows

## Key Commands

| Command | Description |
|---------|-------------|
| `list` | List all capabilities |
| `get` | Get capability details |
| `load` | Load a capability |
| `unload` | Unload a capability |
| `reload` | Hot-reload a capability |
| `hotswap` | Hot-swap capabilities |
| `health` | Check health |
| `watch` | Monitor in real-time |
| `discover` | Discover capabilities |
| `validate` | Validate descriptor |

## Help

Get help for any command:

```bash
mahavishnu capabilities --help
mahavishnu capabilities load --help
```

## Troubleshooting

### Capability Not Found

```bash
# Discover and register first
mahavishnu capabilities discover \
    --from-filesystem /path/to/capabilities \
    --register
```

### Import Errors

```bash
# Install dependencies
pip install textblob nltk numpy

# Validate descriptor
mahavishnu capabilities validate \
    --descriptor /path/to/descriptor.yaml
```

### Health Check Failures

```bash
# Check detailed health
mahavishnu capabilities health --name capability-name

# View details
mahavishnu capabilities get capability-name
```

## Resources

- [Full Documentation](./DYNAMIC_CAPABILITIES_CLI.md)
- [Examples](../examples/capabilities/README.md)
- [API Reference](./MCP_TOOLS_SPECIFICATION.md)
