# ADR 001: Use Oneiric for Configuration and Logging

## Status

**Accepted**

## Context

Mahavishnu needs a robust configuration and logging system that supports:

- Layered configuration with environment overrides
- Structured logging with multiple sinks
- Type-safe configuration models
- Hot-reload capability
- Runtime profiles (development, production, serverless)

### Options Considered

#### Option 1: Pure YAML + python-dotenv

- **Pros:** Simple, lightweight, no dependencies
- **Cons:** No type safety, no validation, no hot-reload, limited structuring

#### Option 2: Dynaconf

- **Pros:** Popular, supports multiple sources
- **Cons:** Not designed for orchestration, limited logging integration

#### Option 3: Oneiric (CHOSEN)

- **Pros:**
  - Native support for orchestration workflows
  - Pydantic-based configuration with full type safety
  - Structured logging with OpenTelemetry integration
  - Multi-sink logging (stdout, file, HTTP)
  - Runtime profiles (serverless, production, development)
  - Secret management with caching
  - Remote manifest loading with signature verification
- **Cons:**
  - Additional dependency
  - Learning curve for Oneiric patterns

## Decision

Use Oneiric for all configuration and logging in Mahavishnu.

### Rationale

1. **Orchestration-Native:** Oneiric is designed for orchestration workflows, making it a natural fit for Mahavishnu's multi-engine architecture.

1. **Type Safety:** Pydantic models provide compile-time and runtime type checking, preventing configuration errors.

1. **Observability:** Built-in OpenTelemetry integration and structured logging provide excellent observability out of the box.

1. **Flexibility:** Multi-sink logging and runtime profiles support diverse deployment scenarios.

1. **Ecosystem Alignment:** Crackerjack and Session-Buddy already use Oneiric patterns, ensuring consistency across the ecosystem.

### Configuration Hierarchy

Following Oneiric patterns, configuration loads in this order (later overrides earlier):

1. **Default values** in Pydantic models
1. **settings/mahavishnu.yaml** (committed to git, base configuration)
1. **settings/local.yaml** (gitignored, local development)
1. **Environment variables** `MAHAVISHNU_{FIELD}`

```python
from mcp_common.cli import MCPServerSettings

class MahavishnuSettings(MCPServerSettings):
    """Mahavishnu configuration extending MCPServerSettings."""

    repos_path: str = Field(default="repos.yaml")
    qc_enabled: bool = Field(default=True)
    session_enabled: bool = Field(default=True)
    # ... additional fields

# Load configuration
settings = MahavishnuSettings.load("mahavishnu")
```

### Logging Integration

```python
import structlog
from opentelemetry import trace

def setup_logging(settings: MahavishnuSettings) -> None:
    """Setup structured logging with OpenTelemetry integration."""
    processors = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Add trace correlation
        _add_correlation_id,
        # JSON for production
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    )

def _add_correlation_id(logger, method_name, event_dict):
    """Add OpenTelemetry trace correlation."""
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        event_dict["trace_id"] = format(current_span.context.trace_id, "032x")
        event_dict["span_id"] = format(current_span.context.span_id, "016x")
    return event_dict
```

## Consequences

### Positive

- Type-safe configuration prevents runtime errors
- Structured logs are queryable and aggregatable
- OpenTelemetry integration enables distributed tracing
- Hot-reload allows configuration changes without restart
- Runtime profiles support diverse deployment scenarios

### Negative

- Additional dependency to maintain
- Learning curve for developers unfamiliar with Oneiric
- Configuration migration path if Oneiric API changes

### Risks

- **Risk:** Oneiric becomes unmaintained
  **Mitigation:** Oneiric is actively maintained with clear API stability guarantees

- **Risk:** Breaking changes in Oneiric
  **Mitigation:** Pin to specific version (`oneiric~=0.1.0`), test upgrades thoroughly

## Implementation

### Phase 1: Configuration (Week 1, Day 1-2)

- [ ] Create `MahavishnuSettings` class extending `MCPServerSettings`
- [ ] Define all configuration fields with Pydantic
- [ ] Implement configuration loading from YAML and environment
- [ ] Add configuration validation

### Phase 2: Logging (Week 1, Day 3-4)

- [ ] Implement structured logging setup
- [ ] Add OpenTelemetry correlation
- [ ] Configure multiple log sinks (stdout, file, HTTP)
- [ ] Add log level configuration

### Phase 3: Testing (Week 1, Day 5)

- [ ] Test configuration loading order
- [ ] Test environment variable overrides
- [ ] Test logging output formats
- [ ] Test hot-reload functionality

## References

- [Oneiric Documentation](https://github.com/example/oneiric)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
