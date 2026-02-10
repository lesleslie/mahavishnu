# Dynamic Capability Loading System

Complete runtime capability loading/unloading system for Mahavishnu with hot-swapping, dependency resolution, and health monitoring.

## Features

- **Hot-loading**: Load capabilities without restarting
- **Hot-swapping**: Zero-downtime capability replacement
- **Dependency resolution**: Automatic dependency management
- **Health monitoring**: Track capability health
- **Discovery**: Auto-discover from GitHub/filesystem
- **Validation**: Safe validation before loading
- **Rollback**: Automatic rollback on failure

## Quick Start

```python
from mahavishnu.integrations.capabilities import (
    CapabilityManager,
    CapabilityDescriptor,
)

# Create manager
manager = CapabilityManager()

# Register descriptor
descriptor = CapabilityDescriptor(
    name="sentiment_analysis",
    version="1.0.0",
    description="Analyze sentiment from text",
    implementation="mahavishnu.integrations.capabilities.builtin.sentiment_analysis:SentimentAnalysis",
)
manager.register_descriptor(descriptor)

# Load capability
instance = await manager.load_capability("sentiment_analysis")

# Use capability
result = await instance.instance.analyze("This is great!")
print(result)  # {'polarity': 0.5, 'classification': 'positive', ...}

# Hot-swap
await manager.hotswap("sentiment_analysis", "sentiment_analysis_v2")
```

## Core Classes

### CapabilityDescriptor

Pydantic model for capability metadata:

```python
descriptor = CapabilityDescriptor(
    name="capability_name",           # Required: Unique identifier
    version="1.0.0",                  # Required: Semantic version
    description="Description",        # Required: Human-readable description
    author="Author Name",             # Optional: Author/maintainer
    dependencies=["dep1", "dep2"],    # Optional: Required capabilities
    provides=["feature1"],            # Optional: Provided features
    interface="ICapability",          # Optional: Interface name
    implementation="module:Class",    # Required: Implementation path
    config_schema={...},              # Optional: Config JSON schema
    health_check="health_check",      # Optional: Health check method
    auto_load=False,                  # Optional: Load on startup
    priority=10,                      # Optional: Loading priority (0-100)
)
```

### CapabilityManager

Main interface for capability lifecycle management:

```python
manager = CapabilityManager()

# Register descriptor
manager.register_descriptor(descriptor)

# Load capability
instance = await manager.load_capability("capability_name")

# Unload capability
await manager.unload_capability("capability_name")

# Hot-reload
instance = await manager.reload_capability("capability_name")

# Hot-swap
new_instance = await manager.hotswap("old_name", "new_name")

# Health check
health, message = await manager.health_check("capability_name")

# Check all
results = await manager.health_check_all()

# List descriptors
descriptors = manager.list_descriptors()
```

### CapabilityDiscovery

Discover capabilities from various sources:

```python
discovery = CapabilityDiscovery()

# Discover from filesystem
descriptors = await discovery.discover_from_filesystem(
    directory="/path/to/capabilities",
    pattern="*.yaml",
    recursive=True,
)

# Discover from GitHub (placeholder)
descriptors = await discovery.discover_from_github(
    org="myorg",
    repo="myrepo",
    path="capabilities",
    branch="main",
)

# Validate capability
validation = await discovery.validate_capability(descriptor, registry)
```

### DynamicLoader

Load capabilities from external sources:

```python
loader = DynamicLoader(registry)

# Load from Git
descriptor = await loader.load_from_git(
    repo_url="https://github.com/org/repo.git",
    capability_name="my_capability",
    branch="main",
    config={...},
)

# Load from local
descriptor = await loader.load_from_local(
    directory="/path/to/capability",
    capability_name="my_capability",
    config={...},
)

# Hot-swap
result = await loader.hot_swap_capability("old", "new")

# Batch load
results = await loader.batch_load([
    ("capability1", None),
    ("capability2", {"param": "value"}),
])
```

## Built-in Capabilities

### 1. SentimentAnalysis

Analyze sentiment from text:

```python
# Load
instance = await manager.load_capability("sentiment_analysis")

# Use
result = await instance.instance.analyze("This is amazing!")
# {
#     "polarity": 0.75,
#     "subjectivity": 0.5,
#     "classification": "positive",
#     "positive_words": 2,
#     "negative_words": 0,
# }
```

**Config options:**
- `model`: "rule-based" (default), "vader", "textblob"

### 2. AnomalyDetection

Detect anomalies in time series:

```python
# Load with config
descriptor = CapabilityDescriptor(
    name="anomaly_detection",
    implementation="...",
)
config = {
    "window_size": 100,
    "threshold": 3.0,
    "method": "zscore",  # or "iqr"
}
instance = await manager.load_capability("anomaly_detection", config)

# Use
result = await instance.instance.detect("cpu_usage", 95.5)
# {
#     "is_anomaly": True,
#     "score": 4.2,
#     "baseline_mean": 50.0,
#     "baseline_std": 10.0,
#     "method": "zscore",
# }
```

**Config options:**
- `window_size`: Sliding window size (10-1000, default: 100)
- `threshold`: Anomaly threshold (1.0-10.0, default: 3.0)
- `method`: "zscore", "iqr", "isolation_forest"

### 3. EventSummarization

Summarize event groups:

```python
instance = await manager.load_capability("event_summarization")

events = [
    {"type": "error", "source": "app", "message": "Failed", "severity": "error"},
    {"type": "info", "source": "app", "message": "Started"},
]

summary = await instance.instance.summarize(events)
# {
#     "summary": "Processed 2 events. Top types: error (1), info (1).",
#     "statistics": {...},
#     "key_events": [...],
#     "timeline": [...],
# }
```

### 4. TrendAnalysis

Analyze trends and forecast:

```python
instance = await manager.load_capability("trend_analysis")

# Feed data
for value in [10, 15, 20, 25, 30]:
    result = await instance.instance.analyze("metric_name", value)
    # {"trend": "upward", "slope": 5.0, ...}

# Forecast
forecast = await instance.instance.forecast("metric_name", steps=5)
# {
#     "forecast": [
#         {"step": 1, "predicted_value": 35, ...},
#         {"step": 2, "predicted_value": 40, ...},
#     ],
# }
```

### 5. Enrichment

Enrich events with context:

```python
instance = await manager.load_capability("enrichment")

event = {"type": "error", "message": "Failed", "severity": "error"}

enriched = await instance.instance.enrich(event)
# {
#     "type": "error",
#     "message": "Failed",
#     "severity": "error",
#     "enriched": True,
#     "enrichment_timestamp": "2024-01-01T10:00:00Z",
#     "event_category": "error",
#     "severity_level": 70,
# }
```

## YAML Descriptors

Capabilities can be defined in YAML:

```yaml
name: sentiment_analysis
version: 1.0.0
description: Analyze sentiment from text
author: Mahavishnu Team
dependencies: []
provides:
  - sentiment_analysis
  - text_analysis
implementation: mahavishnu.integrations.capabilities.builtin.sentiment_analysis:SentimentAnalysis
config_schema:
  type: object
  properties:
    model:
      type: string
      enum: [rule-based, vader, textblob]
      default: rule-based
health_check: health_check
auto_load: false
priority: 10
```

Load from YAML:

```python
descriptor = CapabilityDescriptor.from_yaml("/path/to/descriptor.yaml")
manager.register_descriptor(descriptor)
```

## Creating Custom Capabilities

### 1. Implement the interface

```python
class MyCapability:
    """Custom capability implementation."""

    def __init__(self, config_param: str = "default"):
        self.config_param = config_param

    def initialize(self) -> None:
        """Initialize the capability."""
        # Setup resources
        pass

    async def process(self, data: dict) -> dict:
        """Process data."""
        # Your logic here
        return {"result": "processed"}

    def health_check(self) -> tuple[bool, str]:
        """Check health."""
        return True, "Operational"

    def cleanup(self) -> None:
        """Cleanup resources."""
        pass
```

### 2. Create descriptor

```python
descriptor = CapabilityDescriptor(
    name="my_capability",
    version="1.0.0",
    description="My custom capability",
    implementation="myapp.capabilities:MyCapability",
    config_schema={
        "type": "object",
        "properties": {
            "config_param": {"type": "string"},
        },
    },
)
```

### 3. Register and use

```python
manager.register_descriptor(descriptor)
instance = await manager.load_capability("my_capability", config={"config_param": "value"})

result = await instance.instance.process({"data": "input"})
```

## API Endpoints (MCP Tools)

When using via MCP, the following tools are available:

### `capabilities_list`
List all available capabilities.

### `capabilities_load`
Load a capability by name.

### `capabilities_unload`
Unload a capability.

### `capabilities_reload`
Hot-reload a capability.

### `capabilities_hotswap`
Hot-swap one capability for another.

### `capabilities_health`
Check health of capabilities.

### `capabilities_discover`
Discover capabilities from filesystem.

## Performance

- **Load time**: <5 seconds for most capabilities
- **Hot-swap**: <1 second for zero-downtime swap
- **Capacity**: Supports 100+ capabilities
- **Memory**: Minimal overhead per capability

## Error Handling

```python
from mahavishnu.core.errors import (
    CapabilityError,
    CapabilityNotFoundError,
    CapabilityLoadError,
    DependencyResolutionError,
)

try:
    await manager.load_capability("nonexistent")
except CapabilityNotFoundError as e:
    print(f"Capability not found: {e.message}")
    print(f"Details: {e.details}")

try:
    await manager.load_capability("broken_capability")
except CapabilityLoadError as e:
    print(f"Load failed: {e.message}")

try:
    await manager.load_capability("with_circular_deps")
except DependencyResolutionError as e:
    print(f"Dependency error: {e.message}")
    print(f"Dependency graph: {e.details}")
```

## Testing

Run tests:

```bash
# Run all capability tests
pytest tests/unit/test_capabilities/

# Run specific test
pytest tests/unit/test_capabilities/test_capability_loader.py::TestCapabilityLoader::test_load_capability

# Run with coverage
pytest --cov=mahavishnu/integrations/capabilities tests/unit/test_capabilities/
```

## Examples

See `examples/capabilities_example.py` for comprehensive examples:

1. Basic usage
2. Discovery
3. Dependency loading
4. Hot-swapping
5. Health monitoring
6. Batch operations
7. Trend analysis

Run examples:

```bash
python examples/capabilities_example.py
```

## Architecture

```
CapabilityManager
    ├── CapabilityLoader (load/unload instances)
    ├── CapabilityDiscovery (find capabilities)
    └── CapabilityHealthMonitor (check health)

CapabilityInstance (runtime state)
    ├── descriptor: CapabilityDescriptor
    ├── status: CapabilityStatus
    ├── health: CapabilityHealth
    └── instance: (loaded object)
```

## Best Practices

1. **Descriptors**: Store in version control with your code
2. **Dependencies**: Minimize to reduce complexity
3. **Health checks**: Always implement for monitoring
4. **Cleanup**: Properly release resources
5. **Configuration**: Use schema validation
6. **Testing**: Test both loading and functionality
7. **Versioning**: Use semantic versioning
8. **Documentation**: Document provided features

## Future Enhancements

- [ ] HTTP-based capability loading
- [ ] Capability marketplace integration
- [ ] Version conflict resolution
- [ ] Capability sandboxing
- [ ] Distributed capability loading
- [ ] Capability composition/orchestration
- [ ] Automatic capability scaling
